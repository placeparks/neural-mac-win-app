"""
Checkpoint Store — Per-step state snapshots for multi-step reasoning.

Enables recovery from crashes during tool-use loops by persisting the
message array and iteration state at each step.  Follows the same
SQLite + aiosqlite pattern as IdempotencyStore.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import aiosqlite


@dataclass
class Checkpoint:
    """A snapshot of reasoning state at a specific step."""
    checkpoint_id: str
    session_id: str
    step_index: int
    messages: list[dict[str, Any]]
    tool_calls_made: int
    created_at: float


class CheckpointStore:
    """SQLite-backed checkpoint store with persistent connection."""

    _PRUNE_TTL = 24 * 3600  # 24 hours

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open persistent connection and create schema."""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                messages_json TEXT NOT NULL,
                tool_calls_made INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_checkpoints_session
                ON checkpoints(session_id, step_index);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_created_at
                ON checkpoints(created_at);
            """
        )
        await self._db.commit()
        # Prune stale entries on startup
        await self._prune(self._PRUNE_TTL)

    async def save(
        self,
        session_id: str,
        step_index: int,
        messages: list[dict[str, Any]],
        tool_calls_made: int = 0,
    ) -> str:
        """Save a checkpoint. Returns the checkpoint ID."""
        if self._db is None:
            return ""
        checkpoint_id = uuid.uuid4().hex[:12]
        payload = json.dumps(messages, ensure_ascii=False, default=str)
        await self._db.execute(
            "INSERT INTO checkpoints"
            "(checkpoint_id, session_id, step_index, messages_json, tool_calls_made, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (checkpoint_id, session_id, step_index, payload, tool_calls_made, time.time()),
        )
        await self._db.commit()
        # Keep only the last 3 checkpoints per session
        await self._prune_session(session_id, keep_last=3)
        return checkpoint_id

    async def latest(self, session_id: str) -> Checkpoint | None:
        """Load the most recent checkpoint for a session."""
        if self._db is None:
            return None
        cur = await self._db.execute(
            "SELECT checkpoint_id, session_id, step_index, messages_json, tool_calls_made, created_at"
            " FROM checkpoints WHERE session_id = ? ORDER BY step_index DESC LIMIT 1",
            (session_id,),
        )
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return None
        return Checkpoint(
            checkpoint_id=row[0],
            session_id=row[1],
            step_index=row[2],
            messages=json.loads(row[3]),
            tool_calls_made=row[4],
            created_at=row[5],
        )

    async def clear_session(self, session_id: str) -> int:
        """Delete all checkpoints for a session (e.g. after successful completion)."""
        if self._db is None:
            return 0
        cur = await self._db.execute(
            "DELETE FROM checkpoints WHERE session_id = ?", (session_id,),
        )
        await self._db.commit()
        return cur.rowcount or 0

    async def _prune_session(self, session_id: str, keep_last: int = 3) -> None:
        """Keep only the N most recent checkpoints for a session."""
        if self._db is None:
            return
        await self._db.execute(
            "DELETE FROM checkpoints WHERE session_id = ? AND checkpoint_id NOT IN"
            " (SELECT checkpoint_id FROM checkpoints WHERE session_id = ?"
            "  ORDER BY step_index DESC LIMIT ?)",
            (session_id, session_id, keep_last),
        )
        await self._db.commit()

    async def _prune(self, ttl_seconds: float) -> int:
        """Delete checkpoints older than TTL."""
        if self._db is None:
            return 0
        cutoff = time.time() - ttl_seconds
        cur = await self._db.execute(
            "DELETE FROM checkpoints WHERE created_at < ?", (cutoff,),
        )
        await self._db.commit()
        return cur.rowcount or 0

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
