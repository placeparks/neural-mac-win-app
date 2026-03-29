"""
Built-in Skill: Workflow — Create and manage DAG-based task pipelines.

Provides tools for defining multi-step workflows with parallel execution,
conditional branching, variable interpolation, and pause/resume support.
"""

from __future__ import annotations

import json
from typing import Any

from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter


# Module-level engine reference (set by gateway on init)
_engine: Any | None = None


def set_workflow_engine(engine: Any) -> None:
    """Set the WorkflowEngine instance for this skill."""
    global _engine
    _engine = engine


async def create_workflow(
    name: str,
    steps_json: str,
    description: str = "",
    variables_json: str = "{}",
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a new workflow from a JSON step definition."""
    if not _engine:
        return {"error": "Workflow engine is not enabled"}
    try:
        steps = json.loads(steps_json)
        variables = json.loads(variables_json)
        if not isinstance(steps, list):
            return {"error": "steps_json must be a JSON array"}
        wf = await _engine.create_workflow(
            name=name, steps=steps, description=description, variables=variables,
        )
        return {"success": True, "workflow_id": wf.id, "name": wf.name, "step_count": len(wf.steps)}
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


async def run_workflow(workflow_id: str, **kwargs: Any) -> dict[str, Any]:
    """Start executing a workflow."""
    if not _engine:
        return {"error": "Workflow engine is not enabled"}
    try:
        return await _engine.execute_workflow(workflow_id)
    except Exception as e:
        return {"error": str(e)}


async def pause_workflow(workflow_id: str, **kwargs: Any) -> dict[str, Any]:
    """Pause a running workflow."""
    if not _engine:
        return {"error": "Workflow engine is not enabled"}
    try:
        return await _engine.pause_workflow(workflow_id)
    except Exception as e:
        return {"error": str(e)}


async def resume_workflow(workflow_id: str, **kwargs: Any) -> dict[str, Any]:
    """Resume a paused workflow."""
    if not _engine:
        return {"error": "Workflow engine is not enabled"}
    try:
        return await _engine.resume_workflow(workflow_id)
    except Exception as e:
        return {"error": str(e)}


async def workflow_status(workflow_id: str, **kwargs: Any) -> dict[str, Any]:
    """Get current status of a workflow."""
    if not _engine:
        return {"error": "Workflow engine is not enabled"}
    try:
        return await _engine.get_status(workflow_id)
    except Exception as e:
        return {"error": str(e)}


async def list_workflows(**kwargs: Any) -> dict[str, Any]:
    """List all workflows."""
    if not _engine:
        return {"error": "Workflow engine is not enabled"}
    try:
        workflows = await _engine.list_workflows()
        return {"workflows": workflows, "count": len(workflows)}
    except Exception as e:
        return {"error": str(e)}


async def delete_workflow(workflow_id: str, **kwargs: Any) -> dict[str, Any]:
    """Delete a workflow and its run history."""
    if not _engine:
        return {"error": "Workflow engine is not enabled"}
    try:
        deleted = await _engine.delete_workflow(workflow_id)
        if deleted:
            return {"success": True, "workflow_id": workflow_id}
        return {"error": f"Workflow not found: {workflow_id}"}
    except Exception as e:
        return {"error": str(e)}


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="workflow",
        description="Create and manage DAG-based multi-step task pipelines with parallel execution and pause/resume",
        tools=[
            ToolDefinition(
                name="create_workflow",
                description=(
                    "Create a new workflow pipeline. Each step has: id, name, action (tool name or prompt), "
                    "action_type ('tool' or 'prompt'), action_params (dict), depends_on (list of step IDs), "
                    "condition (optional expression). Use {step_id} in action_params to reference previous results."
                ),
                parameters=[
                    ToolParameter(name="name", type="string", description="Workflow name"),
                    ToolParameter(
                        name="steps_json", type="string",
                        description='JSON array of step objects, e.g. [{"id":"s1","name":"search","action":"web_search","action_params":{"query":"test"}}]',
                    ),
                    ToolParameter(
                        name="description", type="string",
                        description="Optional workflow description",
                        required=False, default="",
                    ),
                    ToolParameter(
                        name="variables_json", type="string",
                        description="Optional JSON object of initial workflow variables",
                        required=False, default="{}",
                    ),
                ],
                handler=create_workflow,
            ),
            ToolDefinition(
                name="run_workflow",
                description="Start executing a workflow. Steps run in parallel where dependencies allow.",
                parameters=[
                    ToolParameter(name="workflow_id", type="string", description="Workflow ID to execute"),
                ],
                handler=run_workflow,
            ),
            ToolDefinition(
                name="pause_workflow",
                description="Pause a running workflow (human-in-the-loop gate)",
                parameters=[
                    ToolParameter(name="workflow_id", type="string", description="Workflow ID to pause"),
                ],
                handler=pause_workflow,
            ),
            ToolDefinition(
                name="resume_workflow",
                description="Resume a paused workflow",
                parameters=[
                    ToolParameter(name="workflow_id", type="string", description="Workflow ID to resume"),
                ],
                handler=resume_workflow,
            ),
            ToolDefinition(
                name="workflow_status",
                description="Get detailed status of a workflow including all step states",
                parameters=[
                    ToolParameter(name="workflow_id", type="string", description="Workflow ID"),
                ],
                handler=workflow_status,
            ),
            ToolDefinition(
                name="list_workflows",
                description="List all workflows with their status",
                parameters=[],
                handler=list_workflows,
            ),
            ToolDefinition(
                name="delete_workflow",
                description="Delete a workflow and its run history",
                parameters=[
                    ToolParameter(name="workflow_id", type="string", description="Workflow ID to delete"),
                ],
                handler=delete_workflow,
            ),
        ],
    )
