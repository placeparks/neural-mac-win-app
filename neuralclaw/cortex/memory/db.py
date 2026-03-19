from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite


@dataclass
class DBPool:
    """
    Shared SQLite pool with one serialized writer and a small read pool.

    The public methods mirror the subset of ``aiosqlite.Connection`` used by the
    memory and observability modules so they can adopt the pool incrementally.
    """

    db_path: str
    pool_size: int = 3

    _write_conn: aiosqlite.Connection | None = field(default=None, init=False, repr=False)
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _read_pool: asyncio.Queue[aiosqlite.Connection] | None = field(default=None, init=False, repr=False)
    _initialized: bool = field(default=False, init=False, repr=False)

    async def initialize(self) -> None:
        if self._initialized:
            return

        path = Path(self.db_path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)

        self._write_conn = await aiosqlite.connect(self.db_path)
        await self._apply_pragmas(self._write_conn, query_only=False)

        self._read_pool = asyncio.Queue(maxsize=max(self.pool_size, 1))
        for _ in range(max(self.pool_size, 1)):
            conn = await aiosqlite.connect(self.db_path)
            await self._apply_pragmas(conn, query_only=True)
            await self._read_pool.put(conn)

        self._initialized = True

    async def executescript(self, script: str) -> None:
        async with self.write() as conn:
            await conn.executescript(script)

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        async with self.write() as conn:
            cursor = await conn.execute(sql, params)
            return int(cursor.rowcount or 0)

    async def executemany(self, sql: str, params_seq: list[tuple[Any, ...]]) -> None:
        async with self.write() as conn:
            await conn.executemany(sql, params_seq)

    async def execute_fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        async with self.read() as conn:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            await cursor.close()
            return rows

    async def execute_fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
        async with self.read() as conn:
            cursor = await conn.execute(sql, params)
            row = await cursor.fetchone()
            await cursor.close()
            return row

    async def commit(self) -> None:
        return None

    async def ping(self) -> bool:
        row = await self.execute_fetchone("SELECT 1")
        return bool(row and row[0] == 1)

    @asynccontextmanager
    async def write(self):
        if not self._write_conn:
            raise RuntimeError("DBPool not initialized")
        async with self._write_lock:
            yield self._write_conn
            await self._write_conn.commit()

    @asynccontextmanager
    async def read(self):
        if not self._read_pool:
            raise RuntimeError("DBPool not initialized")
        conn = await self._read_pool.get()
        try:
            yield conn
        finally:
            await self._read_pool.put(conn)

    async def close(self) -> None:
        if self._write_conn:
            await self._write_conn.close()
            self._write_conn = None
        if self._read_pool:
            while not self._read_pool.empty():
                conn = await self._read_pool.get()
                await conn.close()
            self._read_pool = None
        self._initialized = False

    async def _apply_pragmas(self, conn: aiosqlite.Connection, *, query_only: bool) -> None:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.execute("PRAGMA cache_size=-32000")
        await conn.execute(f"PRAGMA query_only={'ON' if query_only else 'OFF'}")
        await conn.commit()
