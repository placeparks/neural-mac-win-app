"""
Workflow Engine — DAG-based multi-step task pipelines.

Supports:
- Linear and parallel step execution (DAG with dependency tracking)
- Variable interpolation between steps ({step_id} references)
- Conditional step execution (evaluated against workflow variables)
- Pause/resume for human-in-the-loop gates
- Tool execution via SkillRegistry handler lookup
- SQLite-backed persistence for workflow definitions and run state
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

from neuralclaw.bus.neural_bus import EventType, NeuralBus

log = logging.getLogger("neuralclaw.reasoning.workflow")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class WorkflowStep:
    """A single step in a workflow pipeline."""
    id: str
    name: str
    action: str  # tool name (for type=tool) or prompt text (for type=prompt)
    action_type: str = "tool"  # "tool" or "prompt"
    action_params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    condition: str = ""  # Python expression evaluated against variables
    status: str = "pending"  # pending, running, completed, failed, skipped
    result: Any = None
    retries: int = 0
    max_retries: int = 1
    timeout_seconds: int = 120

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "action": self.action,
            "action_type": self.action_type, "action_params": self.action_params,
            "depends_on": self.depends_on, "condition": self.condition,
            "status": self.status, "result": self.result,
            "retries": self.retries, "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowStep:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            name=data.get("name", ""),
            action=data.get("action", ""),
            action_type=data.get("action_type", "tool"),
            action_params=data.get("action_params", {}),
            depends_on=data.get("depends_on", []),
            condition=data.get("condition", ""),
            status=data.get("status", "pending"),
            result=data.get("result"),
            retries=data.get("retries", 0),
            max_retries=data.get("max_retries", 1),
            timeout_seconds=data.get("timeout_seconds", 120),
        )


@dataclass
class Workflow:
    """A complete workflow pipeline."""
    id: str
    name: str
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    status: str = "pending"  # pending, running, paused, completed, failed
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    variables: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status, "created_at": self.created_at,
            "started_at": self.started_at, "completed_at": self.completed_at,
            "variables": self.variables,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Workflow:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:12]),
            name=data.get("name", ""),
            description=data.get("description", ""),
            steps=[WorkflowStep.from_dict(s) for s in data.get("steps", [])],
            status=data.get("status", "pending"),
            created_at=data.get("created_at", time.time()),
            started_at=data.get("started_at", 0.0),
            completed_at=data.get("completed_at", 0.0),
            variables=data.get("variables", {}),
        )


# ---------------------------------------------------------------------------
# Workflow Engine
# ---------------------------------------------------------------------------

class WorkflowEngine:
    """
    DAG-based workflow execution engine with SQLite persistence.

    Steps with no dependencies run in parallel. Each step's result
    is stored as a workflow variable accessible by downstream steps.
    """

    def __init__(
        self,
        db_path: str,
        bus: NeuralBus | None = None,
        skill_registry: Any | None = None,
        max_concurrent: int = 5,
        max_steps: int = 50,
        step_timeout: int = 120,
    ) -> None:
        self._db_path = db_path
        self._bus = bus
        self._skill_registry = skill_registry
        self._max_concurrent = max_concurrent
        self._max_steps = max_steps
        self._default_step_timeout = step_timeout
        self._db: aiosqlite.Connection | None = None
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running_workflows: dict[str, asyncio.Task[None]] = {}
        self._paused: set[str] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create database tables."""
        try:
            self._db = await aiosqlite.connect(self._db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA foreign_keys=ON")
            await self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    steps_json TEXT NOT NULL DEFAULT '[]',
                    variables_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL DEFAULT (unixepoch('now')),
                    started_at REAL NOT NULL DEFAULT 0,
                    completed_at REAL NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS workflow_runs (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
                    step_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    started_at REAL NOT NULL DEFAULT 0,
                    completed_at REAL NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_workflow_runs_wf
                    ON workflow_runs(workflow_id);
                """
            )
            await self._db.commit()
        except Exception as exc:
            log.error("WorkflowEngine initialize failed: %s", exc)

    async def close(self) -> None:
        """Cancel running workflows and close database."""
        for task in self._running_workflows.values():
            task.cancel()
        self._running_workflows.clear()
        if self._db:
            await self._db.close()
            self._db = None

    async def ping(self) -> bool:
        """Readiness check."""
        if not self._db:
            return False
        try:
            rows = await self._db.execute_fetchall("SELECT 1")
            return bool(rows and rows[0][0] == 1)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Workflow CRUD
    # ------------------------------------------------------------------

    async def create_workflow(
        self,
        name: str,
        steps: list[dict[str, Any]],
        description: str = "",
        variables: dict[str, Any] | None = None,
    ) -> Workflow:
        """Create a new workflow definition."""
        if not self._db:
            raise RuntimeError("Workflow engine not initialized")

        if len(steps) > self._max_steps:
            raise ValueError(f"Workflow exceeds max {self._max_steps} steps")

        wf = Workflow(
            id=uuid.uuid4().hex[:12],
            name=name,
            description=description,
            steps=[WorkflowStep.from_dict(s) for s in steps],
            variables=variables or {},
        )

        # Validate DAG (no cycles)
        self._validate_dag(wf)

        await self._db.execute(
            """
            INSERT INTO workflows (id, name, description, status, steps_json, variables_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (wf.id, wf.name, wf.description, wf.status,
             json.dumps([s.to_dict() for s in wf.steps]),
             json.dumps(wf.variables), wf.created_at),
        )
        await self._db.commit()

        if self._bus:
            await self._bus.publish(
                EventType.WORKFLOW_CREATED,
                {"workflow_id": wf.id, "name": wf.name, "step_count": len(wf.steps)},
                source="reasoning.workflow",
            )

        return wf

    async def execute_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Start executing a workflow asynchronously."""
        wf = await self._load_workflow(workflow_id)
        if not wf:
            return {"error": f"Workflow not found: {workflow_id}"}

        if wf.status == "running":
            return {"error": "Workflow is already running"}

        wf.status = "running"
        wf.started_at = time.time()
        await self._save_workflow(wf)

        task = asyncio.create_task(self._run_workflow(wf))
        self._running_workflows[workflow_id] = task
        return {"success": True, "workflow_id": workflow_id, "status": "running"}

    async def pause_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Pause a running workflow."""
        wf = await self._load_workflow(workflow_id)
        if not wf:
            return {"error": f"Workflow not found: {workflow_id}"}
        if wf.status != "running":
            return {"error": f"Workflow is not running (status: {wf.status})"}

        self._paused.add(workflow_id)
        wf.status = "paused"
        await self._save_workflow(wf)

        if self._bus:
            await self._bus.publish(
                EventType.WORKFLOW_PAUSED,
                {"workflow_id": workflow_id},
                source="reasoning.workflow",
            )
        return {"success": True, "workflow_id": workflow_id, "status": "paused"}

    async def resume_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Resume a paused workflow."""
        wf = await self._load_workflow(workflow_id)
        if not wf:
            return {"error": f"Workflow not found: {workflow_id}"}
        if wf.status != "paused":
            return {"error": f"Workflow is not paused (status: {wf.status})"}

        self._paused.discard(workflow_id)
        wf.status = "running"
        await self._save_workflow(wf)

        task = asyncio.create_task(self._run_workflow(wf))
        self._running_workflows[workflow_id] = task
        return {"success": True, "workflow_id": workflow_id, "status": "running"}

    async def get_status(self, workflow_id: str) -> dict[str, Any]:
        """Get current workflow status."""
        wf = await self._load_workflow(workflow_id)
        if not wf:
            return {"error": f"Workflow not found: {workflow_id}"}
        return wf.to_dict()

    async def list_workflows(self) -> list[dict[str, Any]]:
        """List all workflows."""
        if not self._db:
            return []
        rows = await self._db.execute_fetchall(
            "SELECT id, name, description, status, created_at, started_at, completed_at "
            "FROM workflows ORDER BY created_at DESC"
        )
        return [
            {
                "id": r[0], "name": r[1], "description": r[2],
                "status": r[3], "created_at": r[4],
                "started_at": r[5], "completed_at": r[6],
            }
            for r in rows
        ]

    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow and its run history."""
        if not self._db:
            return False
        # Cancel if running
        if workflow_id in self._running_workflows:
            self._running_workflows[workflow_id].cancel()
            del self._running_workflows[workflow_id]
        self._paused.discard(workflow_id)
        cursor = await self._db.execute(
            "DELETE FROM workflows WHERE id = ?", (workflow_id,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # DAG execution
    # ------------------------------------------------------------------

    async def _run_workflow(self, wf: Workflow) -> None:
        """Execute workflow steps in topological order with parallel layers."""
        try:
            if self._bus:
                await self._bus.publish(
                    EventType.WORKFLOW_STARTED,
                    {"workflow_id": wf.id, "name": wf.name},
                    source="reasoning.workflow",
                )

            layers = self._topological_layers(wf)

            for layer in layers:
                if wf.id in self._paused:
                    return  # Paused — will resume later

                # Execute all steps in this layer in parallel
                tasks = []
                for step in layer:
                    if step.status in ("completed", "skipped"):
                        continue
                    tasks.append(self._execute_step(wf, step))

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await self._save_workflow(wf)

            # Check if all steps completed
            failed = [s for s in wf.steps if s.status == "failed"]
            if failed:
                wf.status = "failed"
            else:
                wf.status = "completed"
            wf.completed_at = time.time()
            await self._save_workflow(wf)

            if self._bus:
                await self._bus.publish(
                    EventType.WORKFLOW_COMPLETED,
                    {
                        "workflow_id": wf.id,
                        "status": wf.status,
                        "duration": wf.completed_at - wf.started_at,
                    },
                    source="reasoning.workflow",
                )

        except asyncio.CancelledError:
            wf.status = "paused"
            await self._save_workflow(wf)
        except Exception as exc:
            log.error("Workflow %s failed: %s", wf.id, exc)
            wf.status = "failed"
            wf.completed_at = time.time()
            await self._save_workflow(wf)
        finally:
            self._running_workflows.pop(wf.id, None)

    async def _execute_step(self, wf: Workflow, step: WorkflowStep) -> None:
        """Execute a single workflow step."""
        # Check condition
        if step.condition:
            try:
                if not self._evaluate_condition(step.condition, wf.variables):
                    step.status = "skipped"
                    return
            except Exception as exc:
                log.warning("Condition eval failed for step %s: %s", step.id, exc)
                step.status = "skipped"
                return

        step.status = "running"
        if self._bus:
            await self._bus.publish(
                EventType.WORKFLOW_STEP_STARTED,
                {"workflow_id": wf.id, "step_id": step.id, "step_name": step.name},
                source="reasoning.workflow",
            )

        timeout = step.timeout_seconds or self._default_step_timeout
        attempt = 0

        while attempt <= step.max_retries:
            try:
                result = await asyncio.wait_for(
                    self._invoke_step(wf, step),
                    timeout=timeout,
                )
                step.result = result
                step.status = "completed"
                wf.variables[step.id] = result

                if self._bus:
                    await self._bus.publish(
                        EventType.WORKFLOW_STEP_COMPLETED,
                        {
                            "workflow_id": wf.id,
                            "step_id": step.id,
                            "status": "completed",
                        },
                        source="reasoning.workflow",
                    )
                return

            except asyncio.TimeoutError:
                attempt += 1
                step.retries = attempt
                log.warning("Step %s timed out (attempt %d/%d)", step.id, attempt, step.max_retries + 1)
            except Exception as exc:
                attempt += 1
                step.retries = attempt
                log.warning("Step %s failed (attempt %d/%d): %s", step.id, attempt, step.max_retries + 1, exc)

        step.status = "failed"
        step.result = {"error": "Max retries exceeded"}

        if self._bus:
            await self._bus.publish(
                EventType.WORKFLOW_STEP_COMPLETED,
                {"workflow_id": wf.id, "step_id": step.id, "status": "failed"},
                source="reasoning.workflow",
            )

    async def _invoke_step(self, wf: Workflow, step: WorkflowStep) -> Any:
        """Invoke a step's action (tool call or prompt)."""
        # Interpolate variables into action params
        params = self._interpolate(step.action_params, wf.variables)

        if step.action_type == "tool":
            return await self._call_tool(step.action, params)
        elif step.action_type == "prompt":
            # For prompt-type steps, return the interpolated action text as result
            return {"response": self._interpolate_string(step.action, wf.variables)}
        else:
            return {"error": f"Unknown action type: {step.action_type}"}

    async def _call_tool(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Look up and call a tool handler from the SkillRegistry."""
        if not self._skill_registry:
            return {"error": "Skill registry not available"}

        handler = self._skill_registry.get_handler(tool_name)
        if not handler:
            return {"error": f"Tool not found: {tool_name}"}

        try:
            return await handler(**params)
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # DAG utilities
    # ------------------------------------------------------------------

    def _validate_dag(self, wf: Workflow) -> None:
        """Validate that the workflow steps form a valid DAG (no cycles)."""
        step_ids = {s.id for s in wf.steps}
        for step in wf.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    raise ValueError(f"Step '{step.id}' depends on unknown step '{dep}'")

        # Cycle detection via topological sort
        in_degree: dict[str, int] = {s.id: 0 for s in wf.steps}
        adj: dict[str, list[str]] = defaultdict(list)
        for step in wf.steps:
            for dep in step.depends_on:
                adj[dep].append(step.id)
                in_degree[step.id] += 1

        queue: deque[str] = deque(sid for sid, deg in in_degree.items() if deg == 0)
        visited = 0
        while queue:
            node = queue.popleft()
            visited += 1
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited != len(wf.steps):
            raise ValueError("Workflow contains a cycle")

    def _topological_layers(self, wf: Workflow) -> list[list[WorkflowStep]]:
        """Group steps into parallel execution layers using Kahn's algorithm."""
        step_map = {s.id: s for s in wf.steps}
        in_degree: dict[str, int] = {s.id: 0 for s in wf.steps}
        adj: dict[str, list[str]] = defaultdict(list)

        for step in wf.steps:
            for dep in step.depends_on:
                adj[dep].append(step.id)
                in_degree[step.id] += 1

        layers: list[list[WorkflowStep]] = []
        queue: list[str] = [sid for sid, deg in in_degree.items() if deg == 0]

        while queue:
            layers.append([step_map[sid] for sid in queue])
            next_queue: list[str] = []
            for sid in queue:
                for neighbor in adj[sid]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_queue.append(neighbor)
            queue = next_queue

        return layers

    # ------------------------------------------------------------------
    # Variable interpolation & condition evaluation
    # ------------------------------------------------------------------

    def _interpolate(self, params: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
        """Interpolate {var} references in parameter values."""
        result: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str):
                result[key] = self._interpolate_string(value, variables)
            elif isinstance(value, dict):
                result[key] = self._interpolate(value, variables)
            else:
                result[key] = value
        return result

    @staticmethod
    def _interpolate_string(text: str, variables: dict[str, Any]) -> str:
        """Replace {var} placeholders with variable values."""
        for key, value in variables.items():
            placeholder = "{" + key + "}"
            if placeholder in text:
                text = text.replace(placeholder, str(value) if not isinstance(value, str) else value)
        return text

    @staticmethod
    def _evaluate_condition(condition: str, variables: dict[str, Any]) -> bool:
        """Safely evaluate a condition expression against workflow variables."""
        # Restrict to only workflow variables — no builtins
        safe_globals: dict[str, Any] = {"__builtins__": {}}
        safe_locals = dict(variables)
        try:
            return bool(eval(condition, safe_globals, safe_locals))  # noqa: S307
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _load_workflow(self, workflow_id: str) -> Workflow | None:
        """Load a workflow from the database."""
        if not self._db:
            return None
        rows = await self._db.execute_fetchall(
            "SELECT id, name, description, status, steps_json, variables_json, "
            "created_at, started_at, completed_at FROM workflows WHERE id = ?",
            (workflow_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return Workflow(
            id=r[0], name=r[1], description=r[2], status=r[3],
            steps=[WorkflowStep.from_dict(s) for s in json.loads(r[4])],
            variables=json.loads(r[5]),
            created_at=r[6], started_at=r[7], completed_at=r[8],
        )

    async def _save_workflow(self, wf: Workflow) -> None:
        """Persist current workflow state to the database."""
        if not self._db:
            return
        await self._db.execute(
            """
            UPDATE workflows SET status = ?, steps_json = ?, variables_json = ?,
                   started_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (wf.status, json.dumps([s.to_dict() for s in wf.steps]),
             json.dumps(wf.variables), wf.started_at, wf.completed_at, wf.id),
        )
        await self._db.commit()
