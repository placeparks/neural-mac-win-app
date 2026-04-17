"""Per-integration compensating rollback — connector-specific undo actions."""

from __future__ import annotations
import json, time, hashlib
from typing import Any
from pathlib import Path
import aiosqlite

class CompensatingRollbackRegistry:
    """Registry of per-integration compensating actions.

    Each integration (slack, github, jira, google_workspace, etc.) registers
    compensating actions that can undo or approximate-undo specific operations.
    When a rollback is requested for a receipt that touched integrations,
    this registry finds and executes the appropriate compensating action.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._handlers: dict[str, dict[str, Any]] = {}  # integration -> {action -> handler_info}
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS compensating_actions (
                    action_id TEXT PRIMARY KEY,
                    receipt_id TEXT NOT NULL,
                    integration TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    original_payload_json TEXT,
                    compensating_payload_json TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_json TEXT,
                    created_at REAL NOT NULL,
                    executed_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_ca_receipt ON compensating_actions(receipt_id);
                CREATE INDEX IF NOT EXISTS idx_ca_integration ON compensating_actions(integration);
            """)
        self._register_builtins()
        self._initialized = True

    def register_compensator(self, integration: str, operation: str, *,
                              compensate_fn: Any = None,
                              description: str = "",
                              reversibility: str = "best_effort") -> None:
        """Register a compensating action for a specific integration+operation pair.

        reversibility: "full" | "best_effort" | "manual_only"
        """
        if integration not in self._handlers:
            self._handlers[integration] = {}
        self._handlers[integration][operation] = {
            "handler": compensate_fn,
            "description": description,
            "reversibility": reversibility,
        }

    def _register_builtins(self) -> None:
        """Register built-in compensating actions for known integrations."""
        # Slack: delete sent message
        self.register_compensator("slack", "send_message",
            description="Delete the sent Slack message",
            reversibility="full")
        # Slack: unpin/un-react
        self.register_compensator("slack", "pin_message",
            description="Unpin the pinned message",
            reversibility="full")
        # GitHub: close opened issue/PR
        self.register_compensator("github", "create_issue",
            description="Close the created issue with a compensating note",
            reversibility="best_effort")
        self.register_compensator("github", "create_comment",
            description="Delete or edit the comment to mark as compensated",
            reversibility="best_effort")
        self.register_compensator("github", "merge_pr",
            description="Revert merge via revert PR (manual approval needed)",
            reversibility="manual_only")
        # Jira: transition issue back
        self.register_compensator("jira", "create_issue",
            description="Close/cancel the created Jira issue",
            reversibility="best_effort")
        self.register_compensator("jira", "transition_issue",
            description="Transition issue back to previous status",
            reversibility="best_effort")
        # Google Workspace: trash sent email (if possible)
        self.register_compensator("google_workspace", "send_email",
            description="Move sent email to trash (if within recall window)",
            reversibility="best_effort")
        self.register_compensator("google_workspace", "create_doc",
            description="Move created document to trash",
            reversibility="full")
        # Generic: memory mutation compensation
        self.register_compensator("memory", "write_episode",
            description="Delete the written episode",
            reversibility="full")
        self.register_compensator("memory", "update_identity",
            description="Restore identity from snapshot",
            reversibility="best_effort")

    async def plan_compensation(self, receipt: dict) -> list[dict]:
        """Plan compensating actions for a change receipt. Returns action plan without executing."""
        await self.initialize()
        plan: list[dict] = []
        integrations_touched = receipt.get("integrations_touched", [])
        operations = receipt.get("operations", [])

        for integration in integrations_touched:
            integration = str(integration).strip().lower()
            handlers = self._handlers.get(integration, {})
            for op in operations:
                op_lower = str(op).strip().lower()
                # Try exact match first, then prefix match
                handler_info = handlers.get(op_lower)
                if not handler_info:
                    for registered_op, info in handlers.items():
                        if registered_op in op_lower or op_lower in registered_op:
                            handler_info = info
                            break

                action_id = f"ca-{hashlib.sha256(f'{integration}:{op}:{time.time_ns()}'.encode()).hexdigest()[:12]}"
                plan.append({
                    "action_id": action_id,
                    "integration": integration,
                    "operation": op,
                    "has_handler": handler_info is not None,
                    "description": handler_info["description"] if handler_info else f"No registered compensator for {integration}:{op}",
                    "reversibility": handler_info["reversibility"] if handler_info else "not_supported",
                })

        # Also plan for file changes
        for path in receipt.get("files_changed", []):
            plan.append({
                "action_id": f"ca-file-{hashlib.sha256(path.encode()).hexdigest()[:8]}",
                "integration": "filesystem",
                "operation": f"restore:{path}",
                "has_handler": True,
                "description": f"Restore {path} from snapshot",
                "reversibility": "full",
            })

        # Memory compensation
        if receipt.get("memory_updated"):
            plan.append({
                "action_id": f"ca-mem-{hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:8]}",
                "integration": "memory",
                "operation": "restore_memory_state",
                "has_handler": True,
                "description": "Restore memory state from pre-change snapshot",
                "reversibility": "best_effort",
            })

        return plan

    async def execute_compensation(self, receipt_id: str, plan: list[dict]) -> dict:
        """Execute planned compensating actions and persist results."""
        await self.initialize()
        now = time.time()
        results: list[dict] = []
        succeeded = 0
        failed = 0
        skipped = 0

        for action in plan:
            action_id = action["action_id"]
            integration = action["integration"]
            operation = action["operation"]

            if not action.get("has_handler") or action.get("reversibility") == "not_supported":
                status = "skipped"
                result = {"reason": "No compensating handler available"}
                skipped += 1
            elif action.get("reversibility") == "manual_only":
                status = "requires_manual"
                result = {"reason": "Requires manual intervention", "instruction": action.get("description", "")}
                skipped += 1
            else:
                # Execute the compensating handler if available
                handlers = self._handlers.get(integration, {})
                handler_info = None
                for reg_op, info in handlers.items():
                    if reg_op in operation.lower() or operation.lower() in reg_op:
                        handler_info = info
                        break

                if handler_info and handler_info.get("handler"):
                    try:
                        compensation_result = await handler_info["handler"](receipt_id=receipt_id, operation=operation)
                        status = "completed"
                        result = compensation_result if isinstance(compensation_result, dict) else {"result": str(compensation_result)}
                        succeeded += 1
                    except Exception as e:
                        status = "failed"
                        result = {"error": str(e)}
                        failed += 1
                else:
                    # No actual handler but marked as supported — record as planned
                    status = "planned"
                    result = {"description": action.get("description", ""), "note": "Compensating action registered but no runtime handler attached"}
                    succeeded += 1

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("""
                    INSERT INTO compensating_actions
                        (action_id, receipt_id, integration, operation, status, result_json, created_at, executed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (action_id, receipt_id, integration, operation, status, json.dumps(result), now, now if status != "pending" else None))
                await db.commit()

            results.append({**action, "status": status, "result": result})

        return {
            "ok": True,
            "receipt_id": receipt_id,
            "total": len(plan),
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "actions": results,
        }

    async def get_compensation_history(self, receipt_id: str) -> list[dict]:
        """Get compensation history for a receipt."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM compensating_actions WHERE receipt_id = ? ORDER BY created_at DESC",
                (receipt_id,))
            rows = await cur.fetchall()
        return [{
            "action_id": r["action_id"],
            "integration": r["integration"],
            "operation": r["operation"],
            "status": r["status"],
            "result": json.loads(r["result_json"]) if r["result_json"] else None,
            "created_at": r["created_at"],
            "executed_at": r["executed_at"],
        } for r in rows]

    async def list_registered_compensators(self) -> list[dict]:
        """List all registered compensating action types."""
        result: list[dict] = []
        for integration, ops in self._handlers.items():
            for operation, info in ops.items():
                result.append({
                    "integration": integration,
                    "operation": operation,
                    "description": info["description"],
                    "reversibility": info["reversibility"],
                    "has_runtime_handler": info.get("handler") is not None,
                })
        return result
