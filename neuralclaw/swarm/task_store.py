"""
Task Store - Persistent delegated task tracking.

Stores parent and child delegation runs in SQLite so the desktop inbox can
survive restarts and expose durable task lifecycle data.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiosqlite


@dataclass
class TaskRecord:
    task_id: str
    title: str
    prompt: str
    status: str = "queued"
    provider: str = ""
    requested_model: str = ""
    effective_model: str = ""
    base_url: str = ""
    target_agents: list[str] = field(default_factory=list)
    child_task_ids: list[str] = field(default_factory=list)
    shared_task_id: str = ""
    parent_task_id: str = ""
    result: str = ""
    result_preview: str = ""
    error: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "prompt": self.prompt,
            "status": self.status,
            "provider": self.provider,
            "requested_model": self.requested_model,
            "effective_model": self.effective_model,
            "base_url": self.base_url,
            "target_agents": self.target_agents,
            "child_task_ids": self.child_task_ids,
            "shared_task_id": self.shared_task_id or None,
            "parent_task_id": self.parent_task_id or None,
            "result": self.result,
            "result_preview": self.result_preview,
            "error": self.error or None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at or None,
            "completed_at": self.completed_at or None,
            "duration_ms": self.duration_ms or None,
            "metadata": self.metadata,
        }


class TaskStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS delegation_tasks (
                task_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL,
                provider TEXT DEFAULT '',
                requested_model TEXT DEFAULT '',
                effective_model TEXT DEFAULT '',
                base_url TEXT DEFAULT '',
                target_agents TEXT DEFAULT '[]',
                child_task_ids TEXT DEFAULT '[]',
                shared_task_id TEXT DEFAULT '',
                parent_task_id TEXT DEFAULT '',
                result TEXT DEFAULT '',
                result_preview TEXT DEFAULT '',
                error TEXT DEFAULT '',
                created_at REAL,
                updated_at REAL,
                started_at REAL DEFAULT 0,
                completed_at REAL DEFAULT 0,
                duration_ms REAL DEFAULT 0,
                metadata TEXT DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_delegation_tasks_updated
                ON delegation_tasks(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_delegation_tasks_parent
                ON delegation_tasks(parent_task_id);
            CREATE INDEX IF NOT EXISTS idx_delegation_tasks_status
                ON delegation_tasks(status);
            """
        )
        await self._db.commit()

    async def create(self, record: TaskRecord) -> str:
        assert self._db is not None
        if not record.task_id:
            record.task_id = uuid.uuid4().hex[:12]
        now = time.time()
        record.created_at = record.created_at or now
        record.updated_at = record.updated_at or now
        await self._db.execute(
            """
            INSERT INTO delegation_tasks (
                task_id, title, prompt, status, provider, requested_model, effective_model,
                base_url, target_agents, child_task_ids, shared_task_id, parent_task_id,
                result, result_preview, error, created_at, updated_at, started_at,
                completed_at, duration_ms, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.task_id,
                record.title,
                record.prompt,
                record.status,
                record.provider,
                record.requested_model,
                record.effective_model,
                record.base_url,
                json.dumps(record.target_agents),
                json.dumps(record.child_task_ids),
                record.shared_task_id,
                record.parent_task_id,
                record.result,
                record.result_preview,
                record.error,
                record.created_at,
                record.updated_at,
                record.started_at,
                record.completed_at,
                record.duration_ms,
                json.dumps(record.metadata),
            ),
        )
        await self._db.commit()
        return record.task_id

    async def update(self, task_id: str, **kwargs: Any) -> bool:
        assert self._db is not None
        existing = await self.get(task_id)
        if not existing:
            return False
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = time.time()
        if "result" in kwargs and "result_preview" not in kwargs:
            kwargs["result_preview"] = str(kwargs["result"] or "").strip()[:280]
        if "started_at" in kwargs and "completed_at" in kwargs and kwargs.get("started_at") and kwargs.get("completed_at"):
            kwargs["duration_ms"] = max(0.0, (float(kwargs["completed_at"]) - float(kwargs["started_at"])) * 1000.0)

        sets: list[str] = []
        values: list[Any] = []
        for key, value in kwargs.items():
            if key in {"target_agents", "child_task_ids", "metadata"}:
                value = json.dumps(value)
            sets.append(f"{key} = ?")
            values.append(value)
        values.append(task_id)
        await self._db.execute(
            f"UPDATE delegation_tasks SET {', '.join(sets)} WHERE task_id = ?",
            tuple(values),
        )
        await self._db.commit()
        return True

    async def get(self, task_id: str) -> TaskRecord | None:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT * FROM delegation_tasks WHERE task_id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_task(row) if row else None

    async def list_all(self, limit: int = 100) -> list[TaskRecord]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT * FROM delegation_tasks ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    async def list_children(self, parent_task_id: str) -> list[TaskRecord]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT * FROM delegation_tasks WHERE parent_task_id = ? ORDER BY created_at ASC",
            (parent_task_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _row_to_task(self, row: tuple[Any, ...]) -> TaskRecord:
        return TaskRecord(
            task_id=row[0],
            title=row[1],
            prompt=row[2],
            status=row[3],
            provider=row[4],
            requested_model=row[5],
            effective_model=row[6],
            base_url=row[7],
            target_agents=json.loads(row[8]) if row[8] else [],
            child_task_ids=json.loads(row[9]) if row[9] else [],
            shared_task_id=row[10] or "",
            parent_task_id=row[11] or "",
            result=row[12] or "",
            result_preview=row[13] or "",
            error=row[14] or "",
            created_at=row[15] or 0.0,
            updated_at=row[16] or 0.0,
            started_at=row[17] or 0.0,
            completed_at=row[18] or 0.0,
            duration_ms=row[19] or 0.0,
            metadata=json.loads(row[20]) if row[20] else {},
        )
