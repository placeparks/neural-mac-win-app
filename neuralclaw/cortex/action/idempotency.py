"""Idempotency — prevent duplicate side effects on retries.

NeuralClaw may retry tool calls (provider/network errors). For tools that
cause side effects (file writes, sending messages, creating calendar events),
an idempotency key ensures the action is applied at most once.

This module stores idempotency keys and their results in SQLite using a
persistent connection (same pattern as EpisodicMemory) to avoid per-op
connection overhead.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import aiosqlite


@dataclass
class IdempotencyHit:
    hit: bool
    key: str
    result: dict[str, Any] | None = None


class IdempotencyStore:
    """SQLite-backed idempotency store with persistent connection."""

    def __init__(self, db_path: str, table_name: str = "idempotency") -> None:
        self._db_path = db_path
        # Sanitize table name to prevent SQL injection (allow only alnum + underscore)
        import re
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
            raise ValueError(f"Invalid table name: {table_name!r}")
        self._table = table_name
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open persistent connection and create schema."""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {self._table} (
                key TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                result_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_{self._table}_created_at
                ON {self._table}(created_at);
            """
        )
        await self._db.commit()
        # Prune stale entries on startup (>7 days old)
        await self._prune(ttl_seconds=7 * 24 * 3600)

    async def get(self, key: str) -> IdempotencyHit:
        if not key or self._db is None:
            return IdempotencyHit(hit=False, key=key)
        cur = await self._db.execute(
            f"SELECT result_json FROM {self._table} WHERE key = ?", (key,)
        )
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return IdempotencyHit(hit=False, key=key)
        try:
            return IdempotencyHit(hit=True, key=key, result=json.loads(row[0]))
        except Exception:
            return IdempotencyHit(hit=True, key=key, result={"_raw": row[0]})

    async def set(self, key: str, result: dict[str, Any]) -> None:
        if not key or self._db is None:
            return
        payload = json.dumps(result, ensure_ascii=False)
        await self._db.execute(
            f"INSERT OR REPLACE INTO {self._table}(key, created_at, result_json) VALUES (?, ?, ?)",
            (key, time.time(), payload),
        )
        await self._db.commit()

    async def cleanup(self, ttl_seconds: float = 7 * 24 * 3600) -> int:
        """Delete old idempotency entries. Returns number deleted."""
        return await self._prune(ttl_seconds)

    async def _prune(self, ttl_seconds: float) -> int:
        if self._db is None:
            return 0
        cutoff = time.time() - ttl_seconds
        cur = await self._db.execute(
            f"DELETE FROM {self._table} WHERE created_at < ?", (cutoff,)
        )
        await self._db.commit()
        return cur.rowcount or 0

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
