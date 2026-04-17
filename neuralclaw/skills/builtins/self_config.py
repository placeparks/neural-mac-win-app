"""
Built-in Skill: Self Config — Agent self-modification tools.

Lets the agent inspect and change its own runtime configuration in response
to user instructions ("disable workflows", "switch your fast model to
qwen2.5:3b", "what features are on?"). All tools delegate to existing
gateway dashboard methods so config IO, hot-reload, and persistence stay in
one place.

Safety: this skill deliberately does NOT expose tools for editing security
thresholds, the broader allowlist policy, or provider secrets. The agent can
toggle individual skills and feature flags and swap model role bindings; it
cannot disable threat blocking or exfiltrate keys.
"""

from __future__ import annotations

from typing import Any

from neuralclaw.skills.builtins._registry import BUILTIN_SKILL_METADATA
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter


# Module-level gateway reference (set by gateway on init).
_gateway_ref: Any = None


def set_gateway(gateway: Any) -> None:
    """Inject the live Gateway instance so tools can call dashboard methods."""
    global _gateway_ref
    _gateway_ref = gateway


def _require_gateway() -> tuple[Any, dict[str, Any] | None]:
    if _gateway_ref is None:
        return None, {"error": "self_config skill is not bound to a gateway"}
    return _gateway_ref, None


# ---------------------------------------------------------------------------
# Feature toggles
# ---------------------------------------------------------------------------

async def list_features(**_: Any) -> dict[str, Any]:
    """Return all feature toggles with their current value and live-effect flag."""
    gw, err = _require_gateway()
    if err:
        return err
    try:
        features = gw._dashboard_get_features()
        return {"features": features, "count": len(features)}
    except Exception as e:
        return {"error": str(e)}


async def set_feature(name: str, enabled: bool, **_: Any) -> dict[str, Any]:
    """Enable or disable a feature toggle by name."""
    gw, err = _require_gateway()
    if err:
        return err
    try:
        result = await gw._dashboard_set_feature(name, bool(enabled))
        return result
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Skill enable / disable
# ---------------------------------------------------------------------------

async def list_skills(**_: Any) -> dict[str, Any]:
    """List every loaded skill, its tools, and whether each tool is allowed."""
    gw, err = _require_gateway()
    if err:
        return err
    try:
        allowed = set(gw._config.policy.allowed_tools or [])
        manifest_by_name = {manifest.name: manifest for manifest in gw._skills.list_skills()}
        skills_out: list[dict[str, Any]] = []
        for meta in BUILTIN_SKILL_METADATA:
            tool_entries = [
                {
                    "name": tool_meta["name"],
                    "description": tool_meta["description"],
                    "enabled": tool_meta["name"] in allowed,
                }
                for tool_meta in meta.get("tools", [])
            ]
            live_manifest = manifest_by_name.get(meta["name"])
            skills_out.append({
                "name": meta["name"],
                "description": live_manifest.description if live_manifest else meta.get("description", ""),
                "source": "builtin",
                "enabled": any(tool["enabled"] for tool in tool_entries),
                "tools": tool_entries,
            })
        for manifest in gw._skills.list_user_skills():
            tool_entries = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "enabled": tool.name in allowed,
                }
                for tool in manifest.tools
            ]
            skills_out.append({
                "name": manifest.name,
                "description": manifest.description,
                "source": "user",
                "enabled": any(tool["enabled"] for tool in tool_entries),
                "tools": tool_entries,
            })
        return {"skills": skills_out, "count": len(skills_out)}
    except Exception as e:
        return {"error": str(e)}


async def set_skill_enabled(tool_name: str, enabled: bool, **_: Any) -> dict[str, Any]:
    """Add or remove a tool or whole skill from the policy allowlist and hot-reload."""
    gw, err = _require_gateway()
    if err:
        return err
    try:
        allowed = list(gw._config.policy.allowed_tools or [])
        requested = (tool_name or "").strip()
        if not requested:
            return {"error": "tool_name is required"}

        target_tools = [requested]
        matched_skill = next((meta for meta in BUILTIN_SKILL_METADATA if meta["name"] == requested), None)
        if matched_skill:
            target_tools = [tool_meta["name"] for tool_meta in matched_skill.get("tools", [])]
        else:
            user_skill = gw._skills.get_skill(requested)
            if user_skill:
                target_tools = [tool.name for tool in user_skill.tools]

        changed = False
        for target_tool in target_tools:
            if enabled and target_tool not in allowed:
                allowed.append(target_tool)
                changed = True
            elif not enabled and target_tool in allowed:
                allowed.remove(target_tool)
                changed = True

        if not changed:
            return {"ok": True, "tool": requested, "enabled": enabled, "changed": False, "tools": target_tools}

        # Persist via dashboard config so update flows through hot-reload.
        result = await gw._dashboard_update_config({"policy": {"allowed_tools": allowed}})
        result["tool"] = requested
        result["enabled"] = enabled
        result["changed"] = True
        result["tools"] = target_tools
        return result
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Config snapshot
# ---------------------------------------------------------------------------

async def get_config(**_: Any) -> dict[str, Any]:
    """Return a redacted snapshot of the current runtime config."""
    gw, err = _require_gateway()
    if err:
        return err
    try:
        return {"config": gw._get_dashboard_config()}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Model roles
# ---------------------------------------------------------------------------

async def list_available_models(**_: Any) -> dict[str, Any]:
    """List all models available at the configured local Ollama endpoint."""
    gw, err = _require_gateway()
    if err:
        return err
    try:
        router = getattr(gw, "_role_router", None)
        if router is None:
            return {"error": "Role router is not configured"}
        models = await router.list_available_models()
        return {
            "base_url": router.base_url,
            "current": router.model_map,
            "available": [m.get("id", "") for m in models if m.get("id")],
        }
    except Exception as e:
        return {"error": str(e)}


async def set_model_role(role: str, model: str, **_: Any) -> dict[str, Any]:
    """Bind a model to a role (primary | fast | micro | embed) and hot-reload."""
    gw, err = _require_gateway()
    if err:
        return err
    role = (role or "").strip().lower()
    if role not in {"primary", "fast", "micro", "embed"}:
        return {"error": f"Unknown role '{role}'. Use one of: primary, fast, micro, embed."}
    if not (model or "").strip():
        return {"error": "model name is required"}
    try:
        result = await gw._dashboard_update_config({"model_roles": {role: model.strip()}})
        result["role"] = role
        result["model"] = model.strip()
        return result
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="self_config",
        description=(
            "Inspect and change the agent's own runtime configuration: "
            "list/toggle features, list/enable/disable skills, swap model roles, "
            "and read the current config snapshot."
        ),
        capabilities=[],  # Operates on the gateway only — no external capabilities required.
        tools=[
            ToolDefinition(
                name="list_features",
                description="List all feature toggles and their current state.",
                parameters=[],
                handler=list_features,
            ),
            ToolDefinition(
                name="set_feature",
                description="Enable or disable a feature by name (e.g. 'workflows', 'reflective_reasoning').",
                parameters=[
                    ToolParameter(name="name", type="string", description="Feature name"),
                    ToolParameter(name="enabled", type="boolean", description="True to enable, False to disable"),
                ],
                handler=set_feature,
            ),
            ToolDefinition(
                name="list_skills",
                description="List every loaded skill with its tools and whether each tool is currently allowed.",
                parameters=[],
                handler=list_skills,
            ),
            ToolDefinition(
                name="set_skill_enabled",
                description="Allow or disallow a specific tool by name in the policy allowlist.",
                parameters=[
                    ToolParameter(name="tool_name", type="string", description="The tool name to toggle"),
                    ToolParameter(name="enabled", type="boolean", description="True to allow, False to disallow"),
                ],
                handler=set_skill_enabled,
            ),
            ToolDefinition(
                name="get_config",
                description="Return a redacted snapshot of the current runtime config.",
                parameters=[],
                handler=get_config,
            ),
            ToolDefinition(
                name="list_available_models",
                description="List all models available at the configured Ollama endpoint plus the current role->model bindings.",
                parameters=[],
                handler=list_available_models,
            ),
            ToolDefinition(
                name="set_model_role",
                description="Bind a model name to a role. Roles: primary (deep reasoning), fast (tool loops), micro (classification), embed (embeddings).",
                parameters=[
                    ToolParameter(
                        name="role",
                        type="string",
                        description="Role to bind",
                        enum=["primary", "fast", "micro", "embed"],
                    ),
                    ToolParameter(name="model", type="string", description="Model name as served by Ollama (e.g. 'qwen2.5:3b')"),
                ],
                handler=set_model_role,
            ),
        ],
    )
