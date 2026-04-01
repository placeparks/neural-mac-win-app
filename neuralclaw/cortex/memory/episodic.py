"""
Episodic Memory — Event-based temporal memory store.

Records events with temporal context, importance scoring, and full-text search.
Backed by SQLite + FTS5 for zero-dependency, portable storage.

Schema:
    events(id, timestamp, source, author, content, importance,
           emotional_valence, tags, embedding_json)
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiosqlite

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.memory.db import DBPool

if TYPE_CHECKING:
    from neuralclaw.cortex.memory.vector import VectorMemory


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Episode:
    """A single episodic memory entry."""
    id: str
    timestamp: float
    source: str
    author: str
    content: str
    importance: float
    emotional_valence: float  # -1.0 (negative) to 1.0 (positive)
    tags: list[str]
    access_count: int = 0
    last_accessed: float = 0.0


@dataclass
class EpisodeSearchResult:
    """Episodic memory search result with relevance score."""
    episode: Episode
    relevance: float  # 0.0 – 1.0


# ---------------------------------------------------------------------------
# Episodic Memory Store
# ---------------------------------------------------------------------------

class EpisodicMemory:
    """
    SQLite + FTS5 backed episodic memory store.

    Key features:
    - Stores events with temporal context and importance scores
    - Full-text search via FTS5
    - Temporal range queries
    - Access tracking (strengthens frequently accessed memories)
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        vector_memory: VectorMemory | None = None,
        bus: NeuralBus | None = None,
        db_pool: DBPool | None = None,
    ) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | DBPool | None = None
        self._db_pool = db_pool
        self._owns_db = db_pool is None
        self._vector_memory = vector_memory
        self._bus = bus

    async def initialize(self) -> None:
        """Initialize the database and create tables."""
        if self._db_pool:
            await self._db_pool.initialize()
            self._db = self._db_pool
        else:
            self._db = await aiosqlite.connect(self._db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA foreign_keys=ON")

        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                timestamp REAL NOT NULL,
                source TEXT NOT NULL DEFAULT 'unknown',
                author TEXT NOT NULL DEFAULT 'unknown',
                content TEXT NOT NULL,
                importance REAL NOT NULL DEFAULT 0.5,
                emotional_valence REAL NOT NULL DEFAULT 0.0,
                tags_json TEXT NOT NULL DEFAULT '[]',
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed REAL NOT NULL DEFAULT 0.0,
                created_at REAL NOT NULL DEFAULT (unixepoch('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp);
            CREATE INDEX IF NOT EXISTS idx_episodes_importance ON episodes(importance);

            CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
                content,
                content=episodes,
                content_rowid=rowid
            );

            CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
                INSERT INTO episodes_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
                INSERT INTO episodes_fts(episodes_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS episodes_au AFTER UPDATE ON episodes BEGIN
                INSERT INTO episodes_fts(episodes_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
                INSERT INTO episodes_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END;
        """)
        await self._db.commit()

    async def store(
        self,
        content: str,
        source: str = "conversation",
        author: str = "user",
        importance: float = 0.5,
        emotional_valence: float = 0.0,
        tags: list[str] | None = None,
    ) -> Episode:
        """Store a new episodic memory."""
        assert self._db is not None, "Call initialize() first"

        episode = Episode(
            id=uuid.uuid4().hex[:12],
            timestamp=time.time(),
            source=source,
            author=author,
            content=content,
            importance=importance,
            emotional_valence=emotional_valence,
            tags=tags or [],
        )

        await self._db.execute(
            """INSERT INTO episodes (id, timestamp, source, author, content,
               importance, emotional_valence, tags_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                episode.id,
                episode.timestamp,
                episode.source,
                episode.author,
                episode.content,
                episode.importance,
                episode.emotional_valence,
                json.dumps(episode.tags),
            ),
        )
        await self._db.commit()

        if self._vector_memory:
            try:
                await self._vector_memory.embed_and_store(
                    episode.content,
                    episode.id,
                    "episodic",
                )
            except Exception as exc:
                if self._bus:
                    await self._bus.publish(
                        EventType.ERROR,
                        {
                            "component": "episodic_memory",
                            "operation": "vector_store",
                            "episode_id": episode.id,
                            "error": str(exc),
                        },
                        source="memory.episodic",
                    )

        return episode

    async def search(
        self,
        query: str,
        limit: int = 10,
        min_importance: float = 0.0,
    ) -> list[EpisodeSearchResult]:
        """Full-text search across episodic memories."""
        assert self._db is not None

        # Sanitize query for FTS5: strip special chars, require at least one word
        import re
        sanitized = re.sub(r'[^\w\s]', ' ', query).strip()
        if not sanitized or len(sanitized) < 2:
            return []

        # Use prefix matching for better recall on partial words
        tokens = sanitized.split()
        fts_query = " OR ".join(f'"{t}"' for t in tokens[:10] if len(t) >= 2)
        if not fts_query:
            return []

        rows = await self._db.execute_fetchall(
            """SELECT e.id, e.timestamp, e.source, e.author, e.content,
                      e.importance, e.emotional_valence, e.tags_json,
                      e.access_count, e.last_accessed,
                      rank
               FROM episodes_fts fts
               JOIN episodes e ON e.rowid = fts.rowid
               WHERE episodes_fts MATCH ?
               AND e.importance >= ?
               ORDER BY rank
               LIMIT ?""",
            (fts_query, min_importance, limit),
        )

        results = []
        for row in rows:
            episode = self._row_to_episode(row)
            # FTS5 rank is negative (lower = more relevant), normalize to 0-1
            raw_rank = abs(row[10]) if row[10] else 1.0
            relevance = max(0.0, min(1.0, 1.0 / (1.0 + raw_rank)))
            results.append(EpisodeSearchResult(episode=episode, relevance=relevance))

        # Batch access tracking (single commit for all results)
        if results:
            for r in results:
                await self._track_access(r.episode.id)
            await self._db.commit()

        return results

    async def get_recent(
        self,
        limit: int = 20,
        since: float | None = None,
    ) -> list[Episode]:
        """Get recent episodes, optionally since a timestamp."""
        assert self._db is not None

        if since is not None:
            rows = await self._db.execute_fetchall(
                """SELECT id, timestamp, source, author, content,
                          importance, emotional_valence, tags_json,
                          access_count, last_accessed
                   FROM episodes
                   WHERE timestamp >= ?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (since, limit),
            )
        else:
            rows = await self._db.execute_fetchall(
                """SELECT id, timestamp, source, author, content,
                          importance, emotional_valence, tags_json,
                          access_count, last_accessed
                   FROM episodes
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (limit,),
            )

        return [self._row_to_episode(row) for row in rows]

    async def get_important(
        self,
        limit: int = 10,
        min_importance: float = 0.7,
    ) -> list[Episode]:
        """Get the most important memories."""
        assert self._db is not None

        rows = await self._db.execute_fetchall(
            """SELECT id, timestamp, source, author, content,
                      importance, emotional_valence, tags_json,
                      access_count, last_accessed
               FROM episodes
               WHERE importance >= ?
               ORDER BY importance DESC, access_count DESC
               LIMIT ?""",
            (min_importance, limit),
        )

        return [self._row_to_episode(row) for row in rows]

    async def count(self) -> int:
        """Total number of episodes stored."""
        assert self._db is not None
        row = await self._db.execute_fetchall("SELECT COUNT(*) FROM episodes")
        return row[0][0] if row else 0

    async def get_by_id(self, episode_id: str) -> Episode | None:
        """Fetch a single episode by ID."""
        assert self._db is not None
        rows = await self._db.execute_fetchall(
            """SELECT id, timestamp, source, author, content,
                      importance, emotional_valence, tags_json,
                      access_count, last_accessed
               FROM episodes
               WHERE id = ?""",
            (episode_id,),
        )
        return self._row_to_episode(rows[0]) if rows else None

    async def get_recent_for_user(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[Episode]:
        """Get recent episodes from a specific user.

        Matches by author field OR by a ``user_id:<id>`` tag so both the
        display name and the canonical identity hash resolve correctly.
        """
        assert self._db is not None
        tag_pattern = f'%"user_id:{user_id}"%'
        rows = await self._db.execute_fetchall(
            """SELECT id, timestamp, source, author, content,
                      importance, emotional_valence, tags_json,
                      access_count, last_accessed
               FROM episodes
               WHERE author = ? OR tags_json LIKE ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (user_id, tag_pattern, limit),
        )
        return [self._row_to_episode(row) for row in rows]

    async def get_for_namespace(
        self,
        namespace: str,
        limit: int = 50,
    ) -> list[Episode]:
        """Get recent episodes scoped to a memory namespace (matches author field)."""
        assert self._db is not None
        rows = await self._db.execute_fetchall(
            """SELECT id, timestamp, source, author, content,
                      importance, emotional_valence, tags_json,
                      access_count, last_accessed
               FROM episodes
               WHERE author = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (namespace, limit),
        )
        return [self._row_to_episode(row) for row in rows]

    async def clear(self) -> int:
        """Delete all episodes and rebuild FTS index. Returns count deleted."""
        assert self._db is not None
        row = await self._db.execute_fetchall("SELECT COUNT(*) FROM episodes")
        count = row[0][0] if row else 0
        await self._db.execute("DELETE FROM episodes")
        await self._db.execute(
            "INSERT INTO episodes_fts(episodes_fts) VALUES('rebuild')"
        )
        await self._db.commit()
        return count

    async def prune(self, keep_days: int = 30) -> int:
        """Delete episodes older than the retention window."""
        assert self._db is not None
        cutoff = time.time() - (keep_days * 86400)
        row = await self._db.execute_fetchall(
            "SELECT COUNT(*) FROM episodes WHERE timestamp < ?",
            (cutoff,),
        )
        count = row[0][0] if row else 0
        await self._db.execute("DELETE FROM episodes WHERE timestamp < ?", (cutoff,))
        await self._db.execute("INSERT INTO episodes_fts(episodes_fts) VALUES('rebuild')")
        await self._db.commit()
        return count

    async def close(self) -> None:
        """Close the database connection."""
        if self._db and self._owns_db:
            await self._db.close()
        self._db = None

    async def ping(self) -> bool:
        """Cheap readiness check."""
        if not self._db:
            return False
        rows = await self._db.execute_fetchall("SELECT 1")
        return bool(rows and rows[0][0] == 1)

    # -- Internal -----------------------------------------------------------

    async def _track_access(self, episode_id: str) -> None:
        """Update access count and last_accessed time."""
        if self._db:
            await self._db.execute(
                """UPDATE episodes
                   SET access_count = access_count + 1,
                       last_accessed = ?
                   WHERE id = ?""",
                (time.time(), episode_id),
            )

    def _row_to_episode(self, row: tuple) -> Episode:
        return Episode(
            id=row[0],
            timestamp=row[1],
            source=row[2],
            author=row[3],
            content=row[4],
            importance=row[5],
            emotional_valence=row[6],
            tags=json.loads(row[7]) if row[7] else [],
            access_count=row[8] if len(row) > 8 else 0,
            last_accessed=row[9] if len(row) > 9 else 0.0,
        )
