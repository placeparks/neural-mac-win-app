"""
Procedural Memory — Learned workflow patterns.

The agent remembers HOW to do things, not just what happened.
When a multi-step task succeeds, the steps are captured as a Procedure.
Next time a similar request comes in, the agent can replay or adapt
the procedure instead of reasoning from scratch.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

from neuralclaw.bus.neural_bus import EventType, NeuralBus


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ProcedureStep:
    """A single step in a procedure."""
    action: str          # e.g. "web_search", "create_event"
    description: str     # Human-readable description
    parameters: dict[str, Any] = field(default_factory=dict)
    expected_output: str = ""


@dataclass
class Procedure:
    """A learned multi-step workflow."""
    id: str
    name: str
    description: str
    trigger_patterns: list[str]    # Patterns that activate this procedure
    steps: list[ProcedureStep]
    success_count: int = 0
    failure_count: int = 0
    last_used: float = 0.0
    created_at: float = field(default_factory=time.time)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    @property
    def total_uses(self) -> int:
        return self.success_count + self.failure_count


# ---------------------------------------------------------------------------
# Procedural Memory Store
# ---------------------------------------------------------------------------

class ProceduralMemory:
    """
    SQLite-backed procedural memory.

    Stores learned workflows as Procedures with trigger patterns,
    step sequences, and success tracking for continuous improvement.
    """

    def __init__(self, db_path: str, bus: NeuralBus | None = None) -> None:
        self._db_path = db_path
        self._bus = bus
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS procedures (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                trigger_patterns_json TEXT DEFAULT '[]',
                steps_json TEXT DEFAULT '[]',
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                last_used REAL DEFAULT 0,
                created_at REAL DEFAULT (unixepoch('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_proc_name ON procedures(name);
            CREATE INDEX IF NOT EXISTS idx_proc_last_used ON procedures(last_used);
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def store_procedure(
        self,
        name: str,
        description: str,
        trigger_patterns: list[str],
        steps: list[ProcedureStep],
    ) -> str:
        """Store a new learned procedure."""
        assert self._db is not None
        proc_id = uuid.uuid4().hex[:10]

        steps_data = [
            {"action": s.action, "description": s.description,
             "parameters": s.parameters, "expected_output": s.expected_output}
            for s in steps
        ]

        await self._db.execute(
            """INSERT INTO procedures
               (id, name, description, trigger_patterns_json, steps_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (proc_id, name, description,
             json.dumps(trigger_patterns), json.dumps(steps_data), time.time()),
        )
        await self._db.commit()

        if self._bus:
            await self._bus.publish(
                EventType.PROCEDURE_LEARNED,
                {"id": proc_id, "name": name, "steps": len(steps)},
                source="memory.procedural",
            )

        return proc_id

    async def find_matching(self, query: str) -> list[Procedure]:
        """Find procedures whose trigger patterns match the query."""
        assert self._db is not None
        query_lower = query.lower()

        rows = await self._db.execute_fetchall(
            "SELECT * FROM procedures ORDER BY success_count DESC",
        )

        matches: list[Procedure] = []
        for row in rows:
            triggers = json.loads(row[3])
            for pattern in triggers:
                if pattern.lower() in query_lower or query_lower in pattern.lower():
                    matches.append(self._row_to_procedure(row))
                    break

        return matches

    async def record_outcome(self, proc_id: str, success: bool) -> None:
        """Record the outcome of a procedure execution."""
        assert self._db is not None
        col = "success_count" if success else "failure_count"
        await self._db.execute(
            f"UPDATE procedures SET {col} = {col} + 1, last_used = ? WHERE id = ?",
            (time.time(), proc_id),
        )
        await self._db.commit()

    async def get_all(self, limit: int = 50) -> list[Procedure]:
        """Get all stored procedures."""
        assert self._db is not None
        rows = await self._db.execute_fetchall(
            "SELECT * FROM procedures ORDER BY last_used DESC LIMIT ?", (limit,),
        )
        return [self._row_to_procedure(r) for r in rows]

    async def delete(self, proc_id: str) -> None:
        """Delete a procedure."""
        assert self._db is not None
        await self._db.execute("DELETE FROM procedures WHERE id = ?", (proc_id,))
        await self._db.commit()

    async def count(self) -> int:
        """Total number of stored procedures."""
        assert self._db is not None
        row = await self._db.execute_fetchall("SELECT COUNT(*) FROM procedures")
        return row[0][0] if row else 0

    async def clear(self) -> int:
        """Delete all procedures. Returns count deleted."""
        assert self._db is not None
        row = await self._db.execute_fetchall("SELECT COUNT(*) FROM procedures")
        count = row[0][0] if row else 0
        await self._db.execute("DELETE FROM procedures")
        await self._db.commit()
        return count

    def _row_to_procedure(self, row: tuple) -> Procedure:
        steps_data = json.loads(row[4])
        steps = [
            ProcedureStep(
                action=s["action"], description=s["description"],
                parameters=s.get("parameters", {}),
                expected_output=s.get("expected_output", ""),
            )
            for s in steps_data
        ]
        return Procedure(
            id=row[0], name=row[1], description=row[2],
            trigger_patterns=json.loads(row[3]),
            steps=steps,
            success_count=row[5], failure_count=row[6],
            last_used=row[7], created_at=row[8],
        )
