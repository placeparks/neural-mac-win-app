"""
Shared Memory Bridge — Cross-agent memory sharing for collaborative tasks.

When agents collaborate on a task:
1. A shared task is created with a task_id and participating agents
2. Any agent can write to the shared namespace
3. All participating agents can read from it
4. Task memories are tagged with the contributing agent
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiosqlite


@dataclass
class SharedTask:
    """A collaborative task between agents."""

    task_id: str
    agents: list[str]
    status: str = "active"  # active, completed, cancelled
    created_at: float = 0.0
    closed_at: float = 0.0


@dataclass
class SharedMemoryEntry:
    """A single shared memory entry."""

    id: str
    task_id: str
    from_agent: str
    content: str
    memory_type: str  # episodic, semantic, procedural, note
    timestamp: float = 0.0


class SharedMemoryBridge:
    """
    SQLite-backed cross-agent memory sharing.

    Provides a simple protocol for agents to share memories
    when collaborating on a shared task.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS shared_tasks (
                task_id TEXT PRIMARY KEY,
                agents TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                created_at REAL,
                closed_at REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS shared_memories (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                from_agent TEXT NOT NULL,
                content TEXT NOT NULL,
                memory_type TEXT NOT NULL DEFAULT 'note',
                timestamp REAL NOT NULL,
                FOREIGN KEY (task_id) REFERENCES shared_tasks(task_id)
            );

            CREATE INDEX IF NOT EXISTS idx_shared_mem_task
                ON shared_memories(task_id);
            CREATE INDEX IF NOT EXISTS idx_shared_mem_agent
                ON shared_memories(from_agent);
        """)
        await self._db.commit()

    async def create_shared_task(
        self, agent_names: list[str], task_id: str | None = None,
    ) -> SharedTask:
        """Create a new shared task between agents."""
        assert self._db is not None
        task = SharedTask(
            task_id=task_id or uuid.uuid4().hex[:12],
            agents=agent_names,
            status="active",
            created_at=time.time(),
        )
        await self._db.execute(
            "INSERT INTO shared_tasks (task_id, agents, status, created_at) VALUES (?, ?, ?, ?)",
            (task.task_id, json.dumps(task.agents), task.status, task.created_at),
        )
        await self._db.commit()
        return task

    async def get_task(self, task_id: str) -> SharedTask | None:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT * FROM shared_tasks WHERE task_id = ?", (task_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return SharedTask(
            task_id=row[0], agents=json.loads(row[1]),
            status=row[2], created_at=row[3], closed_at=row[4] or 0.0,
        )

    async def list_active_tasks(self) -> list[SharedTask]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT * FROM shared_tasks WHERE status = 'active' ORDER BY created_at DESC",
        )
        rows = await cursor.fetchall()
        return [
            SharedTask(
                task_id=r[0], agents=json.loads(r[1]),
                status=r[2], created_at=r[3], closed_at=r[4] or 0.0,
            )
            for r in rows
        ]

    async def share_memory(
        self,
        task_id: str,
        from_agent: str,
        content: str,
        memory_type: str = "note",
    ) -> SharedMemoryEntry:
        """Write a memory to the shared task namespace."""
        assert self._db is not None
        entry = SharedMemoryEntry(
            id=uuid.uuid4().hex[:12],
            task_id=task_id,
            from_agent=from_agent,
            content=content,
            memory_type=memory_type,
            timestamp=time.time(),
        )
        await self._db.execute(
            "INSERT INTO shared_memories (id, task_id, from_agent, content, memory_type, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (entry.id, entry.task_id, entry.from_agent, entry.content, entry.memory_type, entry.timestamp),
        )
        await self._db.commit()
        return entry

    async def get_shared_memories(
        self,
        task_id: str,
        memory_type: str | None = None,
        limit: int = 100,
    ) -> list[SharedMemoryEntry]:
        """Read all shared memories for a task."""
        assert self._db is not None
        if memory_type:
            cursor = await self._db.execute(
                "SELECT * FROM shared_memories WHERE task_id = ? AND memory_type = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (task_id, memory_type, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM shared_memories WHERE task_id = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (task_id, limit),
            )
        rows = await cursor.fetchall()
        return [
            SharedMemoryEntry(
                id=r[0], task_id=r[1], from_agent=r[2],
                content=r[3], memory_type=r[4], timestamp=r[5],
            )
            for r in rows
        ]

    async def close_task(self, task_id: str) -> bool:
        """Mark a shared task as completed."""
        assert self._db is not None
        cursor = await self._db.execute(
            "UPDATE shared_tasks SET status = 'completed', closed_at = ? WHERE task_id = ?",
            (time.time(), task_id),
        )
        await self._db.commit()
        return (cursor.rowcount or 0) > 0

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
