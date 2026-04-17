"""
Built-in Skill: Agent Orchestration.

Lets agents create persistent worker definitions, spawn and stop them, inspect
the live roster, and delegate work using the same orchestration modes exposed
in the desktop app.
"""

from __future__ import annotations

from typing import Any

from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter


_gateway_ref: Any = None


def set_gateway(gateway: Any) -> None:
    global _gateway_ref
    _gateway_ref = gateway


def _require_gateway() -> tuple[Any, dict[str, Any] | None]:
    if _gateway_ref is None:
        return None, {"error": "agent_orchestration skill is not bound to a gateway"}
    return _gateway_ref, None


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


async def _list_definitions() -> list[dict[str, Any]]:
    gw, err = _require_gateway()
    if err:
        return []
    return await gw._dashboard_list_definitions()


async def _running_agent_names() -> set[str]:
    gw, err = _require_gateway()
    if err:
        return set()
    return {
        str(agent.get("name", "")).strip()
        for agent in gw._dashboard_get_running_agents()
        if str(agent.get("name", "")).strip()
    }


async def _resolve_agent_definition(
    *,
    agent_id: str = "",
    name: str = "",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    definitions = await _list_definitions()
    requested_id = str(agent_id or "").strip()
    requested_name = str(name or "").strip()
    if requested_id:
        for definition in definitions:
            if str(definition.get("agent_id", "")).strip() == requested_id:
                return definition, None
        return None, {"error": f"Agent definition '{requested_id}' not found"}
    if requested_name:
        for definition in definitions:
            if str(definition.get("name", "")).strip() == requested_name:
                return definition, None
        return None, {"error": f"Agent definition '{requested_name}' not found"}
    return None, {"error": "agent_id or name is required"}


async def _ensure_agents_running(agent_names: list[str]) -> dict[str, Any]:
    gw, err = _require_gateway()
    if err:
        return err

    requested = [name for name in agent_names if name]
    running = await _running_agent_names()
    definitions = {
        str(definition.get("name", "")).strip(): definition
        for definition in await _list_definitions()
        if str(definition.get("name", "")).strip()
    }
    spawned: list[str] = []
    missing: list[str] = []
    for name in requested:
        if name in running:
            continue
        definition = definitions.get(name)
        if definition is None:
            missing.append(name)
            continue
        result = await gw._dashboard_spawn_definition(str(definition.get("agent_id", "") or ""))
        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error") or f"Failed to spawn '{name}'",
                "spawned": spawned,
            }
        spawned.append(name)
    if missing:
        return {
            "ok": False,
            "error": f"Agents are not running and have no saved definitions: {', '.join(missing)}",
            "spawned": spawned,
        }
    return {"ok": True, "spawned": spawned}


def _resolve_mode(
    mode: str,
    agent_names: list[str],
    *,
    consensus_strategy: str = "",
    shared_handoff: bool = False,
) -> str:
    selected = str(mode or "auto").strip().lower()
    if selected != "auto":
        return selected
    if not agent_names:
        return "auto-route"
    if len(agent_names) == 1:
        return "manual"
    if shared_handoff:
        return "pipeline"
    if consensus_strategy:
        return "consensus"
    return "manual"


async def list_agent_definitions(**_: Any) -> dict[str, Any]:
    try:
        running = await _running_agent_names()
        definitions = await _list_definitions()
        enriched = [{**definition, "running": str(definition.get("name", "")).strip() in running} for definition in definitions]
        return {"definitions": enriched, "count": len(enriched)}
    except Exception as exc:
        return {"error": str(exc)}


async def create_agent_definition(
    name: str,
    model: str,
    description: str = "",
    capabilities: list[str] | str | None = None,
    provider: str = "primary",
    base_url: str = "",
    system_prompt: str = "",
    memory_namespace: str = "",
    auto_start: bool = False,
    spawn_now: bool = False,
    metadata: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    gw, err = _require_gateway()
    if err:
        return err
    try:
        payload = {
            "name": str(name or "").strip(),
            "description": str(description or "").strip(),
            "capabilities": _normalize_string_list(capabilities or []),
            "provider": str(provider or "primary").strip() or "primary",
            "model": str(model or "").strip(),
            "base_url": str(base_url or "").strip(),
            "system_prompt": str(system_prompt or "").strip(),
            "memory_namespace": str(memory_namespace or "").strip(),
            "auto_start": bool(auto_start),
            "metadata": metadata if isinstance(metadata, dict) else {},
        }
        result = await gw._dashboard_create_definition(payload)
        if not result.get("ok") or not spawn_now:
            return result
        spawned = await gw._dashboard_spawn_definition(str(result.get("agent_id", "") or ""))
        return {
            **spawned,
            "agent_id": result.get("agent_id"),
            "name": payload["name"],
            "spawned": bool(spawned.get("ok")),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def update_agent_definition(
    agent_id: str = "",
    name: str = "",
    new_name: str = "",
    description: str = "",
    capabilities: list[str] | str | None = None,
    provider: str = "",
    model: str = "",
    base_url: str = "",
    system_prompt: str = "",
    memory_namespace: str = "",
    auto_start: bool | None = None,
    metadata: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    gw, err = _require_gateway()
    if err:
        return err
    try:
        definition, lookup_error = await _resolve_agent_definition(agent_id=agent_id, name=name)
        if lookup_error:
            return {"ok": False, **lookup_error}
        updates: dict[str, Any] = {}
        if str(new_name or "").strip():
            updates["name"] = str(new_name).strip()
        if description:
            updates["description"] = str(description).strip()
        if capabilities:
            updates["capabilities"] = _normalize_string_list(capabilities)
        if provider:
            updates["provider"] = str(provider).strip()
        if model:
            updates["model"] = str(model).strip()
        if base_url:
            updates["base_url"] = str(base_url).strip()
        if system_prompt:
            updates["system_prompt"] = str(system_prompt).strip()
        if memory_namespace:
            updates["memory_namespace"] = str(memory_namespace).strip()
        if auto_start is not None:
            updates["auto_start"] = bool(auto_start)
        if metadata is not None:
            updates["metadata"] = metadata if isinstance(metadata, dict) else {}
        if not updates:
            return {"ok": False, "error": "No updates provided"}
        result = await gw._dashboard_update_definition(str(definition.get("agent_id", "") or ""), updates)
        if result.get("ok"):
            result["agent_id"] = definition.get("agent_id")
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def spawn_defined_agent(agent_id: str = "", name: str = "", **_: Any) -> dict[str, Any]:
    gw, err = _require_gateway()
    if err:
        return err
    try:
        definition, lookup_error = await _resolve_agent_definition(agent_id=agent_id, name=name)
        if lookup_error:
            return {"ok": False, **lookup_error}
        result = await gw._dashboard_spawn_definition(str(definition.get("agent_id", "") or ""))
        if result.get("ok"):
            result["agent_id"] = definition.get("agent_id")
            result["name"] = definition.get("name")
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def despawn_defined_agent(agent_id: str = "", name: str = "", **_: Any) -> dict[str, Any]:
    gw, err = _require_gateway()
    if err:
        return err
    try:
        definition, lookup_error = await _resolve_agent_definition(agent_id=agent_id, name=name)
        if lookup_error:
            return {"ok": False, **lookup_error}
        result = await gw._dashboard_despawn_definition(str(definition.get("agent_id", "") or ""))
        if result.get("ok"):
            result["agent_id"] = definition.get("agent_id")
            result["name"] = definition.get("name")
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def list_running_agents(**_: Any) -> dict[str, Any]:
    gw, err = _require_gateway()
    if err:
        return err
    try:
        agents = gw._dashboard_get_running_agents()
        return {"agents": agents, "count": len(agents)}
    except Exception as exc:
        return {"error": str(exc)}


async def orchestrate_agent_task(
    task: str,
    mode: str = "auto",
    agent_names: list[str] | str | None = None,
    title: str = "",
    success_criteria: str = "",
    deliverables: list[str] | str | None = None,
    workspace_path: str = "",
    integration_targets: list[str] | str | None = None,
    execution_mode: str = "agent-task",
    require_approval: bool = False,
    approval_note: str = "",
    timeout_seconds: int = 0,
    max_agents: int = 1,
    consensus_strategy: str = "",
    shared_handoff: bool = False,
    create_shared_task: bool = False,
    spawn_missing: bool = True,
    **_: Any,
) -> dict[str, Any]:
    gw, err = _require_gateway()
    if err:
        return err
    task_text = str(task or "").strip()
    targets = _normalize_string_list(agent_names or [])
    if not task_text:
        return {"ok": False, "error": "task is required"}
    try:
        if spawn_missing and targets:
            ensure_result = await _ensure_agents_running(targets)
            if not ensure_result.get("ok"):
                return ensure_result
        else:
            ensure_result = {"ok": True, "spawned": []}
        selected_mode = _resolve_mode(mode, targets, consensus_strategy=consensus_strategy, shared_handoff=shared_handoff)
        payload: dict[str, Any] = {
            "task": task_text,
            "title": str(title or "").strip() or None,
            "success_criteria": str(success_criteria or "").strip() or None,
            "deliverables": _normalize_string_list(deliverables or []),
            "workspace_path": str(workspace_path or "").strip() or None,
            "integration_targets": _normalize_string_list(integration_targets or []),
            "execution_mode": str(execution_mode or "agent-task").strip() or "agent-task",
            "require_approval": bool(require_approval),
            "approval_note": str(approval_note or "").strip() or None,
        }
        if timeout_seconds:
            payload["timeout_seconds"] = int(timeout_seconds)
        if selected_mode == "auto-route":
            payload["max_agents"] = max(1, int(max_agents or 1))
            result = await gw._dashboard_auto_route_task(payload)
        elif selected_mode == "pipeline":
            if len(targets) < 2:
                return {"ok": False, "error": "pipeline mode requires at least 2 agent_names"}
            payload["agent_names"] = targets
            result = await gw._dashboard_pipeline_task(payload)
        elif selected_mode == "consensus":
            if len(targets) < 2:
                return {"ok": False, "error": "consensus mode requires at least 2 agent_names"}
            payload["agent_names"] = targets
            if consensus_strategy:
                payload["strategy"] = consensus_strategy
            result = await gw._dashboard_seek_consensus(payload)
        elif selected_mode == "manual":
            if not targets:
                return {"ok": False, "error": "manual mode requires agent_names"}
            if len(targets) == 1:
                payload["agent_name"] = targets[0]
            payload["agent_names"] = targets
            if create_shared_task and len(targets) > 1 and gw._shared_bridge:
                shared_task = await gw._dashboard_create_shared_task(targets)
                if not shared_task.get("ok"):
                    return shared_task
                if shared_task.get("task_id"):
                    payload["shared_task_id"] = shared_task.get("task_id")
            result = await gw._dashboard_delegate_task(payload)
        else:
            return {"ok": False, "error": "Unsupported mode"}
        result["mode"] = selected_mode
        result["spawned_agents"] = ensure_result.get("spawned", [])
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="agent_orchestration",
        description=(
            "Create persistent worker definitions, spawn or stop saved agents, inspect the live roster, "
            "and delegate work across manual, auto-route, consensus, or pipeline modes."
        ),
        tools=[
            ToolDefinition(
                name="list_agent_definitions",
                description="List saved agent definitions and show which ones are currently running.",
                parameters=[],
                handler=list_agent_definitions,
            ),
            ToolDefinition(
                name="create_agent_definition",
                description="Create a persistent worker definition and optionally spawn it immediately.",
                parameters=[
                    ToolParameter(name="name", type="string", description="Unique agent name", required=True),
                    ToolParameter(name="model", type="string", description="Model name", required=True),
                    ToolParameter(name="description", type="string", description="Human-readable summary", required=False, default=""),
                    ToolParameter(name="capabilities", type="array", description="Capabilities or specialties", required=False, default=[], items_type="string"),
                    ToolParameter(name="provider", type="string", description="Provider route", required=False, default="primary"),
                    ToolParameter(name="base_url", type="string", description="Optional base URL override", required=False, default=""),
                    ToolParameter(name="system_prompt", type="string", description="Optional specialist prompt", required=False, default=""),
                    ToolParameter(name="memory_namespace", type="string", description="Optional isolated memory namespace", required=False, default=""),
                    ToolParameter(name="auto_start", type="boolean", description="Auto-start on gateway boot", required=False, default=False),
                    ToolParameter(name="spawn_now", type="boolean", description="Spawn immediately after saving", required=False, default=False),
                    ToolParameter(name="metadata", type="object", description="Optional metadata", required=False, default={}),
                ],
                handler=create_agent_definition,
            ),
            ToolDefinition(
                name="update_agent_definition",
                description="Update an existing agent definition by id or name.",
                parameters=[
                    ToolParameter(name="agent_id", type="string", description="Saved agent id", required=False, default=""),
                    ToolParameter(name="name", type="string", description="Existing agent name", required=False, default=""),
                    ToolParameter(name="new_name", type="string", description="Rename the agent", required=False, default=""),
                    ToolParameter(name="description", type="string", description="Updated description", required=False, default=""),
                    ToolParameter(name="capabilities", type="array", description="Updated capability list", required=False, default=[], items_type="string"),
                    ToolParameter(name="provider", type="string", description="Updated provider", required=False, default=""),
                    ToolParameter(name="model", type="string", description="Updated model", required=False, default=""),
                    ToolParameter(name="base_url", type="string", description="Updated base URL", required=False, default=""),
                    ToolParameter(name="system_prompt", type="string", description="Updated system prompt", required=False, default=""),
                    ToolParameter(name="memory_namespace", type="string", description="Updated memory namespace", required=False, default=""),
                    ToolParameter(name="auto_start", type="boolean", description="Updated auto-start setting", required=False, default=False),
                    ToolParameter(name="metadata", type="object", description="Replacement metadata", required=False, default={}),
                ],
                handler=update_agent_definition,
            ),
            ToolDefinition(
                name="spawn_defined_agent",
                description="Spawn a saved worker by id or name.",
                parameters=[
                    ToolParameter(name="agent_id", type="string", description="Saved agent id", required=False, default=""),
                    ToolParameter(name="name", type="string", description="Saved agent name", required=False, default=""),
                ],
                handler=spawn_defined_agent,
            ),
            ToolDefinition(
                name="despawn_defined_agent",
                description="Stop a saved worker by id or name.",
                parameters=[
                    ToolParameter(name="agent_id", type="string", description="Saved agent id", required=False, default=""),
                    ToolParameter(name="name", type="string", description="Saved agent name", required=False, default=""),
                ],
                handler=despawn_defined_agent,
            ),
            ToolDefinition(
                name="list_running_agents",
                description="List all currently running agents in the live swarm.",
                parameters=[],
                handler=list_running_agents,
            ),
            ToolDefinition(
                name="orchestrate_agent_task",
                description="Delegate work using manual, auto-route, consensus, or pipeline mode. Auto mode chooses a suitable path and can auto-spawn missing saved workers first.",
                parameters=[
                    ToolParameter(name="task", type="string", description="Task or question to execute", required=True),
                    ToolParameter(name="mode", type="string", description="auto, manual, auto-route, pipeline, or consensus", required=False, default="auto", enum=["auto", "manual", "auto-route", "pipeline", "consensus"]),
                    ToolParameter(name="agent_names", type="array", description="Target agent names", required=False, default=[], items_type="string"),
                    ToolParameter(name="title", type="string", description="Optional durable task title", required=False, default=""),
                    ToolParameter(name="success_criteria", type="string", description="What counts as done", required=False, default=""),
                    ToolParameter(name="deliverables", type="array", description="Expected outputs", required=False, default=[], items_type="string"),
                    ToolParameter(name="workspace_path", type="string", description="Optional repo or project path", required=False, default=""),
                    ToolParameter(name="integration_targets", type="array", description="Integrations this run should touch", required=False, default=[], items_type="string"),
                    ToolParameter(name="execution_mode", type="string", description="agent-task, workspace-run, integration-loop, or review-pass", required=False, default="agent-task"),
                    ToolParameter(name="require_approval", type="boolean", description="Gate execution for user approval first", required=False, default=False),
                    ToolParameter(name="approval_note", type="string", description="Approval guidance for the inbox", required=False, default=""),
                    ToolParameter(name="timeout_seconds", type="integer", description="Optional timeout override", required=False, default=0),
                    ToolParameter(name="max_agents", type="integer", description="Used for auto-route mode", required=False, default=1),
                    ToolParameter(name="consensus_strategy", type="string", description="Consensus strategy", required=False, default=""),
                    ToolParameter(name="shared_handoff", type="boolean", description="Prefer pipeline handoff when multiple agents are specified", required=False, default=False),
                    ToolParameter(name="create_shared_task", type="boolean", description="Create shared-task memory for manual multi-agent fanout", required=False, default=False),
                    ToolParameter(name="spawn_missing", type="boolean", description="Auto-spawn saved workers before delegation", required=False, default=True),
                ],
                handler=orchestrate_agent_task,
            ),
        ],
    )
