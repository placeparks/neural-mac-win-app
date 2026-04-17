from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

from .contracts import AdaptiveSuggestion, ChangeReceipt, LearningDiff, ProjectContextProfile, TeachingArtifact


class AdaptiveControlPlane:
    """Persistent operator-facing adaptive state.

    The control plane synthesizes suggestions, project briefs, learning diffs,
    and change receipts from existing runtime subsystems without requiring a
    parallel product stack.
    """

    def __init__(self, db_path: str | Path, workspace_root: str | Path | None = None) -> None:
        self._db_path = Path(db_path)
        self._workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS adaptive_suggestions (
                    suggestion_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS adaptive_project_profiles (
                    project_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS adaptive_learning_diffs (
                    cycle_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS adaptive_change_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS adaptive_playbook_entries (
                    entry_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS adaptive_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    task_id TEXT,
                    snapshot_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS adaptive_rollback_log (
                    rollback_id TEXT PRIMARY KEY,
                    receipt_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_json TEXT,
                    created_at REAL NOT NULL,
                    executed_at REAL
                );

                CREATE TABLE IF NOT EXISTS adaptive_routines (
                    routine_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    trigger_pattern TEXT NOT NULL,
                    action_template TEXT NOT NULL,
                    risk_level TEXT NOT NULL DEFAULT 'low',
                    autonomy_class TEXT NOT NULL DEFAULT 'suggest-first',
                    probation_status TEXT NOT NULL DEFAULT 'observed',
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    last_run_at REAL,
                    payload_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS adaptive_project_sessions (
                    session_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    memory_snapshot_json TEXT,
                    skill_snapshot_json TEXT,
                    activated_at REAL,
                    suspended_at REAL,
                    updated_at REAL NOT NULL
                );
                """
            )
            await db.commit()
        self._initialized = True

    async def close(self) -> None:
        self._initialized = False

    async def sync_snapshot(
        self,
        *,
        tasks: list[dict[str, Any]],
        audit_events: list[dict[str, Any]],
        integrations: list[dict[str, Any]],
        kb_docs: list[dict[str, Any]],
        running_agents: list[dict[str, Any]],
        evolution_initiatives: list[dict[str, Any]] | None = None,
        workspace_root: str | Path | None = None,
    ) -> dict[str, Any]:
        if not self._initialized:
            await self.initialize()
        project_profile = self._build_project_profile(
            tasks=tasks,
            integrations=integrations,
            running_agents=running_agents,
            workspace_root=workspace_root,
        )
        suggestions = self._build_suggestions(
            tasks=tasks,
            audit_events=audit_events,
            integrations=integrations,
            project_profile=project_profile,
        )
        learning_diffs = self._build_learning_diffs(evolution_initiatives or [])
        recent_receipts = self._build_change_receipts(tasks)
        routines = await self.list_routines(limit=8)
        if not routines:
            routines = [
                {
                    "routine_id": f"routine-{str(item.get('suggestion_id') or '')}",
                    "title": str(item.get("title") or "Routine candidate"),
                    "trigger_pattern": str(item.get("summary") or ""),
                    "action_template": str(item.get("proposed_action") or ""),
                    "risk_level": str(item.get("risk_level") or "low"),
                    "autonomy_class": "suggest-first",
                    "probation_status": "observed",
                    "success_count": 0,
                    "failure_count": 0,
                }
                for item in suggestions
                if str(item.get("category") or "") == "intent_prediction"
            ][:6]
        active_project = await self.get_active_project()
        playbook_entries = await self.list_playbook_entries(limit=6)

        if self._initialized:
            await self._persist_records("adaptive_project_profiles", "project_id", [project_profile])
            await self._persist_records("adaptive_suggestions", "suggestion_id", suggestions)
            await self._persist_records("adaptive_learning_diffs", "cycle_id", learning_diffs)
            await self._persist_records("adaptive_change_receipts", "receipt_id", recent_receipts)
            await self._seed_routines_from_suggestions(suggestions)

        return {
            "adaptive_suggestions": suggestions,
            "next_actions": suggestions[:3],
            "project_brief": project_profile,
            "learning_diffs": learning_diffs,
            "recent_receipts": recent_receipts,
            "proactive_routines": routines,
            "active_project": active_project,
            "playbook_entries": playbook_entries,
        }

    async def _seed_routines_from_suggestions(self, suggestions: list[dict[str, Any]]) -> None:
        existing = {item["routine_id"] for item in await self.list_routines(limit=200)}
        for item in suggestions:
            if str(item.get("category") or "") != "intent_prediction":
                continue
            title = str(item.get("title") or "").strip() or "Routine candidate"
            routine_id = f"routine-{hashlib.sha1(title.encode('utf-8')).hexdigest()[:12]}"
            if routine_id in existing:
                continue
            await self.create_routine(
                title=title,
                trigger_pattern=str(item.get("summary") or title),
                action_template=str(item.get("proposed_action") or title),
                risk_level=str(item.get("risk_level") or "low"),
                autonomy_class="suggest-first",
            )

    def _build_project_profile(
        self,
        *,
        tasks: list[dict[str, Any]],
        integrations: list[dict[str, Any]],
        running_agents: list[dict[str, Any]],
        workspace_root: str | Path | None = None,
    ) -> dict[str, Any]:
        root = Path(workspace_root).resolve() if workspace_root else self._workspace_root
        agents_md = root / "AGENTS.md"
        agents_summary = ""
        if agents_md.exists():
            try:
                lines = [line.strip() for line in agents_md.read_text(encoding="utf-8").splitlines() if line.strip()]
                agents_summary = " ".join(lines[1:4])[:320] if len(lines) > 1 else (lines[0] if lines else "")
            except Exception:
                agents_summary = ""

        recent_tasks = tasks[:3]
        open_work = [
            str(task.get("title") or task.get("task_id") or "").strip()
            for task in tasks
            if str(task.get("status") or "").lower() in {"queued", "running", "awaiting_approval", "partial", "failed"}
        ][:4]
        active_skills = sorted({
            str(event.get("tool_name") or "").strip()
            for event in tasks[:6]
            if isinstance(event, dict) and str(event.get("tool_name") or "").strip()
        })
        project_id = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:12]
        preferred = next((task for task in tasks if task.get("effective_model") or task.get("provider")), {}) or {}

        autonomy_mode = next(
            (
                str((task.get("metadata") or {}).get("autonomy_mode") or "").strip()
                for task in tasks
                if isinstance(task, dict) and isinstance(task.get("metadata"), dict) and (task.get("metadata") or {}).get("autonomy_mode")
            ),
            "",
        ) or "suggest-first"
        now = time.time()
        return ProjectContextProfile(
            project_id=project_id,
            title=root.name or "Workspace",
            paths=[str(root)],
            agents_md_summary=agents_summary or "No AGENTS.md summary available yet.",
            active_skills=active_skills[:8],
            preferred_provider=str(preferred.get("provider") or "primary"),
            preferred_model=str(preferred.get("effective_model") or preferred.get("requested_model") or "auto"),
            recent_tasks=[
                {
                    "task_id": task.get("task_id"),
                    "title": task.get("title"),
                    "status": task.get("status"),
                }
                for task in recent_tasks
            ],
            last_known_open_work=open_work,
            connected_integrations=[
                str(item.get("label") or item.get("id") or "").strip()
                for item in integrations
                if isinstance(item, dict) and item.get("connected")
            ][:6],
            running_agents=[
                str(agent.get("name") or agent.get("id") or "").strip()
                for agent in running_agents
                if isinstance(agent, dict)
            ][:6],
            autonomy_mode=autonomy_mode,
            created_at=now,
            updated_at=now,
        ).to_dict()

    def _build_suggestions(
        self,
        *,
        tasks: list[dict[str, Any]],
        audit_events: list[dict[str, Any]],
        integrations: list[dict[str, Any]],
        project_profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        now = time.time()
        suggestions: list[AdaptiveSuggestion] = []
        pending = [task for task in tasks if str(task.get("status") or "").lower() == "awaiting_approval"]
        failed = [task for task in tasks if str(task.get("status") or "").lower() in {"failed", "partial"}]
        recent_tool_names = [
            str(event.get("tool_name") or "").strip()
            for event in audit_events[:12]
            if str(event.get("tool_name") or "").strip()
        ]

        if pending:
            task = pending[0]
            suggestions.append(AdaptiveSuggestion(
                suggestion_id=f"suggest-approval-{task.get('task_id')}",
                category="approval",
                title="Clear the approval backlog",
                summary=f"{len(pending)} task(s) are blocked on explicit review.",
                confidence=0.92,
                rationale="Recent operator activity shows approval-gated work waiting to move.",
                proposed_action="Review the blocked task, approve low-risk work, and leave a rejection reason where needed.",
                risk_level="medium",
                project_scope=str(project_profile.get("project_id") or ""),
                requires_approval=True,
                score=0.92,
                created_at=now,
            ))
        if failed:
            task = failed[0]
            suggestions.append(AdaptiveSuggestion(
                suggestion_id=f"suggest-retry-{task.get('task_id')}",
                category="self_correction",
                title="Run a failure analysis",
                summary=str(task.get("title") or "A recent task failed"),
                confidence=0.88,
                rationale="A recent task ended in partial or failed state and should feed the corrective loop.",
                proposed_action="Inspect the error, classify the failure mode, then retry with a narrower scope or alternate provider.",
                risk_level="low",
                project_scope=str(project_profile.get("project_id") or ""),
                requires_approval=False,
                score=0.9,
                created_at=now,
            ))
        if recent_tool_names:
            repeated = self._top_repeated(recent_tool_names)
            if repeated:
                suggestions.append(AdaptiveSuggestion(
                    suggestion_id=f"suggest-routine-{repeated['name']}",
                    category="intent_prediction",
                    title="Promote a repeated workflow",
                    summary=f"{repeated['name']} appeared {repeated['count']} times in recent actions.",
                    confidence=0.74,
                    rationale="Repeated actions are a strong candidate for a suggested routine before auto-run.",
                    proposed_action=f"Offer a reusable routine around {repeated['name']} with operator review before promotion.",
                    risk_level="low",
                    project_scope=str(project_profile.get("project_id") or ""),
                    requires_approval=False,
                    score=min(0.89, 0.56 + repeated["count"] * 0.08),
                    created_at=now,
                ))
        if project_profile.get("agents_md_summary"):
            suggestions.append(AdaptiveSuggestion(
                suggestion_id=f"suggest-project-{project_profile.get('project_id')}",
                category="project_context",
                title="Refresh the project brief",
                summary=f"Workspace focus: {project_profile.get('title')}",
                confidence=0.66,
                rationale="Project context should be visible before new work starts.",
                proposed_action="Load the project brief, active integrations, and last open work into the operator surface.",
                risk_level="low",
                project_scope=str(project_profile.get("project_id") or ""),
                requires_approval=False,
                score=0.67,
                created_at=now,
            ))

        connected = [item for item in integrations if isinstance(item, dict) and item.get("connected")]
        if connected:
            suggestions.append(AdaptiveSuggestion(
                suggestion_id="suggest-teaching-mode",
                category="teaching",
                title="Capture this flow into the playbook",
                summary="Connected apps and recent work are enough to explain and template the next run.",
                confidence=0.61,
                rationale="Teaching mode is most useful once workflows and integrations are visible.",
                proposed_action="Run the next task in teaching mode and turn the result into a reusable template or skill candidate.",
                risk_level="low",
                project_scope=str(project_profile.get("project_id") or ""),
                requires_approval=False,
                score=0.58,
                created_at=now,
            ))
        ranked = sorted(
            (item.to_dict() for item in suggestions),
            key=lambda item: (float(item.get("score") or 0.0), float(item.get("confidence") or 0.0)),
            reverse=True,
        )
        return ranked[:6]

    def _build_learning_diffs(self, initiatives: list[dict[str, Any]]) -> list[dict[str, Any]]:
        diffs: list[dict[str, Any]] = []
        now = time.time()
        for initiative in initiatives[:8]:
            state = str(initiative.get("state") or "observed")
            fingerprint = str(initiative.get("fingerprint") or "")[:12]
            probation_status = (
                "promoted" if state == "promoted"
                else "probation" if state == "probation"
                else "quarantined" if state == "quarantined"
                else "observed"
            )
            approval_status = "auto_promoted" if state == "promoted" else "needs_review"
            failure_count = int(initiative.get("failure_count") or 0)
            diffs.append(LearningDiff(
                cycle_id=f"learning-{fingerprint or len(diffs)}",
                behavior_change_summary=(
                    f"Strategy '{initiative.get('strategy') or 'unknown'}' tracked for "
                    f"'{initiative.get('query') or 'unspecified request'}'."
                ),
                source_events=[str(failure_count)],
                impacted_artifacts=[
                    str(initiative.get("strategy") or "runtime_skill_candidate"),
                    *([str(initiative.get("skill_name") or "").strip()] if initiative.get("skill_name") else []),
                ],
                probation_status=probation_status,
                approval_status=approval_status,
                last_error=str(initiative.get("last_error") or ""),
                created_at=now,
            ).to_dict())
        return diffs

    def _build_change_receipts(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        receipts: list[dict[str, Any]] = []
        now = time.time()
        for task in tasks[:8]:
            metadata = task.get("metadata", {}) if isinstance(task.get("metadata"), dict) else {}
            receipt = metadata.get("change_receipt")
            if isinstance(receipt, dict):
                receipts.append(receipt)
                continue
            operations = []
            for entry in list(metadata.get("execution_log", []) or [])[:4]:
                if isinstance(entry, dict):
                    operations.append(str(entry.get("event") or entry.get("detail") or "operation"))
            artifacts = list(metadata.get("artifacts", []) or [])
            files_changed = [
                str(item.get("value") or "")
                for item in artifacts
                if isinstance(item, dict) and str(item.get("label") or "").lower() in {"file", "path"}
            ][:6]
            if not operations and not files_changed and not artifacts:
                continue
            receipt_id = f"receipt-{task.get('task_id')}"
            receipts.append(ChangeReceipt(
                receipt_id=receipt_id,
                task_id=str(task.get("task_id") or ""),
                operation_list=operations[:6],
                operations=operations[:6],
                files_changed=files_changed,
                integrations_touched=list(metadata.get("brief", {}).get("integration_targets", [])) if isinstance(metadata.get("brief"), dict) else [],
                memory_updated=list(metadata.get("memory_scopes", []) or []),
                artifacts=artifacts[:6] if isinstance(artifacts, list) else [],
                rollback_token=str(metadata.get("rollback_token") or "") or None,
                rollback_available=bool(metadata.get("rollback_available") or metadata.get("rollback_refs")),
                snapshot_id=str(metadata.get("snapshot_id") or "") or None,
                summary=f"{len(operations[:6])} operation(s), {len(files_changed)} file reference(s)",
                created_at=float(task.get("updated_at") or task.get("created_at") or now),
            ).to_dict())
        return receipts

    # ------------------------------------------------------------------
    # Feature 1: Real Rollback / Snapshot Mechanics
    # ------------------------------------------------------------------

    async def create_snapshot(self, task_id: str, snapshot_type: str, payload: dict) -> str:
        """Create a pre-change snapshot. Returns snapshot_id."""
        if not self._initialized:
            await self.initialize()
        now = time.time()
        ts_hex = format(int(now * 1000), "x")
        snapshot_id = f"snap-{task_id[:8]}-{ts_hex}"
        snapshot_payload = self._build_snapshot_payload(payload)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO adaptive_snapshots (snapshot_id, task_id, snapshot_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (snapshot_id, task_id, snapshot_type, json.dumps(snapshot_payload), now),
            )
            await self._attach_snapshot_to_receipts(db, task_id, snapshot_id, now)
            await db.commit()
        return snapshot_id

    async def execute_rollback(self, receipt_id: str) -> dict:
        """Execute rollback using the receipt's snapshot. Returns result."""
        if not self._initialized:
            await self.initialize()
        now = time.time()
        rollback_id = f"rb-{uuid.uuid4().hex[:12]}"
        receipt_data: dict[str, Any] = {}
        task_id = ""
        snapshot_id = ""
        snapshot_payload: dict[str, Any] = {}
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM adaptive_change_receipts WHERE receipt_id = ?",
                (receipt_id,),
            )
            receipt_row = await cursor.fetchone()
            if not receipt_row:
                return {"ok": False, "error": f"Receipt {receipt_id} not found"}

            receipt_data = json.loads(receipt_row["payload_json"])
            task_id = receipt_row["task_id"] or receipt_data.get("task_id", "")

            cursor = await db.execute(
                "SELECT * FROM adaptive_snapshots WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
                (task_id,),
            )
            snap_row = await cursor.fetchone()
            snapshot_id = snap_row["snapshot_id"] if snap_row else ""
            snapshot_payload = json.loads(snap_row["payload_json"] or "{}") if snap_row else {}

        operations = receipt_data.get("operations", [])
        if not snapshot_id:
            result = {
                "ok": False,
                "rollback_id": rollback_id,
                "receipt_id": receipt_id,
                "task_id": task_id,
                "snapshot_id": "",
                "status": "failed",
                "error": f"No snapshot found for task {task_id or receipt_id}",
                "operations_reversed": operations,
            }
        else:
            result = await self._restore_snapshot_payload(snapshot_id, snapshot_payload)
            result.update({
                "rollback_id": rollback_id,
                "receipt_id": receipt_id,
                "task_id": task_id,
                "snapshot_id": snapshot_id,
                "operations_reversed": operations,
            })

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO adaptive_rollback_log
                    (rollback_id, receipt_id, snapshot_id, status, result_json, created_at, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rollback_id,
                    receipt_id,
                    snapshot_id,
                    str(result.get("status") or ("completed" if result.get("ok") else "failed")),
                    json.dumps(result),
                    now,
                    now,
                ),
            )

            receipt_data["rollback_token"] = rollback_id if result.get("ok") else str(receipt_data.get("rollback_token") or "")
            receipt_data["rollback_status"] = str(result.get("status") or ("completed" if result.get("ok") else "failed"))
            receipt_data["rollback_available"] = False if result.get("ok") else bool(snapshot_id)
            if snapshot_id:
                receipt_data["snapshot_id"] = snapshot_id
            resource_entries = receipt_data.get("resource_entries")
            if isinstance(resource_entries, list):
                for entry in resource_entries:
                    if not isinstance(entry, dict):
                        continue
                    if str(entry.get("resource_type") or "") == "file":
                        entry["rollback_status"] = "rolled_back" if result.get("ok") else str(entry.get("rollback_status") or "snapshot_required")
                receipt_data["resource_entries"] = resource_entries
            await db.execute(
                """
                UPDATE adaptive_change_receipts
                SET payload_json = ?, updated_at = ?
                WHERE receipt_id = ?
                """,
                (json.dumps(receipt_data), now, receipt_id),
            )
            await db.commit()
        return result

    async def rollback_snapshot(self, snapshot_id: str) -> dict:
        """Restore a snapshot directly when an explicit snapshot id is provided."""
        if not self._initialized:
            await self.initialize()
        payload: dict[str, Any] = {}
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM adaptive_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return {"ok": False, "error": f"Snapshot {snapshot_id} not found"}
            payload = json.loads(row["payload_json"] or "{}")
        result = await self._restore_snapshot_payload(snapshot_id, payload)
        rollback_id = f"rb-{uuid.uuid4().hex[:12]}"
        now = time.time()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO adaptive_rollback_log
                    (rollback_id, receipt_id, snapshot_id, status, result_json, created_at, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rollback_id,
                    "",
                    snapshot_id,
                    str(result.get("status") or ("completed" if result.get("ok") else "failed")),
                    json.dumps(result),
                    now,
                    now,
                ),
            )
            await db.commit()
        result["rollback_id"] = rollback_id
        return result

    async def list_snapshots(self, task_id: str | None = None, limit: int = 20) -> list[dict]:
        """List snapshots, optionally filtered by task_id."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            if task_id:
                cursor = await db.execute(
                    "SELECT * FROM adaptive_snapshots WHERE task_id = ? ORDER BY created_at DESC LIMIT ?",
                    (task_id, limit),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM adaptive_snapshots ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cursor.fetchall()
            return [
                {
                    "snapshot_id": row["snapshot_id"],
                    "task_id": row["task_id"],
                    "snapshot_type": row["snapshot_type"],
                    "payload": json.loads(row["payload_json"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

    async def get_rollback_status(self, receipt_id: str) -> dict | None:
        """Get rollback status for a receipt."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM adaptive_rollback_log WHERE receipt_id = ? ORDER BY created_at DESC LIMIT 1",
                (receipt_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "rollback_id": row["rollback_id"],
                "receipt_id": row["receipt_id"],
                "snapshot_id": row["snapshot_id"],
                "status": row["status"],
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "created_at": row["created_at"],
                "executed_at": row["executed_at"],
            }

    # ------------------------------------------------------------------
    # Feature 2: Persisted Proactive Routines with Probation/Promotion
    # ------------------------------------------------------------------

    async def create_routine(
        self,
        title: str,
        trigger_pattern: str,
        action_template: str,
        risk_level: str = "low",
        autonomy_class: str = "suggest-first",
    ) -> str:
        """Create a new routine candidate. Returns routine_id."""
        now = time.time()
        routine_id = f"routine-{uuid.uuid4().hex[:12]}"
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO adaptive_routines
                    (routine_id, title, trigger_pattern, action_template,
                     risk_level, autonomy_class, probation_status,
                     success_count, failure_count, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'observed', 0, 0, '{}', ?, ?)
                """,
                (routine_id, title, trigger_pattern, action_template, risk_level, autonomy_class, now, now),
            )
            await db.commit()
        return routine_id

    async def list_routines(self, status: str | None = None, limit: int = 50) -> list[dict]:
        """List routines, optionally filtered by probation_status."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            if status:
                cursor = await db.execute(
                    "SELECT * FROM adaptive_routines WHERE probation_status = ? ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM adaptive_routines ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cursor.fetchall()
            return [self._routine_row_to_dict(row) for row in rows]

    async def update_routine_status(self, routine_id: str, new_status: str, reason: str = "") -> dict:
        """Transition routine status (observed->probation->promoted or ->quarantined)."""
        now = time.time()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM adaptive_routines WHERE routine_id = ?",
                (routine_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return {"ok": False, "error": f"Routine {routine_id} not found"}

            payload = json.loads(row["payload_json"] or "{}")
            payload["status_reason"] = reason

            await db.execute(
                """
                UPDATE adaptive_routines
                SET probation_status = ?, payload_json = ?, updated_at = ?
                WHERE routine_id = ?
                """,
                (new_status, json.dumps(payload), now, routine_id),
            )
            await db.commit()

            cursor = await db.execute(
                "SELECT * FROM adaptive_routines WHERE routine_id = ?",
                (routine_id,),
            )
            updated = await cursor.fetchone()
            return self._routine_row_to_dict(updated)  # type: ignore[arg-type]

    async def record_routine_outcome(self, routine_id: str, success: bool) -> dict:
        """Track routine execution outcome.

        Auto-promote after 3 successes (if risk_level is 'low'),
        auto-quarantine after 3 failures.
        """
        now = time.time()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM adaptive_routines WHERE routine_id = ?",
                (routine_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return {"ok": False, "error": f"Routine {routine_id} not found"}

            new_success = row["success_count"] + (1 if success else 0)
            new_failure = row["failure_count"] + (0 if success else 1)
            new_status = row["probation_status"]

            if new_failure >= 3:
                new_status = "quarantined"
            elif new_success >= 3 and row["risk_level"] == "low":
                new_status = "promoted"

            await db.execute(
                """
                UPDATE adaptive_routines
                SET success_count = ?, failure_count = ?, probation_status = ?,
                    last_run_at = ?, updated_at = ?
                WHERE routine_id = ?
                """,
                (new_success, new_failure, new_status, now, now, routine_id),
            )
            await db.commit()

            cursor = await db.execute(
                "SELECT * FROM adaptive_routines WHERE routine_id = ?",
                (routine_id,),
            )
            updated = await cursor.fetchone()
            return self._routine_row_to_dict(updated)  # type: ignore[arg-type]

    @staticmethod
    def _routine_row_to_dict(row: aiosqlite.Row) -> dict:
        return {
            "routine_id": row["routine_id"],
            "title": row["title"],
            "trigger_pattern": row["trigger_pattern"],
            "action_template": row["action_template"],
            "risk_level": row["risk_level"],
            "autonomy_class": row["autonomy_class"],
            "probation_status": row["probation_status"],
            "success_count": row["success_count"],
            "failure_count": row["failure_count"],
            "last_run_at": row["last_run_at"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ------------------------------------------------------------------
    # Feature 3: Learning Diff Review Actions
    # ------------------------------------------------------------------

    async def review_learning_diff(
        self, cycle_id: str, action: str, reviewer: str = "desktop-user", reason: str = ""
    ) -> dict:
        """Apply review action (approve|reject|probation) to a learning diff."""
        status_map = {
            "approve": "approved",
            "reject": "rejected",
            "probation": "sent_to_probation",
        }
        new_status = status_map.get(action)
        if not new_status:
            return {"ok": False, "error": f"Invalid action '{action}'. Use approve|reject|probation."}

        now = time.time()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM adaptive_learning_diffs WHERE cycle_id = ?",
                (cycle_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return {"ok": False, "error": f"Learning diff {cycle_id} not found"}

            payload = json.loads(row["payload_json"])
            payload["approval_status"] = new_status
            payload["reviewed_by"] = reviewer
            payload["review_reason"] = reason
            payload["reviewed_at"] = now

            await db.execute(
                """
                UPDATE adaptive_learning_diffs
                SET payload_json = ?, updated_at = ?
                WHERE cycle_id = ?
                """,
                (json.dumps(payload), now, cycle_id),
            )
            await db.commit()

        return {"ok": True, "cycle_id": cycle_id, "action": action, "approval_status": new_status}

    async def list_pending_reviews(self) -> list[dict]:
        """List learning diffs that need review (approval_status == 'needs_review')."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM adaptive_learning_diffs ORDER BY created_at DESC"
            )
            rows = await cursor.fetchall()
            results: list[dict] = []
            for row in rows:
                payload = json.loads(row["payload_json"])
                if payload.get("approval_status") == "needs_review":
                    results.append(payload)
            return results

    # ------------------------------------------------------------------
    # Feature 4: Active Project Context Switching
    # ------------------------------------------------------------------

    async def activate_project(
        self,
        project_id: str,
        memory_snapshot: dict | None = None,
        skill_snapshot: list[str] | None = None,
    ) -> dict:
        """Activate a project context, suspending the current one. Returns activation result."""
        now = time.time()
        restored_memory = False
        restored_skills: list[str] = []

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row

            # Suspend any currently active project
            cursor = await db.execute(
                "SELECT * FROM adaptive_project_sessions WHERE status = 'active' LIMIT 1"
            )
            active = await cursor.fetchone()
            if active and active["project_id"] != project_id:
                await db.execute(
                    """
                    UPDATE adaptive_project_sessions
                    SET status = 'suspended', suspended_at = ?, updated_at = ?
                    WHERE session_id = ?
                    """,
                    (now, now, active["session_id"]),
                )

            # Check for an existing session for the target project
            cursor = await db.execute(
                "SELECT * FROM adaptive_project_sessions WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            )
            existing = await cursor.fetchone()

            if existing:
                # Reactivate existing session, restoring saved state
                prev_memory = json.loads(existing["memory_snapshot_json"] or "null")
                prev_skills = json.loads(existing["skill_snapshot_json"] or "[]")
                restored_memory = prev_memory is not None
                restored_skills = prev_skills if isinstance(prev_skills, list) else []

                new_memory = json.dumps(memory_snapshot) if memory_snapshot is not None else existing["memory_snapshot_json"]
                new_skills = json.dumps(skill_snapshot) if skill_snapshot is not None else existing["skill_snapshot_json"]

                await db.execute(
                    """
                    UPDATE adaptive_project_sessions
                    SET status = 'active', activated_at = ?, suspended_at = NULL,
                        memory_snapshot_json = ?, skill_snapshot_json = ?, updated_at = ?
                    WHERE session_id = ?
                    """,
                    (now, new_memory, new_skills, now, existing["session_id"]),
                )
            else:
                # Create a new session
                session_id = f"sess-{uuid.uuid4().hex[:12]}"
                await db.execute(
                    """
                    INSERT INTO adaptive_project_sessions
                        (session_id, project_id, status, memory_snapshot_json,
                         skill_snapshot_json, activated_at, updated_at)
                    VALUES (?, ?, 'active', ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        project_id,
                        json.dumps(memory_snapshot) if memory_snapshot else None,
                        json.dumps(skill_snapshot) if skill_snapshot else None,
                        now,
                        now,
                    ),
                )

            await db.commit()

        return {
            "ok": True,
            "project_id": project_id,
            "status": "active",
            "restored_memory": restored_memory,
            "restored_skills": restored_skills,
        }

    async def suspend_project(self, project_id: str) -> dict:
        """Suspend a project context, saving current state. Returns suspension result."""
        now = time.time()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM adaptive_project_sessions WHERE project_id = ? AND status = 'active' LIMIT 1",
                (project_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return {"ok": False, "error": f"No active session for project {project_id}"}

            await db.execute(
                """
                UPDATE adaptive_project_sessions
                SET status = 'suspended', suspended_at = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (now, now, row["session_id"]),
            )
            await db.commit()

        return {"ok": True, "project_id": project_id, "status": "suspended"}

    async def get_active_project(self) -> dict | None:
        """Get the currently active project session."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM adaptive_project_sessions WHERE status = 'active' LIMIT 1"
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return self._session_row_to_dict(row)

    async def list_project_sessions(self) -> list[dict]:
        """List all project sessions."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM adaptive_project_sessions ORDER BY updated_at DESC"
            )
            rows = await cursor.fetchall()
            return [self._session_row_to_dict(row) for row in rows]

    async def list_project_profiles(self, limit: int = 50) -> list[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT payload_json FROM adaptive_project_profiles ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
        items: list[dict] = []
        for row in rows:
            try:
                items.append(json.loads(row["payload_json"]))
            except Exception:
                continue
        return items

    @staticmethod
    def _session_row_to_dict(row: aiosqlite.Row) -> dict:
        return {
            "session_id": row["session_id"],
            "project_id": row["project_id"],
            "status": row["status"],
            "memory_snapshot": json.loads(row["memory_snapshot_json"] or "null"),
            "skill_snapshot": json.loads(row["skill_snapshot_json"] or "[]"),
            "activated_at": row["activated_at"],
            "suspended_at": row["suspended_at"],
            "updated_at": row["updated_at"],
        }

    # ------------------------------------------------------------------
    # Feature 5: Teaching Artifacts / Playbook
    # ------------------------------------------------------------------

    async def record_teaching_artifact(
        self,
        *,
        source_id: str,
        title: str,
        transcript: str,
        task_prompt: str = "",
        result_text: str = "",
        tags: list[str] | None = None,
    ) -> dict:
        if not self._initialized:
            await self.initialize()
        now = time.time()
        entry = TeachingArtifact(
            entry_id=f"playbook-{uuid.uuid4().hex[:12]}",
            title=title,
            transcript=transcript[:12000],
            template_candidate=task_prompt[:2000],
            workflow_candidate={
                "title": title,
                "source_id": source_id,
                "steps_hint": transcript[:800],
            },
            skill_candidate={
                "name": f"skill-{hashlib.sha1(title.encode('utf-8')).hexdigest()[:8]}",
                "summary": result_text[:1200],
                "capability_metadata": {
                    "source_id": source_id,
                    "teaching_mode": True,
                    "review_required": True,
                },
            },
            tags=list(tags or []),
            promotion_state="pending",
            created_at=now,
        ).to_dict() | {"source_id": source_id}
        await self._persist_records("adaptive_playbook_entries", "entry_id", [entry])
        return entry

    async def list_playbook_entries(self, limit: int = 20) -> list[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT payload_json FROM adaptive_playbook_entries ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
        items: list[dict] = []
        for row in rows:
            try:
                items.append(json.loads(row["payload_json"]))
            except Exception:
                continue
        return items

    # ------------------------------------------------------------------
    # Feature 6: Skill Graph / Sharing / Multimodal Ingestion
    # ------------------------------------------------------------------

    def build_skill_graph(self, manifests: list[dict[str, Any]]) -> dict[str, Any]:
        names = {str(item.get("name") or "") for item in manifests}
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for item in manifests:
            name = str(item.get("name") or "")
            nodes.append({
                "id": name,
                "label": name,
                "risk_level": str(item.get("risk_level") or "low"),
                "tools": list(item.get("tools", []) or []),
                "multimodal_capabilities": list(item.get("multimodal_capabilities", []) or []),
            })
            for dep in list(item.get("dependencies", []) or []):
                edges.append({"source": name, "target": str(dep), "status": "present" if dep in names else "missing"})
            composition = item.get("composition_metadata", {}) if isinstance(item.get("composition_metadata"), dict) else {}
            for composed in list(composition.get("composes", []) or []):
                edges.append({"source": name, "target": str(composed), "status": "composed"})
        return {"nodes": nodes, "edges": edges}

    async def export_distilled_patterns(self) -> dict:
        return {
            "ok": True,
            "project_sessions": await self.list_project_sessions(),
            "routines": await self.list_routines(limit=100),
            "playbook_entries": await self.list_playbook_entries(limit=100),
            "pending_reviews": await self.list_pending_reviews(),
        }

    async def import_distilled_patterns(self, payload: dict[str, Any]) -> dict:
        imported = 0
        playbooks = payload.get("playbook_entries", [])
        if isinstance(playbooks, list):
            await self._persist_records("adaptive_playbook_entries", "entry_id", playbooks)
            imported += len(playbooks)
        return {"ok": True, "imported": imported}

    async def ingest_multimodal_artifact(self, kind: str, payload: dict[str, Any]) -> dict:
        now = time.time()
        artifact = {
            "artifact_id": f"artifact-{uuid.uuid4().hex[:12]}",
            "kind": kind,
            "payload": payload,
            "created_at": now,
        }
        await self._persist_records("adaptive_playbook_entries", "entry_id", [{
            "entry_id": artifact["artifact_id"],
            "title": f"Multimodal {kind}",
            "transcript": json.dumps(payload)[:4000],
            "template_candidate": "",
            "skill_candidate": {},
            "tags": [kind, "multimodal"],
            "created_at": now,
        }])
        return {"ok": True, "artifact": artifact}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_snapshot_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_paths = payload.get("file_paths", [])
        file_paths = [
            str(item).strip()
            for item in (source_paths if isinstance(source_paths, list) else [])
            if str(item).strip()
        ]
        snapshot_files: list[dict[str, Any]] = []
        skipped_paths: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_path in file_paths:
            resolved = self._resolve_snapshot_path(raw_path)
            if resolved is None:
                skipped_paths.append({
                    "path": raw_path,
                    "status": "skipped",
                    "reason": "outside_workspace",
                })
                continue
            dedupe_key = str(resolved)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            snapshot_files.append(self._snapshot_file_entry(resolved))
        return {
            **payload,
            "file_paths": [entry["path"] for entry in snapshot_files],
            "file_entries": snapshot_files,
            "skipped_paths": skipped_paths,
            "workspace_root": str(self._workspace_root),
            "captured_at": time.time(),
        }

    def _resolve_snapshot_path(self, raw_path: str | Path) -> Path | None:
        candidate = Path(str(raw_path)).expanduser()
        try:
            resolved = candidate.resolve() if candidate.is_absolute() else (self._workspace_root / candidate).resolve()
            resolved.relative_to(self._workspace_root)
        except Exception:
            return None
        return resolved

    def _snapshot_file_entry(self, path: Path) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "path": str(path),
            "relative_path": str(path.relative_to(self._workspace_root)),
            "exists": path.exists(),
            "kind": "file",
        }
        if not path.exists():
            return entry
        if path.is_dir():
            entry["kind"] = "directory"
            return entry
        data = path.read_bytes()
        entry["size_bytes"] = len(data)
        entry["sha1"] = hashlib.sha1(data).hexdigest()
        try:
            entry["encoding"] = "utf-8"
            entry["content_text"] = data.decode("utf-8")
        except UnicodeDecodeError:
            entry["encoding"] = "base64"
            entry["content_base64"] = base64.b64encode(data).decode("ascii")
        return entry

    async def _restore_snapshot_payload(self, snapshot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        entries = payload.get("file_entries", [])
        if not isinstance(entries, list) or not entries:
            return {
                "ok": False,
                "snapshot_id": snapshot_id,
                "status": "failed",
                "error": "Snapshot does not contain restorable file entries",
                "restored_paths": [],
                "deleted_paths": [],
                "skipped_paths": payload.get("skipped_paths", []),
            }

        restored_paths: list[str] = []
        deleted_paths: list[str] = []
        skipped_paths: list[dict[str, Any]] = list(payload.get("skipped_paths", [])) if isinstance(payload.get("skipped_paths"), list) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            relative_path = str(entry.get("relative_path") or "").strip()
            raw_path = str(entry.get("path") or "").strip()
            target = self._resolve_snapshot_path(relative_path or raw_path)
            if target is None:
                skipped_paths.append({
                    "path": raw_path or relative_path,
                    "status": "skipped",
                    "reason": "outside_workspace",
                })
                continue
            if entry.get("kind") == "directory":
                target.mkdir(parents=True, exist_ok=True)
                restored_paths.append(str(target))
                continue
            if not bool(entry.get("exists")):
                if target.exists() and target.is_file():
                    target.unlink()
                    deleted_paths.append(str(target))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            encoding = str(entry.get("encoding") or "utf-8")
            if encoding == "base64":
                raw = base64.b64decode(str(entry.get("content_base64") or "").encode("ascii"))
                target.write_bytes(raw)
            else:
                raw = str(entry.get("content_text") or "").encode("utf-8")
                target.write_bytes(raw)
            restored_paths.append(str(target))

        return {
            "ok": True,
            "snapshot_id": snapshot_id,
            "status": "completed",
            "restored_paths": restored_paths,
            "deleted_paths": deleted_paths,
            "skipped_paths": skipped_paths,
            "restored_count": len(restored_paths),
            "deleted_count": len(deleted_paths),
        }

    async def _attach_snapshot_to_receipts(
        self,
        db: aiosqlite.Connection,
        task_id: str,
        snapshot_id: str,
        now: float,
    ) -> None:
        if not task_id:
            return
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT receipt_id, payload_json FROM adaptive_change_receipts WHERE task_id = ?",
            (task_id,),
        )
        rows = await cursor.fetchall()
        for row in rows:
            payload = json.loads(row["payload_json"] or "{}")
            payload["snapshot_id"] = snapshot_id
            payload["rollback_available"] = True
            resource_entries = payload.get("resource_entries")
            if isinstance(resource_entries, list):
                for entry in resource_entries:
                    if not isinstance(entry, dict):
                        continue
                    if str(entry.get("resource_type") or "") == "file":
                        entry["rollback_status"] = "ready"
                payload["resource_entries"] = resource_entries
            await db.execute(
                """
                UPDATE adaptive_change_receipts
                SET payload_json = ?, updated_at = ?
                WHERE receipt_id = ?
                """,
                (json.dumps(payload), now, row["receipt_id"]),
            )

    async def _persist_records(self, table: str, id_field: str, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        now = time.time()
        async with aiosqlite.connect(self._db_path) as db:
            for record in records:
                record_id = str(record.get(id_field) or "").strip()
                if not record_id:
                    continue
                if table == "adaptive_suggestions":
                    await db.execute(
                        f"""
                        INSERT INTO {table} ({id_field}, category, payload_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT({id_field}) DO UPDATE SET
                            category = excluded.category,
                            payload_json = excluded.payload_json,
                            updated_at = excluded.updated_at
                        """,
                        (
                            record_id,
                            str(record.get("category") or "general"),
                            json.dumps(record),
                            float(record.get("created_at") or now),
                            now,
                        ),
                    )
                    continue
                if table == "adaptive_change_receipts":
                    await db.execute(
                        f"""
                        INSERT INTO {table} ({id_field}, task_id, payload_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT({id_field}) DO UPDATE SET
                            task_id = excluded.task_id,
                            payload_json = excluded.payload_json,
                            updated_at = excluded.updated_at
                        """,
                        (
                            record_id,
                            str(record.get("task_id") or ""),
                            json.dumps(record),
                            float(record.get("created_at") or now),
                            now,
                        ),
                    )
                    continue
                await db.execute(
                    f"""
                    INSERT INTO {table} ({id_field}, payload_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT({id_field}) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        record_id,
                        json.dumps(record),
                        float(record.get("created_at") or now),
                        now,
                    ),
                )
            await db.commit()

    @staticmethod
    def _top_repeated(items: list[str]) -> dict[str, Any] | None:
        counts: dict[str, int] = {}
        for item in items:
            counts[item] = counts.get(item, 0) + 1
        if not counts:
            return None
        name, count = max(counts.items(), key=lambda pair: pair[1])
        if count < 2:
            return None
        return {"name": name, "count": count}
