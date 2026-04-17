"""
Workspace Coordinator — Multi-agent directory claim/release system.

Prevents agents from stepping on each other's work by tracking which
agent has claimed which filesystem path. Uses SQLite with WAL mode
so multiple processes on the same machine can share state.

Usage:
    coordinator = WorkspaceCoordinator(db_path)
    await coordinator.initialize()

    claim = await coordinator.claim("/path/to/dir", "agent-bob", purpose="scaffolding")
    if claim:
        # We own it — do the work
        await coordinator.release("/path/to/dir", "agent-bob")
    else:
        existing = await coordinator.get_claim("/path/to/dir")
        # Someone else has it — check existing.agent_name
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import aiosqlite


@dataclass
class WorkspaceClaim:
    """An active directory lock held by one agent."""

    claim_id: str
    agent_name: str
    path: str
    purpose: str
    claimed_at: float
    expires_at: float  # 0 = never expires
    active: bool = True


class WorkspaceCoordinator:
    """
    SQLite-backed directory claim/release coordinator.

    One active claim per path at a time. Claims are scoped to an agent_name,
    can optionally expire (ttl_seconds > 0), and are released automatically
    when an agent shuts down via release_all_for_agent().
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS workspace_claims (
                claim_id    TEXT PRIMARY KEY,
                agent_name  TEXT NOT NULL,
                path        TEXT NOT NULL,
                purpose     TEXT DEFAULT '',
                claimed_at  REAL NOT NULL,
                expires_at  REAL DEFAULT 0,
                active      INTEGER DEFAULT 1
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uix_path_active
                ON workspace_claims(path, active)
                WHERE active = 1;
            CREATE INDEX IF NOT EXISTS idx_agent_active
                ON workspace_claims(agent_name, active);
        """)
        await self._db.commit()

    # ------------------------------------------------------------------
    # Core claim / release
    # ------------------------------------------------------------------

    async def claim(
        self,
        path: str,
        agent_name: str,
        purpose: str = "",
        ttl_seconds: float = 0,
    ) -> WorkspaceClaim | None:
        """
        Attempt to claim *path* for *agent_name*.

        Returns the new WorkspaceClaim on success, or None if another agent
        already holds an active claim on this path.
        """
        assert self._db is not None
        path = _normalise(path)
        now = time.time()
        expires_at = now + ttl_seconds if ttl_seconds > 0 else 0.0

        # First expire any stale claims so they don't block us.
        await self._expire_path(path, now)

        existing = await self.get_claim(path)
        if existing is not None:
            # Path is claimed — caller should inspect existing.agent_name
            return None

        claim_id = str(uuid.uuid4())
        try:
            await self._db.execute(
                """
                INSERT INTO workspace_claims
                    (claim_id, agent_name, path, purpose, claimed_at, expires_at, active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (claim_id, agent_name, path, purpose, now, expires_at),
            )
            await self._db.commit()
        except aiosqlite.IntegrityError:
            # Race — another agent won
            return None

        return WorkspaceClaim(
            claim_id=claim_id,
            agent_name=agent_name,
            path=path,
            purpose=purpose,
            claimed_at=now,
            expires_at=expires_at,
        )

    async def release(self, path: str, agent_name: str) -> bool:
        """
        Release the claim on *path* if held by *agent_name*.

        Returns True if released, False if not the owner or not claimed.
        """
        assert self._db is not None
        path = _normalise(path)
        cursor = await self._db.execute(
            """
            UPDATE workspace_claims
               SET active = 0
             WHERE path = ? AND agent_name = ? AND active = 1
            """,
            (path, agent_name),
        )
        await self._db.commit()
        return (cursor.rowcount or 0) > 0

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_claim(self, path: str) -> WorkspaceClaim | None:
        """Return the active claim for *path*, or None."""
        assert self._db is not None
        path = _normalise(path)
        async with self._db.execute(
            """
            SELECT claim_id, agent_name, path, purpose, claimed_at, expires_at
              FROM workspace_claims
             WHERE path = ? AND active = 1
            """,
            (path,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return _row_to_claim(row)

    async def get_claims_for_agent(self, agent_name: str) -> list[WorkspaceClaim]:
        """All active claims held by *agent_name*."""
        assert self._db is not None
        async with self._db.execute(
            """
            SELECT claim_id, agent_name, path, purpose, claimed_at, expires_at
              FROM workspace_claims
             WHERE agent_name = ? AND active = 1
             ORDER BY claimed_at
            """,
            (agent_name,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_claim(r) for r in rows]

    async def list_all_claims(self) -> list[WorkspaceClaim]:
        """All currently active claims (across all agents)."""
        assert self._db is not None
        async with self._db.execute(
            """
            SELECT claim_id, agent_name, path, purpose, claimed_at, expires_at
              FROM workspace_claims
             WHERE active = 1
             ORDER BY claimed_at
            """
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_claim(r) for r in rows]

    # ------------------------------------------------------------------
    # Bulk release / maintenance
    # ------------------------------------------------------------------

    async def release_all_for_agent(self, agent_name: str) -> int:
        """
        Release every active claim held by *agent_name*.
        Called on agent shutdown. Returns the number of claims released.
        """
        assert self._db is not None
        cursor = await self._db.execute(
            "UPDATE workspace_claims SET active = 0 WHERE agent_name = ? AND active = 1",
            (agent_name,),
        )
        await self._db.commit()
        return cursor.rowcount or 0

    async def cleanup_expired(self) -> int:
        """
        Deactivate any claims whose expires_at has passed.
        Called periodically by the gateway GC task.
        Returns the count of claims cleaned up.
        """
        assert self._db is not None
        now = time.time()
        cursor = await self._db.execute(
            """
            UPDATE workspace_claims
               SET active = 0
             WHERE active = 1 AND expires_at > 0 AND expires_at <= ?
            """,
            (now,),
        )
        await self._db.commit()
        return cursor.rowcount or 0

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _expire_path(self, path: str, now: float) -> None:
        """Silently deactivate any expired claim on *path*."""
        assert self._db is not None
        await self._db.execute(
            """
            UPDATE workspace_claims
               SET active = 0
             WHERE path = ? AND active = 1 AND expires_at > 0 AND expires_at <= ?
            """,
            (path, now),
        )
        await self._db.commit()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _normalise(path: str) -> str:
    """Strip trailing slashes for consistent key comparison."""
    return path.rstrip("/").rstrip("\\")


def _row_to_claim(row: tuple) -> WorkspaceClaim:
    claim_id, agent_name, path, purpose, claimed_at, expires_at = row
    return WorkspaceClaim(
        claim_id=claim_id,
        agent_name=agent_name,
        path=path,
        purpose=purpose,
        claimed_at=claimed_at,
        expires_at=expires_at,
        active=True,
    )
