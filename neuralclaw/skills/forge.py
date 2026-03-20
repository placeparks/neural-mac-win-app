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
import hashlib
import importlib
import importlib.util
import inspect
import json
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
from neuralclaw.skills.manifest import (
    Capability,
    SkillManifest,
    ToolDefinition,
    ToolParameter,
)
from neuralclaw.skills.marketplace import StaticAnalyzer


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

    USER_SKILLS_DIR = Path.home() / ".neuralclaw" / "skills"

    def __init__(
        self,
        provider: Any,
        sandbox: Sandbox,
        registry: Any,
        bus: NeuralBus | None = None,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self._provider = provider
        self._sandbox = sandbox
        self._registry = registry
        self._bus = bus
        self._model = model
        self._sessions: dict[str, ForgeSession] = {}
        self.USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

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
        spec = await self._run_use_case_interview(
            capability_description=capability_description,
            use_case=use_case,
            base_url=base_url,
            auth_pattern=auth_pattern,
            skill_name_hint=skill_name_hint,
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
        )

        if not code:
            return ForgeResult(
                success=False, skill_name=spec.skill_name,
                input_type=ForgeInputType.UNKNOWN,
                error="Code generation produced empty output",
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
                test_result = await self._sandbox_test(code, spec)

        # Final safety: ensure get_manifest() is always present before saving
        if "def get_manifest" not in code:
            code = self._append_manifest_function(code, spec)

        file_path = await self._persist_skill(code, spec.skill_name)
        manifest = self._build_manifest_from_spec(spec, code)
        self._registry.hot_register(manifest)

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

    async def _run_use_case_interview(
        self,
        capability_description: str,
        use_case: str,
        base_url: str,
        auth_pattern: str,
        skill_name_hint: str,
    ) -> UseCaseSpec:
        """The use-case interview is the heart of SkillForge."""
        use_case_section = (
            f"\n\nUSE CASE: {use_case}" if use_case else
            "\n\nUSE CASE: General purpose assistant"
        )

        prompt = f"""You are designing NeuralClaw skill tools for an AI agent.

CAPABILITY AVAILABLE:
{capability_description[:3000]}
{use_case_section}

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
  "required_imports": ["aiohttp"],
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

        except Exception as e:
            return UseCaseSpec(
                skill_name=skill_name_hint or "custom_skill",
                skill_description="Custom skill",
                tools=[ToolSpec(
                    name=skill_name_hint or "execute",
                    description=f"Execute {use_case or 'custom operation'}",
                    parameters=[{"name": "input", "type": "string", "description": "Input", "required": True}],
                )],
                required_imports=["aiohttp"],
                clarifications=[f"Could not auto-design tools: {e}. Describe what you want this skill to do."],
            )

    async def _generate_skill_code(
        self,
        spec: UseCaseSpec,
        base_url: str,
        auth_pattern: str,
        extra_imports: list[str],
        existing_code: str,
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

    async def _sandbox_test(self, code: str, spec: UseCaseSpec) -> SandboxResult:
        """Run the generated skill through sandbox."""
        test_code = f"""{code}

import asyncio

manifest = get_manifest()
assert manifest.name == "{spec.skill_name}", f"Name mismatch: {{manifest.name}}"
assert len(manifest.tools) >= 1, "No tools in manifest"
print("FORGE_TEST_OK:", manifest.name, "tools:", len(manifest.tools))
"""
        return await self._sandbox.execute_python(test_code)

    async def _attempt_fix(self, code: str, error: str, spec: UseCaseSpec) -> str:
        """One attempt to auto-fix a failing skill."""
        try:
            response = await self._provider.complete(
                messages=[
                    {"role": "system", "content": "Fix the Python error in this NeuralClaw skill code. Return only the fixed code."},
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
            return fixed.strip()
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
        # Try loading from the persisted skill file first (more reliable)
        skill_file = self.USER_SKILLS_DIR / f"{spec.skill_name}.py"
        load_sources: list[tuple[str, str]] = []
        if skill_file.exists():
            load_sources.append((f"_forge_{spec.skill_name}", str(skill_file)))
        load_sources.append(("_forge_temp_inline", ""))  # fallback to temp file

        for mod_name, file_path in load_sources:
            try:
                if not file_path:
                    # Write code to temp file
                    with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
                        f.write(code)
                        file_path = f.name

                spec_mod = importlib.util.spec_from_file_location(mod_name, file_path)
                if spec_mod is None or spec_mod.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec_mod)
                spec_mod.loader.exec_module(module)
                # Keep module alive so handlers don't get garbage collected
                if not hasattr(self, "_loaded_modules"):
                    self._loaded_modules: dict[str, Any] = {}
                self._loaded_modules[spec.skill_name] = module
                if hasattr(module, "get_manifest"):
                    return module.get_manifest()
            except Exception:
                continue

        # Last resort: create tools with wrapper handlers that load the skill file on demand
        def _make_lazy_handler(skill_name: str, tool_name: str):
            async def _lazy_call(**kwargs):
                path = self.USER_SKILLS_DIR / f"{skill_name}.py"
                if not path.exists():
                    return {"error": f"Skill file not found: {path}"}
                spec_m = importlib.util.spec_from_file_location(f"_lazy_{skill_name}", path)
                if spec_m is None or spec_m.loader is None:
                    return {"error": f"Cannot load skill module: {path}"}
                mod = importlib.util.module_from_spec(spec_m)
                spec_m.loader.exec_module(mod)
                self._loaded_modules[skill_name] = mod
                manifest = mod.get_manifest() if hasattr(mod, "get_manifest") else None
                if not manifest:
                    return {"error": "Skill has no get_manifest()"}
                handler = next((t.handler for t in manifest.tools if t.name == tool_name), None)
                if not handler:
                    return {"error": f"Tool '{tool_name}' not found in loaded manifest"}
                return await handler(**kwargs)
            return _lazy_call

        tools = [
            ToolDefinition(
                name=t.name,
                description=t.description,
                parameters=[
                    ToolParameter(
                        name=p["name"],
                        type=p.get("type", "string"),
                        description=p.get("description", ""),
                        required=p.get("required", True),
                    )
                    for p in t.parameters
                ],
                handler=_make_lazy_handler(spec.skill_name, t.name),
            )
            for t in spec.tools
        ]
        return SkillManifest(
            name=spec.skill_name,
            description=spec.skill_description,
            capabilities=[Capability.NETWORK_HTTP] if spec.base_url else [],
            tools=tools,
        )

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
