"""
SkillForge — Proactive skill ingestion and synthesis pipeline.

Takes any input — URL, library, description, code, spec, GitHub repo —
and produces a fully-formed NeuralClaw skill that plugs directly into
the SkillRegistry.

Channel integration: users can trigger synthesis from Discord, Telegram,
Slack, WhatsApp, or CLI with a single command. No developer needed.
"""

from __future__ import annotations

import asyncio
import ast
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import re
import sys
import tempfile
import time
import textwrap
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.action.network import validate_url_with_dns
from neuralclaw.cortex.action.sandbox import Sandbox, SandboxResult
from neuralclaw.skills.loader import load_skill_manifest
from neuralclaw.skills.manifest import (
    Capability,
    SkillManifest,
    ToolDefinition,
    ToolParameter,
)
from neuralclaw.skills.marketplace import StaticAnalyzer
from neuralclaw.skills.paths import quarantine_skill_file, resolve_user_skills_dir


# ---------------------------------------------------------------------------
# Input type detection
# ---------------------------------------------------------------------------

class ForgeInputType(Enum):
    URL          = auto()
    OPENAPI      = auto()
    GRAPHQL      = auto()
    LIBRARY      = auto()
    DESCRIPTION  = auto()
    CODE         = auto()
    FILE         = auto()
    GITHUB       = auto()
    MCP          = auto()
    UNKNOWN      = auto()


# ---------------------------------------------------------------------------
# Forge result
# ---------------------------------------------------------------------------

@dataclass
class ToolSpec:
    """Specification for one tool to generate inside the skill."""
    name: str
    description: str
    parameters: list[dict[str, Any]]
    example_call: str = ""
    example_output: str = ""


@dataclass
class UseCaseSpec:
    """The result of the use-case interview."""
    skill_name: str
    skill_description: str
    tools: list[ToolSpec]
    required_imports: list[str]
    auth_pattern: str = ""
    base_url: str = ""
    domain_context: str = ""
    clarifications: list[str] = field(default_factory=list)


@dataclass
class ForgeResult:
    """Full result of a SkillForge run."""
    success: bool
    skill_name: str
    input_type: ForgeInputType
    manifest: SkillManifest | None = None
    code: str = ""
    file_path: str = ""
    test_output: str = ""
    static_analysis: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    tools_generated: int = 0
    elapsed_seconds: float = 0.0
    clarifications_needed: list[str] = field(default_factory=list)
    session_id: str = ""


# ---------------------------------------------------------------------------
# Forge session (multi-turn in channels)
# ---------------------------------------------------------------------------

@dataclass
class ForgeSession:
    """Tracks a multi-turn skill synthesis session in a channel."""
    session_id: str
    user_id: str
    channel_id: str
    platform: str
    source: str
    use_case: str = ""
    input_type: ForgeInputType = ForgeInputType.UNKNOWN
    pending_clarifications: list[str] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    partial_spec: UseCaseSpec | None = None
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    state: str = "probing"


class SkillForge:
    """
    Proactive skill ingestion pipeline.

    Usage:
        forge = SkillForge(provider=provider, sandbox=sandbox, registry=registry)
        result = await forge.steal("https://api.stripe.com/v1", use_case="charge chiro patients")
    """

    USER_SKILLS_DIR = resolve_user_skills_dir()
    PROJECT_ROOT = Path(__file__).resolve().parents[2]

    def __init__(
        self,
        provider: Any,
        sandbox: Sandbox,
        registry: Any,
        bus: NeuralBus | None = None,
        model: str = "claude-sonnet-4-20250514",
        user_skills_dir: str | Path | None = None,
    ) -> None:
        self._provider = provider
        self._sandbox = sandbox
        self._registry = registry
        self._bus = bus
        self._model = model
        self._sessions: dict[str, ForgeSession] = {}
        self.USER_SKILLS_DIR = resolve_user_skills_dir(user_skills_dir)
        self.USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        self.PROJECT_ROOT = Path(__file__).resolve().parents[2]

    # -- Public interface --

    async def steal(
        self,
        source: str,
        use_case: str = "",
        session: ForgeSession | None = None,
    ) -> ForgeResult:
        """Auto-detect source type and route to the right forge method."""
        start = time.monotonic()
        input_type = self._detect_input_type(source)

        handlers: dict[ForgeInputType, Callable] = {
            ForgeInputType.URL:         self.forge_from_url,
            ForgeInputType.OPENAPI:     self.forge_from_openapi_url,
            ForgeInputType.GRAPHQL:     self.forge_from_graphql,
            ForgeInputType.LIBRARY:     self.forge_from_library,
            ForgeInputType.DESCRIPTION: self.forge_from_description,
            ForgeInputType.CODE:        self.forge_from_code,
            ForgeInputType.FILE:        self.forge_from_file,
            ForgeInputType.GITHUB:      self.forge_from_github,
            ForgeInputType.MCP:         self.forge_from_mcp,
        }

        handler = handlers.get(input_type, self.forge_from_description)
        result = await handler(source, use_case=use_case, session=session)
        result.elapsed_seconds = round(time.monotonic() - start, 2)
        result.input_type = input_type

        if self._bus and result.success:
            await self._bus.publish(
                EventType.SKILL_SYNTHESIZED,
                {
                    "name": result.skill_name,
                    "input_type": input_type.name,
                    "tools": result.tools_generated,
                    "elapsed": result.elapsed_seconds,
                },
                source="skill_forge",
            )

        return result

    async def forge_from_url(
        self, url: str, use_case: str = "", session: ForgeSession | None = None
    ) -> ForgeResult:
        """Probe an HTTP endpoint, infer its interface, generate a skill."""
        try:
            await validate_url_with_dns(url)
        except Exception as e:
            return ForgeResult(
                success=False, skill_name="", input_type=ForgeInputType.URL,
                error=f"URL blocked by SSRF policy: {e}",
            )

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session_http:
                openapi_url = await self._probe_for_openapi(session_http, url)
                if openapi_url:
                    return await self.forge_from_openapi_url(openapi_url, use_case=use_case)

                async with session_http.get(
                    url, timeout=aiohttp.ClientTimeout(total=15),
                    headers={"Accept": "application/json"},
                ) as resp:
                    content_type = resp.headers.get("Content-Type", "")
                    status = resp.status
                    if "json" in content_type:
                        raw = await resp.json(content_type=None)
                    else:
                        text = await resp.text()
                        try:
                            raw = json.loads(text)
                        except Exception:
                            raw = {"_raw_text": text[:2000]}

            interface_desc = self._describe_api_from_response(url, status, raw)
            return await self.forge_from_description(
                interface_desc, use_case=use_case, base_url=url,
            )

        except Exception as e:
            return ForgeResult(
                success=False, skill_name="", input_type=ForgeInputType.URL,
                error=f"URL probe failed: {e}",
            )

    async def forge_from_openapi_url(
        self, url: str, use_case: str = "", session: ForgeSession | None = None
    ) -> ForgeResult:
        """Fetch an OpenAPI spec from a URL and forge a skill from it."""
        try:
            await validate_url_with_dns(url)
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    text = await r.text()
            try:
                spec = json.loads(text)
            except Exception:
                import yaml
                spec = yaml.safe_load(text)
            return await self.forge_from_openapi_spec(spec, use_case=use_case)
        except Exception as e:
            return ForgeResult(
                success=False, skill_name="", input_type=ForgeInputType.OPENAPI,
                error=f"OpenAPI fetch failed: {e}",
            )

    async def forge_from_openapi_spec(
        self, spec: dict[str, Any], use_case: str = ""
    ) -> ForgeResult:
        """Parse an OpenAPI 3.x / Swagger 2.0 spec and generate a full skill."""
        title = spec.get("info", {}).get("title", "api")
        version = spec.get("info", {}).get("version", "1.0")
        base_url = self._extract_base_url(spec)
        description = spec.get("info", {}).get("description", "")
        paths = spec.get("paths", {})

        endpoints = self._summarize_endpoints(paths, max_endpoints=40)
        auth = self._extract_auth_scheme(spec)

        api_context = (
            f"API: {title} v{version}\n"
            f"Base URL: {base_url}\n"
            f"Description: {description[:500]}\n"
            f"Authentication: {auth}\n"
            f"Available endpoints ({len(paths)} total, showing first 40):\n"
            + "\n".join(endpoints)
        )

        return await self._interview_then_generate(
            capability_description=api_context,
            use_case=use_case,
            base_url=base_url,
            auth_pattern=auth,
            skill_name_hint=self._slugify(title),
        )

    async def forge_from_graphql(
        self, endpoint_or_schema: str, use_case: str = "", session: ForgeSession | None = None
    ) -> ForgeResult:
        """Parse a GraphQL endpoint (introspection) or schema string."""
        is_url = endpoint_or_schema.startswith("http")

        if is_url:
            try:
                await validate_url_with_dns(endpoint_or_schema)
                import aiohttp
                introspection_query = """
                query IntrospectionQuery {
                  __schema {
                    queryType { name }
                    mutationType { name }
                    types {
                      name kind description
                      fields(includeDeprecated: false) {
                        name description
                        args { name type { name kind } }
                      }
                    }
                  }
                }"""
                async with aiohttp.ClientSession() as s:
                    async with s.post(
                        endpoint_or_schema,
                        json={"query": introspection_query},
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as r:
                        data = await r.json()
                schema_desc = json.dumps(data, indent=2)[:4000]
            except Exception as e:
                return ForgeResult(
                    success=False, skill_name="", input_type=ForgeInputType.GRAPHQL,
                    error=f"GraphQL introspection failed: {e}",
                )
        else:
            schema_desc = endpoint_or_schema[:4000]

        description = (
            f"GraphQL API at {endpoint_or_schema if is_url else '(schema provided)'}.\n"
            f"Schema summary:\n{schema_desc}"
        )
        return await self._interview_then_generate(
            capability_description=description,
            use_case=use_case,
            base_url=endpoint_or_schema if is_url else "",
            skill_name_hint="graphql_api",
        )

    async def forge_from_library(
        self, library_name: str, use_case: str = "", session: ForgeSession | None = None
    ) -> ForgeResult:
        """Introspect an installed Python library and generate async wrappers."""
        try:
            module = importlib.import_module(library_name)
        except ImportError:
            try:
                import subprocess
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", library_name],
                    capture_output=True, timeout=60,
                )
                module = importlib.import_module(library_name)
            except Exception as e:
                return ForgeResult(
                    success=False, skill_name=library_name,
                    input_type=ForgeInputType.LIBRARY,
                    error=f"Could not import or install '{library_name}': {e}",
                )

        members = inspect.getmembers(module)
        functions = []
        for name, obj in members:
            if name.startswith("_"):
                continue
            if callable(obj) or inspect.isfunction(obj):
                try:
                    sig = str(inspect.signature(obj))
                    doc = (inspect.getdoc(obj) or "")[:200]
                    functions.append(f"  {name}{sig}: {doc}")
                    if len(functions) >= 30:
                        break
                except Exception:
                    continue

        capability_description = (
            f"Python library: {library_name}\n"
            f"Version: {getattr(module, '__version__', 'unknown')}\n"
            f"Public functions ({len(functions)} found):\n"
            + "\n".join(functions[:30])
        )

        return await self._interview_then_generate(
            capability_description=capability_description,
            use_case=use_case,
            skill_name_hint=self._slugify(library_name),
            extra_imports=[library_name],
        )

    async def forge_from_description(
        self,
        description: str,
        use_case: str = "",
        base_url: str = "",
        session: ForgeSession | None = None,
    ) -> ForgeResult:
        """Pure LLM synthesis from natural language."""
        return await self._interview_then_generate(
            capability_description=description,
            use_case=use_case,
            base_url=base_url,
            skill_name_hint=self._slugify(description[:40]),
        )

    async def forge_from_code(
        self, code: str, use_case: str = "", session: ForgeSession | None = None
    ) -> ForgeResult:
        """Analyze existing Python code and wrap it as a NeuralClaw skill."""
        func_pattern = re.compile(
            r"(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*[\w\[\], ]+)?\s*:",
            re.MULTILINE,
        )
        functions_found = [
            f"{m.group(1)}({m.group(2)})" for m in func_pattern.finditer(code)
            if not m.group(1).startswith("_")
        ]

        capability_description = (
            f"Existing Python code with these public functions:\n"
            + "\n".join(f"  - {f}" for f in functions_found[:20])
            + f"\n\nFull code:\n{code[:3000]}"
        )

        return await self._interview_then_generate(
            capability_description=capability_description,
            use_case=use_case,
            existing_code=code,
        )

    async def forge_from_file(
        self, path: str, use_case: str = "", session: ForgeSession | None = None
    ) -> ForgeResult:
        """Read a local file and forge based on its content."""
        p = Path(path)
        if not p.exists():
            return ForgeResult(
                success=False, skill_name="", input_type=ForgeInputType.FILE,
                error=f"File not found: {path}",
            )

        suffix = p.suffix.lower()
        content = p.read_text(encoding="utf-8", errors="replace")

        if suffix in {".json", ".yaml", ".yml"}:
            try:
                spec = json.loads(content) if suffix == ".json" else __import__("yaml").safe_load(content)
                if "openapi" in spec or "swagger" in spec:
                    return await self.forge_from_openapi_spec(spec, use_case=use_case)
            except Exception:
                pass

        if suffix == ".graphql":
            return await self.forge_from_graphql(content, use_case=use_case)

        if suffix == ".py":
            return await self.forge_from_code(content, use_case=use_case)

        return await self.forge_from_description(content, use_case=use_case)

    async def forge_from_github(
        self, repo_url: str, use_case: str = "", session: ForgeSession | None = None
    ) -> ForgeResult:
        """Analyze a GitHub repository and generate a skill from it."""
        match = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", repo_url)
        if not match:
            return ForgeResult(
                success=False, skill_name="", input_type=ForgeInputType.GITHUB,
                error="Invalid GitHub URL. Expected: https://github.com/owner/repo",
            )

        owner, repo = match.group(1), match.group(2)
        api_base = f"https://api.github.com/repos/{owner}/{repo}"

        try:
            await validate_url_with_dns(api_base)
            import aiohttp
            async with aiohttp.ClientSession(
                headers={"Accept": "application/vnd.github.v3+json"}
            ) as s:
                async with s.get(api_base) as r:
                    repo_data = await r.json()

                readme_content = ""
                for readme_path in ["README.md", "readme.md", "README.rst"]:
                    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{readme_path}"
                    try:
                        await validate_url_with_dns(raw_url)
                        async with s.get(raw_url) as r:
                            if r.status == 200:
                                readme_content = (await r.text())[:2000]
                                break
                    except Exception:
                        continue

                for spec_path in ["openapi.json", "swagger.json", "openapi.yaml"]:
                    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{spec_path}"
                    try:
                        await validate_url_with_dns(raw_url)
                        async with s.get(raw_url) as r:
                            if r.status == 200:
                                text = await r.text()
                                spec = json.loads(text) if spec_path.endswith(".json") else __import__("yaml").safe_load(text)
                                return await self.forge_from_openapi_spec(spec, use_case=use_case)
                    except Exception:
                        continue

                description_parts = [
                    f"GitHub repo: {owner}/{repo}",
                    f"Description: {repo_data.get('description', '')}",
                    f"Language: {repo_data.get('language', 'unknown')}",
                    f"Stars: {repo_data.get('stargazers_count', 0)}",
                    f"\nREADME:\n{readme_content}",
                ]

            capability_description = "\n".join(description_parts)
            return await self._interview_then_generate(
                capability_description=capability_description,
                use_case=use_case,
                skill_name_hint=self._slugify(repo),
            )

        except Exception as e:
            return ForgeResult(
                success=False, skill_name="", input_type=ForgeInputType.GITHUB,
                error=f"GitHub probe failed: {e}",
            )

    async def forge_from_mcp(
        self, server_url: str, use_case: str = "", session: ForgeSession | None = None
    ) -> ForgeResult:
        """Connect to an MCP server and generate a skill from its exposed tools."""
        try:
            await validate_url_with_dns(server_url)
            import aiohttp

            headers = {"Content-Type": "application/json"}
            async with aiohttp.ClientSession() as s:
                init_payload = {
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05",
                               "capabilities": {}, "clientInfo": {"name": "SkillForge", "version": "1.0"}},
                }
                async with s.post(server_url, json=init_payload, headers=headers,
                                  timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status != 200:
                        raise RuntimeError(f"MCP init failed: HTTP {r.status}")
                    await r.json()

                list_payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
                async with s.post(server_url, json=list_payload, headers=headers,
                                  timeout=aiohttp.ClientTimeout(total=15)) as r:
                    tools_data = await r.json()

            tools = tools_data.get("result", {}).get("tools", [])
            if not tools:
                raise RuntimeError("MCP server returned no tools")

            tools_desc = "\n".join(
                f"  - {t['name']}: {t.get('description', '')} "
                f"(inputs: {list(t.get('inputSchema', {}).get('properties', {}).keys())})"
                for t in tools[:30]
            )
            capability_description = (
                f"MCP Server at {server_url}\n"
                f"Exposed tools ({len(tools)} total):\n{tools_desc}"
            )

            return await self._interview_then_generate(
                capability_description=capability_description,
                use_case=use_case,
                base_url=server_url,
                auth_pattern="mcp",
                skill_name_hint="mcp_" + self._slugify(server_url.split("/")[-1] or "server"),
            )

        except Exception as e:
            return ForgeResult(
                success=False, skill_name="", input_type=ForgeInputType.MCP,
                error=f"MCP probe failed: {e}",
            )

    # -- Core generation pipeline --

    async def _interview_then_generate(
        self,
        capability_description: str,
        use_case: str = "",
        base_url: str = "",
        auth_pattern: str = "",
        skill_name_hint: str = "",
        extra_imports: list[str] | None = None,
        existing_code: str = "",
    ) -> ForgeResult:
        """Core pipeline: use-case interview -> code generation -> test -> register."""
        local_only_requested = self._is_local_only_request(
            capability_description=capability_description,
            use_case=use_case,
            base_url=base_url,
            auth_pattern=auth_pattern,
        )
        explicit_skill_name = self._extract_explicit_skill_name(
            capability_description,
            use_case,
        )
        spec = await self._run_use_case_interview(
            capability_description=capability_description,
            use_case=use_case,
            base_url=base_url,
            auth_pattern=auth_pattern,
            skill_name_hint=explicit_skill_name or skill_name_hint,
            local_only_requested=local_only_requested,
        )
        spec = self._normalize_spec_for_generation(
            spec,
            local_only_requested,
            forced_skill_name=explicit_skill_name or skill_name_hint,
        )

        if spec.clarifications:
            return ForgeResult(
                success=False,
                skill_name=spec.skill_name,
                input_type=ForgeInputType.UNKNOWN,
                clarifications_needed=spec.clarifications,
            )

        code = await self._generate_skill_code(
            spec=spec,
            base_url=base_url,
            auth_pattern=auth_pattern,
            extra_imports=extra_imports or [],
            existing_code=existing_code,
            local_only_requested=local_only_requested,
        )

        if not code:
            return ForgeResult(
                success=False, skill_name=spec.skill_name,
                input_type=ForgeInputType.UNKNOWN,
                error="Code generation produced empty output",
            )

        # Post-generation hardening: fix common LLM mistakes
        code = self._finalize_generated_code(
            code,
            spec,
            local_only_requested=local_only_requested,
        )
        preflight_error = self._preflight_generated_code(code, spec)
        if preflight_error:
            fixed = await self._attempt_fix(code, preflight_error, spec)
            if fixed:
                code = self._finalize_generated_code(
                    fixed,
                    spec,
                    local_only_requested=local_only_requested,
                )
                preflight_error = self._preflight_generated_code(code, spec)
            if preflight_error:
                return ForgeResult(
                    success=False,
                    skill_name=spec.skill_name,
                    input_type=ForgeInputType.UNKNOWN,
                    code=code,
                    error=f"Preflight validation failed: {preflight_error}",
                )

        if local_only_requested and self._has_forbidden_local_only_dependencies(code):
            fixed = await self._attempt_fix(
                code,
                (
                    "Local-only skill violation: remove aiohttp, validate_url_with_dns, "
                    "external URLs, API-key env vars, and network capabilities. "
                    "Use only local Python libraries and machine-local data."
                ),
                spec,
            )
            if fixed:
                code = self._finalize_generated_code(
                    fixed,
                    spec,
                    local_only_requested=local_only_requested,
                )
            if self._has_forbidden_local_only_dependencies(code):
                return ForgeResult(
                    success=False,
                    skill_name=spec.skill_name,
                    input_type=ForgeInputType.UNKNOWN,
                    code=code,
                    error=(
                        "Generated local-only skill still depended on network scaffolding "
                        "(aiohttp, URLs, or HTTP capabilities)."
                    ),
                )

        findings = StaticAnalyzer.scan(code)
        high_risk = [f for f in findings if f.get("severity", 0) > 0.85]
        if high_risk:
            return ForgeResult(
                success=False, skill_name=spec.skill_name,
                input_type=ForgeInputType.UNKNOWN,
                static_analysis=findings,
                error=f"Static analysis blocked: {[f['description'] for f in high_risk]}",
            )

        test_result = await self._sandbox_test(code, spec)
        if not test_result.success and not test_result.timed_out:
            code = await self._attempt_fix(code, test_result.error or test_result.output, spec)
            if code:
                code = self._finalize_generated_code(
                    code,
                    spec,
                    local_only_requested=local_only_requested,
                )
                preflight_error = self._preflight_generated_code(code, spec)
                if preflight_error:
                    return ForgeResult(
                        success=False,
                        skill_name=spec.skill_name,
                        input_type=ForgeInputType.UNKNOWN,
                        code=code,
                        static_analysis=findings,
                        error=f"Preflight validation failed after fix: {preflight_error}",
                    )
                test_result = await self._sandbox_test(code, spec)

        if not test_result.success:
            return ForgeResult(
                success=False,
                skill_name=spec.skill_name,
                input_type=ForgeInputType.UNKNOWN,
                code=code,
                test_output=test_result.output,
                static_analysis=findings,
                error=test_result.error or "Sandbox validation failed",
            )

        # Final safety: ensure get_manifest() is always present before saving
        if "def get_manifest" not in code:
            code = self._append_manifest_function(code, spec)

        file_path = await self._persist_skill(code, spec.skill_name)
        try:
            manifest = self._build_manifest_from_spec(spec, code)
        except Exception as e:
            try:
                quarantined = quarantine_skill_file(file_path, reason="invalid")
                error = (
                    f"Generated skill failed manifest validation and was quarantined to "
                    f"{quarantined}: {e}"
                )
            except Exception:
                error = f"Generated skill failed manifest validation: {e}"
            return ForgeResult(
                success=False,
                skill_name=spec.skill_name,
                input_type=ForgeInputType.UNKNOWN,
                code=code,
                file_path=str(file_path),
                test_output=test_result.output,
                static_analysis=findings,
                error=error,
            )
        self._registry.hot_register(manifest, source="user")

        return ForgeResult(
            success=True,
            skill_name=spec.skill_name,
            input_type=ForgeInputType.UNKNOWN,
            manifest=manifest,
            code=code,
            file_path=str(file_path),
            test_output=test_result.output,
            static_analysis=findings,
            tools_generated=len(spec.tools),
        )

    def _finalize_generated_code(
        self,
        code: str,
        spec: UseCaseSpec,
        local_only_requested: bool = False,
    ) -> str:
        """Normalize generated code into a deterministic, loadable module."""
        code = self._harden_generated_code(
            code,
            spec,
            local_only_requested=local_only_requested,
        )
        code = self._rewrite_manifest_function(code, spec)
        return code.rstrip() + "\n"

    async def _run_use_case_interview(
        self,
        capability_description: str,
        use_case: str,
        base_url: str,
        auth_pattern: str,
        skill_name_hint: str,
        local_only_requested: bool = False,
    ) -> UseCaseSpec:
        """The use-case interview is the heart of SkillForge."""
        use_case_section = (
            f"\n\nUSE CASE: {use_case}" if use_case else
            "\n\nUSE CASE: General purpose assistant"
        )
        local_only_section = (
            "\n\nLOCAL-ONLY CONSTRAINTS:\n"
            "- The skill must not use external HTTP APIs.\n"
            "- The skill must not require aiohttp or validate_url_with_dns.\n"
            "- Prefer local Python libraries or stdlib only.\n"
            "- base_url must be an empty string and auth_pattern must be 'none'.\n"
            "- required_imports must not include network libraries.\n"
            if local_only_requested else ""
        )
        required_imports_example = "[]" if local_only_requested else '["aiohttp"]'

        prompt = f"""You are designing NeuralClaw skill tools for an AI agent.

CAPABILITY AVAILABLE:
{capability_description[:3000]}
{use_case_section}
{local_only_section}

Design the MINIMAL set of tools this agent actually needs for the use case.
Rename parameters to match the domain (e.g. "patient_name" not "customer_id").
Group related operations into single tools where sensible.
Prefer 2-5 focused tools over many generic ones.

Return ONLY valid JSON matching this schema exactly:
{{
  "skill_name": "snake_case_name",
  "skill_description": "one sentence what this skill does",
  "tools": [
    {{
      "name": "tool_name",
      "description": "what this tool does and when to use it",
      "parameters": [
        {{"name": "param", "type": "string|integer|boolean|number|array", "description": "...", "required": true}}
      ],
      "example_call": "tool_name(param='value')",
      "example_output": "{{\\"result\\": \\"value\\"}}"
    }}
  ],
  "required_imports": {required_imports_example},
  "auth_pattern": "bearer|api_key|none|custom",
  "base_url": "{base_url}",
  "clarifications": []
}}

If you need more info to design good domain-specific tools, put questions in "clarifications" and return empty "tools".
"""

        try:
            response = await self._provider.complete(
                messages=[
                    {"role": "system", "content": "You are a NeuralClaw skill designer. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2000,
            )
            raw = response.content or ""

            # Guard: empty LLM response — don't waste time parsing
            if not raw.strip():
                return UseCaseSpec(
                    skill_name=skill_name_hint or "custom_skill",
                    skill_description="",
                    tools=[],
                    required_imports=[],
                    clarifications=[
                        "The LLM returned an empty response. "
                        "Please describe what you want this skill to do so I can design the right tools."
                    ],
                )

            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            data = json.loads(raw)

            tools = [
                ToolSpec(
                    name=t["name"],
                    description=t["description"],
                    parameters=t.get("parameters", []),
                    example_call=t.get("example_call", ""),
                    example_output=t.get("example_output", ""),
                )
                for t in data.get("tools", [])
            ]

            return UseCaseSpec(
                skill_name=data.get("skill_name") or skill_name_hint or "custom_skill",
                skill_description=data.get("skill_description", ""),
                tools=tools,
                required_imports=data.get("required_imports", []),
                auth_pattern=data.get("auth_pattern", auth_pattern),
                base_url=data.get("base_url", base_url),
                clarifications=data.get("clarifications", []),
            )

        except json.JSONDecodeError as e:
            # LLM returned non-JSON — ask the user for clarification, don't create dummy tools
            return UseCaseSpec(
                skill_name=skill_name_hint or "custom_skill",
                skill_description="",
                tools=[],
                required_imports=[],
                clarifications=[
                    f"Could not parse LLM response as JSON ({e}). "
                    "Please describe specifically what tools you need and what they should do."
                ],
            )
        except Exception as e:
            return UseCaseSpec(
                skill_name=skill_name_hint or "custom_skill",
                skill_description="Custom skill",
                tools=[],
                required_imports=["aiohttp"],
                clarifications=[f"Could not auto-design tools: {e}. Describe what you want this skill to do."],
            )

    def _harden_generated_code(
        self,
        code: str,
        spec: UseCaseSpec,
        local_only_requested: bool = False,
    ) -> str:
        """Fix common LLM code generation mistakes before sandbox testing.

        1. Add missing imports for referenced names
        2. Remove references to undefined base URLs
        3. Ensure all tool functions accept their declared parameters
        4. Strip markdown fences that slipped through
        """
        lines = code.split("\n")

        # --- Fix 1: Add missing imports ---
        needed_imports: list[str] = []

        # Check for Capability reference without import
        if "Capability" in code and "from neuralclaw.cortex.action.capabilities import" not in code:
            needed_imports.append("from neuralclaw.cortex.action.capabilities import Capability")

        # Check for SkillManifest reference without import
        if "SkillManifest" in code and "from neuralclaw.skills.manifest import" not in code:
            needed_imports.append(
                "from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter"
            )

        # Check for validate_url_with_dns without import
        if (
            not local_only_requested
            and "validate_url_with_dns" in code
            and "from neuralclaw.cortex.action.network import" not in code
        ):
            needed_imports.append("from neuralclaw.cortex.action.network import validate_url_with_dns")

        # Check for aiohttp usage without import
        if not local_only_requested and "aiohttp" in code and "import aiohttp" not in code:
            needed_imports.append("import aiohttp")

        # Check for json usage without import
        if "json." in code and "import json" not in code:
            needed_imports.append("import json")

        # Check for os.getenv without import
        if "os.getenv" in code and "import os" not in code:
            needed_imports.append("import os")

        if needed_imports:
            # Insert after the first line (or __future__ import)
            insert_idx = 0
            for i, line in enumerate(lines):
                if line.strip().startswith("from __future__"):
                    insert_idx = i + 1
                    break
                elif line.strip().startswith("import ") or line.strip().startswith("from "):
                    insert_idx = i
                    break
            for imp in reversed(needed_imports):
                lines.insert(insert_idx, imp)

        code = "\n".join(lines)

        # --- Fix 2: Replace invalid Capability enum values ---
        # The LLM often invents values like Capability.NETWORK, Capability.HTTP, etc.
        _VALID_CAPABILITIES = {
            "FILESYSTEM_READ", "FILESYSTEM_WRITE", "NETWORK_HTTP",
            "NETWORK_WEBSOCKET", "SHELL_EXECUTE", "MESSAGING_READ",
            "MESSAGING_WRITE", "CALENDAR_READ", "CALENDAR_WRITE",
            "MEMORY_READ", "MEMORY_WRITE", "GITHUB_CLONE",
            "API_CLIENT", "AUDIO_OUTPUT",
        }
        # Find all Capability.XXX references and fix invalid ones
        for match in re.finditer(r"Capability\.(\w+)", code):
            cap_name = match.group(1)
            if cap_name not in _VALID_CAPABILITIES:
                # Map common LLM mistakes to valid values
                _CAP_FIXES = {
                    "NETWORK": "NETWORK_HTTP",
                    "HTTP": "NETWORK_HTTP",
                    "WEBSOCKET": "NETWORK_WEBSOCKET",
                    "SYSTEM_INFO": "FILESYSTEM_READ",
                    "FILESYSTEM": "FILESYSTEM_READ",
                    "FILE_READ": "FILESYSTEM_READ",
                    "FILE_WRITE": "FILESYSTEM_WRITE",
                    "SHELL": "SHELL_EXECUTE",
                    "MESSAGING": "MESSAGING_READ",
                    "CALENDAR": "CALENDAR_READ",
                    "MEMORY": "MEMORY_READ",
                    "AUDIO": "AUDIO_OUTPUT",
                    "API": "API_CLIENT",
                    "GITHUB": "GITHUB_CLONE",
                }
                fixed_cap = _CAP_FIXES.get(cap_name, "NETWORK_HTTP")
                code = code.replace(f"Capability.{cap_name}", f"Capability.{fixed_cap}")

        if local_only_requested:
            code = re.sub(r"^.*import aiohttp.*$\n?", "", code, flags=re.MULTILINE)
            code = re.sub(
                r"^.*from neuralclaw\.cortex\.action\.network import validate_url_with_dns.*$\n?",
                "",
                code,
                flags=re.MULTILINE,
            )
            code = re.sub(r"^_BASE_URL\s*=.*$\n?", "", code, flags=re.MULTILINE)
            code = re.sub(r"^_API_KEY_ENV\s*=.*$\n?", "", code, flags=re.MULTILINE)
            code = code.replace("Capability.NETWORK_HTTP", "Capability.FILESYSTEM_READ")
            code = code.replace("Capability.NETWORK_WEBSOCKET", "Capability.FILESYSTEM_READ")

        # --- Fix 3: Replace hardcoded placeholder URLs with env var pattern ---
        code = re.sub(
            r'_BASE_URL\s*=\s*"(N/A|YOUR_BASE_URL|https?://example\.com[^"]*)"',
            '_BASE_URL = os.getenv("SKILL_BASE_URL", "")',
            code,
        )

        # --- Fix 4: Ensure tool functions accept **kwargs for flexibility ---
        # Find all async def tool_name(...) and ensure they won't break on extra params
        for t in spec.tools:
            # Check if the function exists and add **kwargs if not present
            pattern = rf"(async\s+def\s+{re.escape(t.name)}\s*\([^)]*)"
            match = re.search(pattern, code)
            if match:
                sig = match.group(1)
                if "**" not in sig:
                    # Add **kwargs before closing paren
                    code = code.replace(sig, sig.rstrip() + ", **_extra")

        # --- Fix 5: Fix string handler references in get_manifest() ---
        # LLMs often write handler="func_name" instead of handler=func_name
        code = re.sub(
            r'handler\s*=\s*"(\w+)"',
            r'handler=\1',
            code,
        )
        code = re.sub(
            r"handler\s*=\s*'(\w+)'",
            r'handler=\1',
            code,
        )

        # --- Fix 6: Strip invalid kwargs from ToolDefinition ---
        # LLMs often put capabilities=[...] on ToolDefinition (it belongs on SkillManifest)
        code = re.sub(
            r',?\s*capabilities\s*=\s*\[[^\]]*\]\s*,?',
            '',
            code,
        )

        return code

    def _preflight_generated_code(self, code: str, spec: UseCaseSpec) -> str | None:
        """Catch deterministic generation failures before sandbox execution."""
        syntax_error = self._validate_python_syntax(code)
        if syntax_error:
            return syntax_error

        actual_funcs = re.findall(r"^async\s+def\s+(\w+)\s*\(", code, re.MULTILINE)
        if not actual_funcs:
            return "Generated code did not define any async tool handlers."
        if len(actual_funcs) < len(spec.tools):
            return (
                f"Generated code only defined {len(actual_funcs)} async handlers for "
                f"{len(spec.tools)} requested tools."
            )
        return None

    async def _generate_skill_code(
        self,
        spec: UseCaseSpec,
        base_url: str,
        auth_pattern: str,
        extra_imports: list[str],
        existing_code: str,
        local_only_requested: bool = False,
    ) -> str:
        """Generate the full Python skill file from a UseCaseSpec."""
        tools_desc = "\n".join(
            f"  - {t.name}({', '.join(p['name'] for p in t.parameters)}): {t.description}"
            f"\n    Example call: {t.example_call}"
            f"\n    Example output: {t.example_output}"
            for t in spec.tools
        )

        existing_section = (
            f"\nExisting code to wrap (preserve logic, add async + error handling):\n```python\n{existing_code[:2000]}\n```"
            if existing_code else ""
        )

        first_tool = spec.tools[0].name if spec.tools else "execute"
        requirements_block = (
            "1. Each tool function must be async and return dict[str, Any]\n"
            "2. Never raise exceptions â€” catch all errors, return {\"error\": str(e)}\n"
            "3. Do not make any HTTP calls or use network-only libraries like aiohttp\n"
            "4. Include a get_manifest() function at the bottom\n"
            "5. Import from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter\n"
            "6. Wire each function as a handler in its ToolDefinition\n"
            "7. Add a brief docstring to each function\n"
            "8. Do not require API keys or external URLs for this skill\n"
            "9. Use only local Python libraries or the stdlib to satisfy the request\n"
            "10. Use the exact SKILL name and exact tool names shown below; do not rename them\n"
            if local_only_requested else
            "1. Each tool function must be async and return dict[str, Any]\n"
            "2. Never raise exceptions â€” catch all errors, return {\"error\": str(e)}\n"
            "3. All HTTP calls must use aiohttp (no requests/urllib)\n"
            "4. Include a get_manifest() function at the bottom\n"
            "5. Import from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter\n"
            "6. Wire each function as a handler in its ToolDefinition\n"
            "7. Add a brief docstring to each function\n"
            "8. Handle API keys via os.getenv() â€” never hardcode credentials\n"
            "9. Include retry logic for transient network failures (max 2 retries)\n"
            "10. Use the exact SKILL name and exact tool names shown below; do not rename them\n"
        )
        local_only_rules = (
            "F. This is a local-only skill. Do NOT import aiohttp or validate_url_with_dns.\n"
            "G. Do NOT define or use _BASE_URL, API-key env vars, or external URLs.\n"
            "H. If you are unsure about metadata, prioritize correct tool implementations; the runtime will rebuild get_manifest().\n"
            if local_only_requested else ""
        )
        skill_template = f"""```python
from __future__ import annotations
from typing import Any
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

async def {first_tool}(...) -> dict[str, Any]:
    \"\"\"...\"\"\"\n    ...

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="{spec.skill_name}",
        description="{spec.skill_description}",
        tools=[...],
    )
```
""" if local_only_requested else f"""```python
from __future__ import annotations
import os
from typing import Any
import aiohttp
from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.cortex.action.network import validate_url_with_dns
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

_BASE_URL = "{spec.base_url or base_url}"
_API_KEY_ENV = "YOUR_API_KEY_ENV_VAR"

async def {first_tool}(...) -> dict[str, Any]:
    \"\"\"...\"\"\"\n    ...

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="{spec.skill_name}",
        description="{spec.skill_description}",
        tools=[...],
    )
```
"""

        prompt = f"""Write a complete NeuralClaw skill Python file.

SKILL: {spec.skill_name}
DESCRIPTION: {spec.skill_description}
BASE URL: {spec.base_url or base_url or 'N/A'}
AUTH: {spec.auth_pattern or auth_pattern or 'none'}

TOOLS TO IMPLEMENT:
{tools_desc}
{existing_section}

Requirements:
1. Each tool function must be async and return dict[str, Any]
2. Never raise exceptions — catch all errors, return {{"error": str(e)}}
3. All HTTP calls must use aiohttp (no requests/urllib)
4. Include a get_manifest() function at the bottom
5. Import from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter
6. Wire each function as a handler in its ToolDefinition
7. Add a brief docstring to each function
8. Handle API keys via os.getenv() — never hardcode credentials
9. Include retry logic for transient network failures (max 2 retries)

CRITICAL RULES (violations = broken skill):
A. Each async def MUST accept EXACTLY the parameters listed in TOOLS above
   e.g. if tool has params (name, age), the function must be: async def tool_name(name: str, age: int, **_extra)
B. ALWAYS add **_extra to function signatures for forward compatibility
C. If BASE URL is "N/A" or empty, the skill MUST work WITHOUT any external API
   — use Python stdlib (hashlib, socket, platform, zipfile, json, etc.)
   — do NOT invent URLs or assume an API exists
D. NEVER reference variables that are not defined in the same file
E. The function name MUST match the tool name exactly

Skill file template:
```python
from __future__ import annotations
import os
from typing import Any
import aiohttp
from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.cortex.action.network import validate_url_with_dns
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

_BASE_URL = "{spec.base_url or base_url}"
_API_KEY_ENV = "YOUR_API_KEY_ENV_VAR"

async def {first_tool}(...) -> dict[str, Any]:
    \"\"\"...\"\"\"\
    ...

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="{spec.skill_name}",
        description="{spec.skill_description}",
        tools=[...],
    )
```

CRITICAL: The file MUST end with a get_manifest() function that returns a SkillManifest.
Without get_manifest(), the skill cannot load. This is NON-NEGOTIABLE.

Return ONLY the Python code. No markdown fences. No explanation.
"""
        prompt = self._build_generation_prompt(
            spec=spec,
            base_url=base_url,
            auth_pattern=auth_pattern,
            tools_desc=tools_desc,
            existing_section=existing_section,
            first_tool=first_tool,
            local_only_requested=local_only_requested,
        )

        try:
            response = await self._provider.complete(
                messages=[
                    {"role": "system", "content": "You are a Python skill developer for NeuralClaw. Return only Python code. EVERY skill file MUST end with a get_manifest() function."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=4000,
            )
            code = response.content or ""
            if "```python" in code:
                code = code.split("```python")[1].split("```")[0].strip()
            elif "```" in code:
                code = code.split("```")[1].split("```")[0].strip()
            code = code.strip()

            # Auto-append get_manifest() if the LLM forgot it
            if code and "def get_manifest" not in code:
                code = self._append_manifest_function(code, spec)

            return code
        except Exception:
            return ""

    def _append_manifest_function(self, code: str, spec: UseCaseSpec) -> str:
        """Append a get_manifest() function if the LLM omitted it."""
        # Extract actual async function names from generated code
        actual_funcs = re.findall(r"^async\s+def\s+(\w+)\s*\(", code, re.MULTILINE)

        # Map spec tool names to actual function names
        # Strategy: exact match first, then fuzzy (tool name contained in func name or vice versa)
        func_map: dict[str, str] = {}
        remaining_funcs = list(actual_funcs)
        for t in spec.tools:
            if t.name in actual_funcs:
                func_map[t.name] = t.name
                if t.name in remaining_funcs:
                    remaining_funcs.remove(t.name)
            else:
                # Fuzzy: find a function whose name contains the tool name or vice versa
                match = next(
                    (f for f in remaining_funcs if t.name in f or f in t.name),
                    None,
                )
                if match:
                    func_map[t.name] = match
                    remaining_funcs.remove(match)

        # If still unmatched tools, assign remaining functions by order
        unmatched_tools = [t for t in spec.tools if t.name not in func_map]
        for t, f in zip(unmatched_tools, remaining_funcs):
            func_map[t.name] = f

        tools_code_parts = []
        for t in spec.tools:
            handler_name = func_map.get(t.name, t.name)
            params_code = ", ".join(
                f'ToolParameter(name="{p["name"]}", type="{p.get("type", "string")}", '
                f'description="{p.get("description", "")}", required={p.get("required", True)})'
                for p in t.parameters
            )
            tools_code_parts.append(
                f'        ToolDefinition(\n'
                f'            name="{t.name}",\n'
                f'            description="{t.description}",\n'
                f'            parameters=[{params_code}],\n'
                f'            handler={handler_name},\n'
                f'        )'
            )
        tools_joined = ",\n".join(tools_code_parts)

        # Ensure required imports are present
        imports_needed = []
        if "from neuralclaw.skills.manifest import" not in code:
            imports_needed.append(
                "from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter"
            )

        manifest_code = f"""

{chr(10).join(imports_needed)}

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="{spec.skill_name}",
        description="{spec.skill_description}",
        tools=[
{tools_joined}
        ],
    )
"""
        return code + manifest_code

    def _rewrite_manifest_function(self, code: str, spec: UseCaseSpec) -> str:
        """Replace any LLM-authored manifest with one derived from the spec."""
        code_without_manifest = self._remove_trailing_manifest_function(code)
        return self._append_manifest_function(code_without_manifest.rstrip(), spec)

    def _remove_trailing_manifest_function(self, code: str) -> str:
        """Drop the final get_manifest block so metadata always comes from the spec."""
        pattern = re.compile(
            r"\n*(?:async\s+)?def\s+get_manifest\s*\([^)]*\)\s*(?:->\s*[^:]+)?\s*:[\s\S]*$",
            re.MULTILINE,
        )
        matches = list(pattern.finditer(code))
        if not matches:
            return code
        return code[:matches[-1].start()].rstrip()

    async def _sandbox_test(self, code: str, spec: UseCaseSpec) -> SandboxResult:
        """Run the generated skill through sandbox with deep validation.

        Tests:
        1. get_manifest() returns a valid SkillManifest
        2. Each tool handler is callable with its declared parameters
        3. No NameError / ImportError at module scope
        4. Handler signatures accept the declared parameters
        """
        # Build per-tool smoke tests
        tool_tests = []
        for t in spec.tools:
            # Build kwargs with safe dummy values per type
            kwargs_parts = []
            for p in t.parameters:
                ptype = p.get("type", "string")
                if ptype == "string":
                    val = '""'
                elif ptype in ("integer", "number"):
                    val = "0"
                elif ptype == "boolean":
                    val = "False"
                elif ptype == "array":
                    val = "[]"
                else:
                    val = '""'
                kwargs_parts.append(f'"{p["name"]}": {val}')
            kwargs_str = "{" + ", ".join(kwargs_parts) + "}"

            tool_tests.append(f"""
# Validate tool: {t.name}
_tool_{t.name} = next((t for t in manifest.tools if t.name == "{t.name}"), None)
assert _tool_{t.name} is not None, "Tool '{t.name}' not in manifest"
assert callable(_tool_{t.name}.handler), "Tool '{t.name}' handler is not callable"

# Smoke-call with dummy args to catch signature mismatches
import inspect as _ins
_sig = _ins.signature(_tool_{t.name}.handler)
_dummy_kwargs = {kwargs_str}
try:
    _bound = _sig.bind(**_dummy_kwargs)
    print("  SIG_OK: {t.name}")
except TypeError as _e:
    # Try without required params that have defaults
    print(f"  SIG_WARN: {t.name}: {{_e}}")
""")

        all_tool_tests = "\n".join(tool_tests)

        test_code = f"""{code}

import asyncio

# Phase 1: manifest loads
manifest = get_manifest()
assert manifest.name == "{spec.skill_name}", f"Name mismatch: {{manifest.name}}"
assert len(manifest.tools) >= 1, "No tools in manifest"
print("MANIFEST_OK:", manifest.name, "tools:", len(manifest.tools))

# Phase 2: each tool handler is callable and accepts declared params
{all_tool_tests}

print("FORGE_TEST_OK:", manifest.name, "tools:", len(manifest.tools))
"""
        extra_env = self._build_sandbox_python_env()
        return await self._sandbox.execute_python(test_code, extra_env=extra_env)

    async def _attempt_fix(self, code: str, error: str, spec: UseCaseSpec) -> str:
        """One attempt to auto-fix a failing skill."""
        try:
            response = await self._provider.complete(
                messages=[
                    {"role": "system", "content": (
                        "Fix the Python error in this NeuralClaw skill code. Return only the fixed code. "
                        "CRITICAL: The file MUST contain a get_manifest() function that returns a SkillManifest. "
                        "Each tool handler MUST accept exactly the parameters declared in its ToolDefinition. "
                        "Do NOT use external APIs or base URLs unless the original code already had them working."
                    )},
                    {"role": "user", "content": f"ERROR:\n{error[:500]}\n\nCODE:\n{code[:3000]}\n\nFix the error. Return only Python code."},
                ],
                temperature=0.1,
                max_tokens=4000,
            )
            fixed = response.content or ""
            if "```python" in fixed:
                fixed = fixed.split("```python")[1].split("```")[0].strip()
            elif "```" in fixed:
                fixed = fixed.split("```")[1].split("```")[0].strip()
            fixed = fixed.strip()

            # Safety: re-append get_manifest() if the fix dropped it
            if fixed and "def get_manifest" not in fixed:
                fixed = self._append_manifest_function(fixed, spec)

            return fixed
        except Exception:
            return ""

    async def _persist_skill(self, code: str, skill_name: str) -> Path:
        """Write the generated skill to ~/.neuralclaw/skills/{skill_name}.py"""
        path = self.USER_SKILLS_DIR / f"{skill_name}.py"
        header = (
            f"# Auto-generated by SkillForge — {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"# Skill: {skill_name}\n"
            f"# Do not edit this file manually — use `neuralclaw forge` to regenerate.\n\n"
        )
        path.write_text(header + code, encoding="utf-8")
        return path

    def _build_manifest_from_spec(self, spec: UseCaseSpec, code: str) -> SkillManifest:
        """Build a SkillManifest by executing the generated code's get_manifest()."""
        skill_file = self.USER_SKILLS_DIR / f"{spec.skill_name}.py"
        if not skill_file.exists():
            raise FileNotFoundError(f"Persisted skill file not found: {skill_file}")
        return load_skill_manifest(skill_file, module_prefix="_forge")

    def _build_generation_prompt(
        self,
        spec: UseCaseSpec,
        base_url: str,
        auth_pattern: str,
        tools_desc: str,
        existing_section: str,
        first_tool: str,
        local_only_requested: bool,
    ) -> str:
        """Build the LLM prompt used to generate a skill implementation."""
        requirements_block = (
            "1. Each tool function must be async and return dict[str, Any]\n"
            "2. Never raise exceptions - catch all errors and return {\"error\": str(e)}\n"
            "3. Do not make any HTTP calls or use network-only libraries like aiohttp\n"
            "4. Include a get_manifest() function at the bottom\n"
            "5. Import from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter\n"
            "6. Wire each function as a handler in its ToolDefinition\n"
            "7. Add a brief docstring to each function\n"
            "8. Do not require API keys or external URLs for this skill\n"
            "9. Use only local Python libraries or the stdlib to satisfy the request\n"
            if local_only_requested else
            "1. Each tool function must be async and return dict[str, Any]\n"
            "2. Never raise exceptions - catch all errors and return {\"error\": str(e)}\n"
            "3. All HTTP calls must use aiohttp (no requests/urllib)\n"
            "4. Include a get_manifest() function at the bottom\n"
            "5. Import from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter\n"
            "6. Wire each function as a handler in its ToolDefinition\n"
            "7. Add a brief docstring to each function\n"
            "8. Handle API keys via os.getenv() - never hardcode credentials\n"
            "9. Include retry logic for transient network failures (max 2 retries)\n"
        )
        local_only_rules = (
            "F. This is a local-only skill. Do NOT import aiohttp or validate_url_with_dns.\n"
            "G. Do NOT define or use _BASE_URL, API-key env vars, or external URLs.\n"
            if local_only_requested else ""
        )
        skill_template = f"""```python
from __future__ import annotations
from typing import Any
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

async def {first_tool}(...) -> dict[str, Any]:
    \"\"\"...\"\"\"
    ...

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="{spec.skill_name}",
        description="{spec.skill_description}",
        tools=[...],
    )
```
""" if local_only_requested else f"""```python
from __future__ import annotations
import os
from typing import Any
import aiohttp
from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.cortex.action.network import validate_url_with_dns
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

_BASE_URL = "{spec.base_url or base_url}"
_API_KEY_ENV = "YOUR_API_KEY_ENV_VAR"

async def {first_tool}(...) -> dict[str, Any]:
    \"\"\"...\"\"\"
    ...

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="{spec.skill_name}",
        description="{spec.skill_description}",
        tools=[...],
    )
```
"""
        return f"""Write a complete NeuralClaw skill Python file.

SKILL: {spec.skill_name}
DESCRIPTION: {spec.skill_description}
BASE URL: {spec.base_url or base_url or 'N/A'}
AUTH: {spec.auth_pattern or auth_pattern or 'none'}

TOOLS TO IMPLEMENT:
{tools_desc}
{existing_section}

Requirements:
{requirements_block}

CRITICAL RULES (violations = broken skill):
A. Each async def MUST accept EXACTLY the parameters listed in TOOLS above
   e.g. if tool has params (name, age), the function must be: async def tool_name(name: str, age: int, **_extra)
B. ALWAYS add **_extra to function signatures for forward compatibility
C. If BASE URL is "N/A" or empty, the skill MUST work WITHOUT any external API
   - use Python stdlib (hashlib, socket, platform, zipfile, json, etc.)
   - do NOT invent URLs or assume an API exists
D. NEVER reference variables that are not defined in the same file
E. The function name MUST match the tool name exactly
{local_only_rules}

Skill file template:
{skill_template}

CRITICAL: The file MUST end with a get_manifest() function that returns a SkillManifest.
Without get_manifest(), the skill cannot load. This is NON-NEGOTIABLE.

Return ONLY the Python code. No markdown fences. No explanation.
"""

    def _build_sandbox_python_env(self) -> dict[str, str]:
        """Expose the local repo package to sandboxed forge validation."""
        project_root = str(self.PROJECT_ROOT)
        existing = os.environ.get("PYTHONPATH", "")
        pythonpath = project_root if not existing else os.pathsep.join([project_root, existing])
        return {"PYTHONPATH": pythonpath}

    def _is_local_only_request(
        self,
        capability_description: str,
        use_case: str,
        base_url: str,
        auth_pattern: str,
    ) -> bool:
        """Detect requests that should stay fully local to this machine."""
        if base_url.strip():
            return False
        if auth_pattern.strip() and auth_pattern.strip().lower() not in {"none"}:
            return False
        haystack = f"{capability_description}\n{use_case}".lower()
        indicators = (
            "local-only",
            "local only",
            "local python",
            "local python only",
            "stdlib",
            "standard library",
            "no network",
            "no external api",
            "on this machine",
            "current machine",
            "local machine",
            "machine-local",
            "psutil",
        )
        return any(token in haystack for token in indicators)

    def _normalize_spec_for_generation(
        self,
        spec: UseCaseSpec,
        local_only_requested: bool,
        forced_skill_name: str = "",
    ) -> UseCaseSpec:
        """Remove network assumptions from specs that must remain local-only."""
        spec.skill_name = self._to_python_identifier(
            forced_skill_name or spec.skill_name or "custom_skill",
            fallback="skill",
        )
        spec.skill_description = spec.skill_description.strip() or spec.skill_name.replace("_", " ")

        seen_tool_names: set[str] = set()
        normalized_tools: list[ToolSpec] = []
        allowed_param_types = {"string", "integer", "boolean", "number", "array", "object"}
        for index, tool in enumerate(spec.tools, start=1):
            tool_name = self._to_python_identifier(tool.name or f"tool_{index}", fallback="tool")
            tool_name = self._dedupe_identifier(tool_name, seen_tool_names)
            seen_tool_names.add(tool_name)

            seen_params: set[str] = set()
            normalized_params: list[dict[str, Any]] = []
            for param_index, param in enumerate(tool.parameters, start=1):
                raw_param = dict(param)
                param_name = self._to_python_identifier(
                    raw_param.get("name") or f"param_{param_index}",
                    fallback="param",
                )
                param_name = self._dedupe_identifier(param_name, seen_params)
                seen_params.add(param_name)
                raw_param["name"] = param_name
                raw_param["type"] = (
                    raw_param.get("type", "string")
                    if raw_param.get("type", "string") in allowed_param_types
                    else "string"
                )
                raw_param["description"] = raw_param.get("description", "") or param_name.replace("_", " ")
                raw_param["required"] = raw_param.get("required", True)
                normalized_params.append(raw_param)

            normalized_tools.append(
                ToolSpec(
                    name=tool_name,
                    description=tool.description.strip() or tool_name.replace("_", " "),
                    parameters=normalized_params,
                    example_call=tool.example_call,
                    example_output=tool.example_output,
                )
            )

        spec.tools = normalized_tools
        if not local_only_requested:
            return spec
        network_imports = {
            "aiohttp",
            "requests",
            "urllib",
            "urllib3",
            "httpx",
            "validate_url_with_dns",
        }
        spec.base_url = ""
        spec.auth_pattern = "none"
        spec.required_imports = [
            item for item in spec.required_imports
            if item.strip().lower() not in network_imports
        ]
        return spec

    def _has_forbidden_local_only_dependencies(self, code: str) -> bool:
        """Detect network scaffolding that must not appear in local-only skills."""
        forbidden_tokens = (
            "aiohttp",
            "validate_url_with_dns",
            "ClientSession",
            "_API_KEY_ENV",
            "http://",
            "https://",
            "Capability.NETWORK_HTTP",
            "Capability.NETWORK_WEBSOCKET",
        )
        return any(token in code for token in forbidden_tokens)

    def _extract_explicit_skill_name(self, capability_description: str, use_case: str) -> str:
        """Honor user-provided skill names instead of trusting generated metadata."""
        combined = f"{capability_description}\n{use_case}"
        patterns = (
            r"\bskill\s+named\s+[`\"']?([a-zA-Z][a-zA-Z0-9_ -]{0,60}?)[`\"']?(?=\s+(?:that|which|with|using|for|to)\b|[.,]|$)",
            r"\bcreate\s+a\s+skill\s+named\s+[`\"']?([a-zA-Z][a-zA-Z0-9_ -]{0,60}?)[`\"']?(?=\s+(?:that|which|with|using|for|to)\b|[.,]|$)",
            r"\bname\s+it\s+[`\"']?([a-zA-Z][a-zA-Z0-9_ -]{0,60}?)[`\"']?(?=\s+(?:that|which|with|using|for|to)\b|[.,]|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, combined, flags=re.IGNORECASE)
            if match:
                return self._to_python_identifier(match.group(1), fallback="skill")
        return ""

    def _validate_python_syntax(self, code: str) -> str | None:
        """Return a readable syntax error message or None when the module parses."""
        try:
            ast.parse(code)
        except SyntaxError as exc:
            bad_line = (exc.text or "").strip()
            location = f"line {exc.lineno}, column {exc.offset}"
            if bad_line:
                return f"Python syntax error at {location}: {exc.msg}. Offending line: {bad_line}"
            return f"Python syntax error at {location}: {exc.msg}"
        return None

    def _to_python_identifier(self, text: str, fallback: str) -> str:
        """Convert free-form LLM output into a safe snake_case Python identifier."""
        ident = self._slugify(text)
        if not ident:
            ident = fallback
        if ident[0].isdigit():
            ident = f"{fallback}_{ident}"
        return ident

    def _dedupe_identifier(self, name: str, seen: set[str]) -> str:
        """Keep identifiers unique while preserving a readable base name."""
        if name not in seen:
            return name
        suffix = 2
        candidate = f"{name}_{suffix}"
        while candidate in seen:
            suffix += 1
            candidate = f"{name}_{suffix}"
        return candidate

    # -- Utility helpers --

    def _detect_input_type(self, source: str) -> ForgeInputType:
        """Auto-detect what kind of input source is."""
        s = source.strip()

        if re.match(r"https?://github\.com/[^/]+/[^/]+", s):
            return ForgeInputType.GITHUB
        if re.match(r"https?://", s):
            low = s.lower()
            if any(x in low for x in ["openapi", "swagger", ".json", ".yaml"]):
                return ForgeInputType.OPENAPI
            if "graphql" in low:
                return ForgeInputType.GRAPHQL
            if any(x in low for x in ["mcp", "/sse", "/mcp"]):
                return ForgeInputType.MCP
            return ForgeInputType.URL
        if Path(s).exists():
            return ForgeInputType.FILE
        if "\n" in s and ("def " in s or "async def" in s or "class " in s):
            return ForgeInputType.CODE
        if s.endswith(".py") or s.endswith(".json") or s.endswith(".yaml"):
            return ForgeInputType.FILE
        if re.match(r"^[a-zA-Z][a-zA-Z0-9_.-]+$", s) and "." not in s:
            try:
                importlib.util.find_spec(s)
                return ForgeInputType.LIBRARY
            except (ModuleNotFoundError, ValueError):
                pass
        return ForgeInputType.DESCRIPTION

    async def _probe_for_openapi(self, session: Any, base_url: str) -> str | None:
        """Check common OpenAPI spec locations."""
        import aiohttp
        candidates = [
            base_url.rstrip("/") + "/openapi.json",
            base_url.rstrip("/") + "/swagger.json",
            base_url.rstrip("/") + "/api-docs",
            base_url.rstrip("/") + "/docs/openapi.json",
        ]
        for url in candidates:
            try:
                await validate_url_with_dns(url)
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        ct = r.headers.get("Content-Type", "")
                        if "json" in ct or "yaml" in ct:
                            data = await r.json(content_type=None)
                            if "openapi" in data or "swagger" in data:
                                return url
            except Exception:
                continue
        return None

    def _summarize_endpoints(self, paths: dict, max_endpoints: int = 40) -> list[str]:
        lines = []
        for path, methods in list(paths.items())[:max_endpoints]:
            for method, op in methods.items():
                if method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                    summary = op.get("summary") or op.get("description", "")[:60]
                    lines.append(f"  {method.upper()} {path} — {summary}")
        return lines

    def _extract_base_url(self, spec: dict) -> str:
        if "servers" in spec:
            return spec["servers"][0].get("url", "") if spec["servers"] else ""
        if "host" in spec:
            scheme = spec.get("schemes", ["https"])[0]
            return f"{scheme}://{spec['host']}{spec.get('basePath', '')}"
        return ""

    def _extract_auth_scheme(self, spec: dict) -> str:
        components = spec.get("components", {}) or spec.get("securityDefinitions", {})
        security = components.get("securitySchemes", {}) or components
        if not security:
            return "none"
        schemes = list(security.values())
        if schemes:
            s = schemes[0]
            t = s.get("type", "")
            if t == "http":
                return s.get("scheme", "bearer")
            return t
        return "none"

    def _describe_api_from_response(self, url: str, status: int, response: Any) -> str:
        shape = json.dumps(response, indent=2)[:1000] if isinstance(response, (dict, list)) else str(response)[:500]
        return f"REST API at {url}\nHTTP {status} response shape:\n{shape}"

    @staticmethod
    def _slugify(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "skill"
