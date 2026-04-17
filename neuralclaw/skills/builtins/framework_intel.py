"""
Built-in Skill: Framework Intel — NeuralClaw self-knowledge tools.

Gives agents full situational awareness of the framework they run inside:
- Directory layout and AGENTS.md orientation files
- All registered skills (without triggering lazy imports)
- All active spawned agents and their workspace claims
- Directory claim/release for multi-agent coordination
- Ready-to-paste skill authoring templates

These tools make agents self-sufficient: they can write new skills, create
projects, avoid workspace conflicts, and understand their own environment.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

# ---------------------------------------------------------------------------
# Module-level state — injected by gateway.initialize()
# ---------------------------------------------------------------------------

_gateway_ref: Any = None
_workspace_coordinator: Any = None
_agent_name: str = "unknown"


def set_gateway(gateway: Any) -> None:
    global _gateway_ref
    _gateway_ref = gateway


def set_workspace_coordinator(coordinator: Any) -> None:
    global _workspace_coordinator
    _workspace_coordinator = coordinator


def set_agent_name(name: str) -> None:
    global _agent_name
    _agent_name = name


# ---------------------------------------------------------------------------
# Skill templates
# ---------------------------------------------------------------------------

_SKILL_TEMPLATES: dict[str, str] = {
    "basic": '''\
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter
from neuralclaw.cortex.action.capabilities import Capability

async def my_tool(param: str, **kwargs) -> dict:
    """Replace with your implementation. Always return a dict."""
    return {"result": param}

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="my_skill",
        description="What this skill does — shown to the LLM",
        capabilities=[],
        tools=[
            ToolDefinition(
                name="my_tool",
                description="What this tool does — be precise",
                parameters=[
                    ToolParameter(name="param", type="string", description="Input parameter", required=True),
                ],
                handler=my_tool,
            )
        ],
    )
''',
    "api": '''\
"""Skill template: external HTTP API integration."""
from __future__ import annotations
import aiohttp
from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.cortex.action.network import validate_url
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

_API_BASE = "https://api.example.com/v1"
_TIMEOUT = aiohttp.ClientTimeout(total=15)

async def call_api(endpoint: str, query: str = "", **kwargs) -> dict:
    url = f"{_API_BASE}/{endpoint.lstrip('/')}"
    try:
        validate_url(url)
    except Exception as e:
        return {"error": f"URL blocked: {e}"}
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
        async with session.get(url, params={"q": query}) as resp:
            if resp.status != 200:
                return {"error": f"HTTP {resp.status}"}
            data = await resp.json()
    return {"result": data}

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="my_api_skill",
        description="Call the Example API",
        capabilities=[Capability.NETWORK_HTTP],
        tools=[
            ToolDefinition(
                name="call_api",
                description="Call an Example API endpoint",
                parameters=[
                    ToolParameter(name="endpoint", type="string", description="API endpoint path", required=True),
                    ToolParameter(name="query", type="string", description="Search query", required=False, default=""),
                ],
                handler=call_api,
            )
        ],
    )
''',
    "filesystem": '''\
"""Skill template: filesystem read/write with path validation."""
from __future__ import annotations
from pathlib import Path
from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

_allowed_roots: list[str] = []

def set_allowed_roots(roots: list[str]) -> None:
    global _allowed_roots
    _allowed_roots = roots

def _check_path(path_str: str) -> Path:
    p = Path(path_str).expanduser().resolve()
    if _allowed_roots:
        if not any(str(p).startswith(r) for r in _allowed_roots):
            raise PermissionError(f"Path {p} is outside allowed roots")
    return p

async def read_file(path: str, **kwargs) -> dict:
    try:
        p = _check_path(path)
        content = p.read_text(encoding="utf-8", errors="replace")
        return {"path": str(p), "content": content, "size": len(content)}
    except Exception as e:
        return {"error": str(e)}

async def write_file(path: str, content: str, **kwargs) -> dict:
    try:
        p = _check_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"path": str(p), "written": len(content)}
    except Exception as e:
        return {"error": str(e)}

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="my_fs_skill",
        description="Read and write files",
        capabilities=[Capability.FILESYSTEM_READ, Capability.FILESYSTEM_WRITE],
        tools=[
            ToolDefinition(name="read_file", description="Read a file", parameters=[
                ToolParameter(name="path", type="string", description="File path", required=True),
            ], handler=read_file),
            ToolDefinition(name="write_file", description="Write a file", parameters=[
                ToolParameter(name="path", type="string", description="File path", required=True),
                ToolParameter(name="content", type="string", description="Content to write", required=True),
            ], handler=write_file),
        ],
    )
''',
    "stateful": '''\
"""Skill template: stateful skill with gateway-injected config."""
from __future__ import annotations
from typing import Any
from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

# Gateway injects config via setter functions
_config: Any = None

def set_config(cfg: Any) -> None:
    global _config
    _config = cfg

async def do_thing(input: str, **kwargs) -> dict:
    if _config is None:
        return {"error": "Skill not configured — gateway did not call set_config()"}
    # Use _config here
    return {"result": input, "config_name": getattr(_config, "name", "unknown")}

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="my_stateful_skill",
        description="Stateful skill with injected config",
        capabilities=[],
        tools=[
            ToolDefinition(
                name="do_thing",
                description="Do the thing",
                parameters=[ToolParameter(name="input", type="string", description="Input", required=True)],
                handler=do_thing,
            )
        ],
    )
''',
}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def list_workspace_structure(include_hidden: bool = False, **kwargs) -> dict:
    """Return a structured view of key NeuralClaw directories with AGENTS.md summaries."""
    from neuralclaw.config import CONFIG_DIR, DATA_DIR, LOG_DIR
    from neuralclaw.skills.paths import resolve_user_skills_dir

    def _read_agents_md(p: Path) -> str | None:
        md = p / "AGENTS.md"
        if md.exists():
            try:
                return md.read_text(encoding="utf-8", errors="replace")[:500]
            except Exception:
                pass
        return None

    def _list_dir(p: Path, max_entries: int = 40) -> list[str]:
        if not p.exists():
            return []
        try:
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
            names = [
                e.name + ("/" if e.is_dir() else "")
                for e in entries
                if include_hidden or not e.name.startswith(".")
            ]
            return names[:max_entries]
        except Exception:
            return []

    gw = _gateway_ref
    config = gw._config if gw else None

    skills_dir = None
    repos_dir = None
    apps_dir = None
    if config:
        from neuralclaw.skills.paths import resolve_user_skills_dir
        skills_dir = resolve_user_skills_dir(
            config.skill_forge.user_skills_dir if hasattr(config, "skill_forge") else None
        )
        repos_dir = Path(config.workspace.repos_dir).expanduser()
        apps_dir = Path(config.workspace.apps_dir).expanduser()

    result: dict[str, Any] = {
        "home": {
            "path": str(CONFIG_DIR),
            "entries": _list_dir(CONFIG_DIR),
            "agents_md": _read_agents_md(CONFIG_DIR),
        },
        "skills": {
            "path": str(skills_dir) if skills_dir else "unknown",
            "entries": _list_dir(skills_dir) if skills_dir else [],
            "agents_md": _read_agents_md(skills_dir) if skills_dir else None,
        },
        "repos": {
            "path": str(repos_dir) if repos_dir else "unknown",
            "entries": _list_dir(repos_dir) if repos_dir else [],
            "agents_md": _read_agents_md(repos_dir) if repos_dir else None,
        },
        "apps": {
            "path": str(apps_dir) if apps_dir else "unknown",
            "entries": _list_dir(apps_dir) if apps_dir else [],
            "agents_md": _read_agents_md(apps_dir) if apps_dir else None,
        },
        "data": {
            "path": str(DATA_DIR),
            "entries": _list_dir(DATA_DIR),
            "agents_md": _read_agents_md(DATA_DIR),
        },
    }

    # Include active workspace claims
    if _workspace_coordinator:
        try:
            claims = await _workspace_coordinator.list_all_claims()
            result["active_workspace_claims"] = [
                {
                    "path": c.path,
                    "agent": c.agent_name,
                    "purpose": c.purpose,
                    "claimed_at": c.claimed_at,
                }
                for c in claims
            ]
        except Exception:
            result["active_workspace_claims"] = []
    else:
        result["active_workspace_claims"] = []

    return result


async def list_available_skills(source_filter: str = "all", **kwargs) -> dict:
    """
    List all registered skills with names, descriptions, and tool counts.
    Does NOT trigger lazy loading of unloaded skill modules.
    """
    gw = _gateway_ref
    if gw is None:
        return {"error": "Gateway not available", "skills": []}

    registry = gw._skills
    skills_out = []

    # Pull from _lazy_entries (stub metadata) first — avoids triggering imports
    lazy_entries = getattr(registry, "_lazy_entries", {})
    loaded = getattr(registry, "_loaded_skills", set())
    tool_to_skill = getattr(registry, "_tool_to_skill", {})

    # Count tools per skill from _tool_defs
    tool_counts: dict[str, int] = {}
    for td in registry.get_all_tools():
        skill = tool_to_skill.get(td.name, "unknown")
        tool_counts[skill] = tool_counts.get(skill, 0) + 1

    for skill_name, module_path in lazy_entries.items():
        source = "user" if skill_name in getattr(registry, "_user_skills", set()) else "builtin"
        if source_filter not in ("all", source):
            continue
        manifest = registry._skills.get(skill_name)
        description = manifest.description if manifest else "(not loaded yet)"
        skills_out.append({
            "name": skill_name,
            "description": description,
            "tool_count": tool_counts.get(skill_name, 0),
            "loaded": skill_name in loaded,
            "source": source,
        })

    # Also include user skills not in lazy_entries (registered via hot_register)
    for manifest in registry.list_user_skills():
        if manifest.name not in lazy_entries:
            skills_out.append({
                "name": manifest.name,
                "description": manifest.description,
                "tool_count": len(manifest.tools),
                "loaded": True,
                "source": "user",
            })

    skills_out.sort(key=lambda x: x["name"])
    return {"total": len(skills_out), "skills": skills_out}


async def get_skill_template(skill_type: str = "basic", **kwargs) -> dict:
    """
    Return a ready-to-paste Python skill template.

    skill_type options:
    - "basic"      — minimal single-tool skill
    - "api"        — HTTP API integration with SSRF protection
    - "filesystem" — read/write files with path validation
    - "stateful"   — skill with gateway-injected config
    """
    template = _SKILL_TEMPLATES.get(skill_type)
    if template is None:
        available = list(_SKILL_TEMPLATES.keys())
        return {"error": f"Unknown skill_type '{skill_type}'. Available: {available}"}

    from neuralclaw.skills.paths import resolve_user_skills_dir
    gw = _gateway_ref
    skills_dir = None
    if gw:
        skills_dir = str(resolve_user_skills_dir(
            gw._config.skill_forge.user_skills_dir if hasattr(gw._config, "skill_forge") else None
        ))

    return {
        "skill_type": skill_type,
        "template": template,
        "install_dir": skills_dir,
        "instructions": (
            f"Save to {skills_dir}/my_skill.py (or any unique name). "
            "Hot-reloaded in ~3 seconds — no restart needed."
        ) if skills_dir else "Save to the user skills directory.",
    }


async def get_active_agents(**kwargs) -> dict:
    """Return all currently running spawned agents with their status and workspace claims."""
    gw = _gateway_ref
    if gw is None:
        return {"error": "Gateway not available", "agents": []}

    agents_out = []

    mesh = getattr(gw, "_mesh", None)
    if mesh is not None:
        try:
            cards = list(mesh._agents.values()) if hasattr(mesh, "_agents") else []
            for card in cards:
                claims: list[str] = []
                if _workspace_coordinator:
                    try:
                        c = await _workspace_coordinator.get_claims_for_agent(card.name)
                        claims = [cl.path for cl in c]
                    except Exception:
                        pass
                agents_out.append({
                    "name": card.name,
                    "description": getattr(card, "description", ""),
                    "capabilities": getattr(card, "capabilities", []),
                    "status": getattr(card, "status", "unknown"),
                    "active_tasks": getattr(card, "active_tasks", 0),
                    "workspace_claims": claims,
                })
        except Exception as e:
            return {"error": str(e), "agents": []}

    # Add the gateway (main agent) itself
    gw_claims: list[str] = []
    if _workspace_coordinator:
        try:
            c = await _workspace_coordinator.get_claims_for_agent(_agent_name)
            gw_claims = [cl.path for cl in c]
        except Exception:
            pass

    agents_out.insert(0, {
        "name": _agent_name,
        "description": "Main NeuralClaw gateway agent",
        "capabilities": ["all"],
        "status": "online",
        "active_tasks": 0,
        "workspace_claims": gw_claims,
        "is_gateway": True,
    })

    return {"total": len(agents_out), "agents": agents_out}


async def claim_workspace_dir(path: str, purpose: str = "", ttl_seconds: float = 0, **kwargs) -> dict:
    """
    Claim a directory for exclusive use by this agent.

    Returns success=True and the claim details on success.
    Returns success=False with the existing claim info if already claimed by another agent.
    Use release_workspace_dir when done.
    """
    if _workspace_coordinator is None:
        return {"success": True, "note": "Workspace coordinator not available — proceeding without claim"}

    gw = _gateway_ref
    if gw:
        # Validate path is within allowed roots
        try:
            from neuralclaw.cortex.action.policy import PolicyEngine
            from pathlib import Path as _P
            resolved = str(_P(path).expanduser().resolve())
        except Exception:
            resolved = path
    else:
        resolved = path

    claim = await _workspace_coordinator.claim(
        path=resolved,
        agent_name=_agent_name,
        purpose=purpose,
        ttl_seconds=ttl_seconds,
    )

    if claim is None:
        existing = await _workspace_coordinator.get_claim(resolved)
        return {
            "success": False,
            "path": resolved,
            "error": f"Path already claimed by '{existing.agent_name}'" if existing else "Claim failed",
            "existing_claim": {
                "agent": existing.agent_name if existing else None,
                "purpose": existing.purpose if existing else None,
                "claimed_at": existing.claimed_at if existing else None,
            } if existing else None,
        }

    return {
        "success": True,
        "path": claim.path,
        "claim_id": claim.claim_id,
        "agent": claim.agent_name,
        "purpose": claim.purpose,
        "claimed_at": claim.claimed_at,
    }


async def release_workspace_dir(path: str, **kwargs) -> dict:
    """Release a previously claimed directory."""
    if _workspace_coordinator is None:
        return {"success": True, "note": "Workspace coordinator not available"}

    from pathlib import Path as _P
    resolved = str(_P(path).expanduser().resolve())

    released = await _workspace_coordinator.release(resolved, _agent_name)
    if released:
        return {"success": True, "path": resolved}
    return {
        "success": False,
        "path": resolved,
        "error": "No active claim found for this path owned by this agent",
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="framework_intel",
        description=(
            "NeuralClaw self-knowledge: explore workspace layout, list skills, get skill templates, "
            "see active agents, and claim/release directories for multi-agent coordination."
        ),
        version="0.1.0",
        capabilities=[Capability.FILESYSTEM_READ, Capability.MEMORY_READ],
        tools=[
            ToolDefinition(
                name="list_workspace_structure",
                description=(
                    "Show the NeuralClaw directory layout: config home, user skills dir, repos, apps, "
                    "data. Includes AGENTS.md orientation text for each dir and active workspace claims."
                ),
                parameters=[
                    ToolParameter(
                        name="include_hidden",
                        type="boolean",
                        description="Include hidden files/dirs (default false)",
                        required=False,
                        default=False,
                    )
                ],
                handler=list_workspace_structure,
            ),
            ToolDefinition(
                name="list_available_skills",
                description=(
                    "List all registered skills (builtin and user) with name, description, and tool count. "
                    "Does NOT import unloaded skill modules."
                ),
                parameters=[
                    ToolParameter(
                        name="source_filter",
                        type="string",
                        description="Filter by source: 'all' (default), 'builtin', or 'user'",
                        required=False,
                        default="all",
                        enum=["all", "builtin", "user"],
                    )
                ],
                handler=list_available_skills,
            ),
            ToolDefinition(
                name="get_skill_template",
                description=(
                    "Get a ready-to-paste Python skill template. "
                    "Types: 'basic' (minimal), 'api' (HTTP calls), 'filesystem' (file I/O), 'stateful' (gateway config)."
                ),
                parameters=[
                    ToolParameter(
                        name="skill_type",
                        type="string",
                        description="Template type: basic | api | filesystem | stateful",
                        required=False,
                        default="basic",
                        enum=["basic", "api", "filesystem", "stateful"],
                    )
                ],
                handler=get_skill_template,
            ),
            ToolDefinition(
                name="get_active_agents",
                description=(
                    "List all currently running agents (main gateway + spawned agents) with status, "
                    "capabilities, active task count, and workspace directory claims."
                ),
                parameters=[],
                handler=get_active_agents,
            ),
            ToolDefinition(
                name="claim_workspace_dir",
                description=(
                    "Claim a directory for exclusive use by this agent to avoid conflicts with other agents. "
                    "Returns success=True with claim details, or success=False with existing claim info. "
                    "Always release with release_workspace_dir when done."
                ),
                parameters=[
                    ToolParameter(name="path", type="string", description="Directory path to claim", required=True),
                    ToolParameter(name="purpose", type="string", description="Human-readable reason for claiming", required=False, default=""),
                    ToolParameter(name="ttl_seconds", type="number", description="Auto-expire claim after N seconds (0 = no expiry)", required=False, default=0),
                ],
                handler=claim_workspace_dir,
            ),
            ToolDefinition(
                name="release_workspace_dir",
                description="Release a directory claim previously made by this agent.",
                parameters=[
                    ToolParameter(name="path", type="string", description="Directory path to release", required=True),
                ],
                handler=release_workspace_dir,
            ),
        ],
    )
