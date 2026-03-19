"""
Semantic Memory — Entity-relationship knowledge graph.

A local knowledge graph backed by SQLite that stores entities, relationships,
and facts extracted from interactions. Supports confidence-scored typed
relationships and contradiction detection.

Schema:
    entities(id, name, type, attributes_json, created_at, updated_at)
    relationships(id, from_entity, to_entity, relation_type, confidence,
                  source_event_id, created_at)
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

from neuralclaw.cortex.memory.db import DBPool


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    """A known entity in the knowledge graph."""
    id: str
    name: str
    entity_type: str  # person, organization, location, concept, etc.
    attributes: dict[str, Any]
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class Relationship:
    """A typed relationship between two entities."""
    id: str
    from_entity_id: str
    to_entity_id: str
    relation_type: str  # works_at, lives_in, likes, knows, etc.
    confidence: float   # 0.0 – 1.0
    source_event_id: str | None = None
    created_at: float = 0.0


@dataclass
class KnowledgeTriple:
    """A subject-predicate-object triple for easy consumption."""
    subject: str
    predicate: str
    obj: str
    confidence: float


# ---------------------------------------------------------------------------
# Semantic Memory Store
# ---------------------------------------------------------------------------

class SemanticMemory:
    """
    SQLite-backed entity-relationship knowledge graph.

    Key features:
    - Store entities with typed attributes
    - Confidence-scored typed relationships
    - Contradiction detection (conflicting facts)
    - Graph traversal queries
    """

    def __init__(self, db_path: str = ":memory:", db_pool: DBPool | None = None) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | DBPool | None = None
        self._db_pool = db_pool
        self._owns_db = db_pool is None

    async def initialize(self) -> None:
        """Initialize database and create tables."""
        if self._db_pool:
            await self._db_pool.initialize()
            self._db = self._db_pool
        else:
            self._db = await aiosqlite.connect(self._db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA foreign_keys=ON")

        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT 'unknown',
                attributes_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL DEFAULT (unixepoch('now')),
                updated_at REAL NOT NULL DEFAULT (unixepoch('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
            CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

            CREATE TABLE IF NOT EXISTS relationships (
                id TEXT PRIMARY KEY,
                from_entity_id TEXT NOT NULL REFERENCES entities(id),
                to_entity_id TEXT NOT NULL REFERENCES entities(id),
                relation_type TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.8,
                source_event_id TEXT,
                created_at REAL NOT NULL DEFAULT (unixepoch('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_rel_from ON relationships(from_entity_id);
            CREATE INDEX IF NOT EXISTS idx_rel_to ON relationships(to_entity_id);
            CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(relation_type);
        """)
        await self._db.commit()

    async def upsert_entity(
        self,
        name: str,
        entity_type: str = "unknown",
        attributes: dict[str, Any] | None = None,
    ) -> Entity:
        """Insert or update an entity. Returns the entity."""
        assert self._db is not None
        now = time.time()

        # Check if entity exists (by name + type)
        row = await self._db.execute_fetchall(
            "SELECT id, name, entity_type, attributes_json, created_at, updated_at "
            "FROM entities WHERE name = ? AND entity_type = ?",
            (name, entity_type),
        )

        if row:
            # Update existing
            existing = self._row_to_entity(row[0])
            merged = {**existing.attributes, **(attributes or {})}
            await self._db.execute(
                "UPDATE entities SET attributes_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(merged), now, existing.id),
            )
            await self._db.commit()
            existing.attributes = merged
            existing.updated_at = now
            return existing
        else:
            # Insert new
            entity = Entity(
                id=uuid.uuid4().hex[:12],
                name=name,
                entity_type=entity_type,
                attributes=attributes or {},
                created_at=now,
                updated_at=now,
            )
            await self._db.execute(
                "INSERT INTO entities (id, name, entity_type, attributes_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (entity.id, entity.name, entity.entity_type, json.dumps(entity.attributes), now, now),
            )
            await self._db.commit()
            return entity

    async def add_relationship(
        self,
        from_name: str,
        relation_type: str,
        to_name: str,
        confidence: float = 0.8,
        from_type: str = "unknown",
        to_type: str = "unknown",
        source_event_id: str | None = None,
    ) -> Relationship:
        """
        Add a relationship between two entities (creating them if needed).

        Also checks for contradictions — e.g. if "User works_at CompanyA"
        exists and we're adding "User works_at CompanyB", flag it.
        """
        assert self._db is not None

        from_entity = await self.upsert_entity(from_name, from_type)
        to_entity = await self.upsert_entity(to_name, to_type)

        # Check for contradictions (same subject + predicate, different object)
        existing = await self._db.execute_fetchall(
            "SELECT r.id, e.name FROM relationships r "
            "JOIN entities e ON e.id = r.to_entity_id "
            "WHERE r.from_entity_id = ? AND r.relation_type = ? AND r.to_entity_id != ?",
            (from_entity.id, relation_type, to_entity.id),
        )

        # If contradiction found with lower confidence, reduce its confidence
        for eid, ename in existing:
            if confidence > 0.5:
                await self._db.execute(
                    "UPDATE relationships SET confidence = confidence * 0.5 WHERE id = ?",
                    (eid,),
                )

        rel = Relationship(
            id=uuid.uuid4().hex[:12],
            from_entity_id=from_entity.id,
            to_entity_id=to_entity.id,
            relation_type=relation_type,
            confidence=confidence,
            source_event_id=source_event_id,
            created_at=time.time(),
        )

        await self._db.execute(
            "INSERT INTO relationships (id, from_entity_id, to_entity_id, relation_type, confidence, source_event_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rel.id, rel.from_entity_id, rel.to_entity_id, rel.relation_type, rel.confidence, rel.source_event_id, rel.created_at),
        )
        await self._db.commit()
        return rel

    async def query_entity(self, name: str) -> Entity | None:
        """Look up an entity by name."""
        assert self._db is not None
        rows = await self._db.execute_fetchall(
            "SELECT id, name, entity_type, attributes_json, created_at, updated_at "
            "FROM entities WHERE name = ?",
            (name,),
        )
        return self._row_to_entity(rows[0]) if rows else None

    async def get_relationships(
        self,
        entity_name: str,
        direction: str = "both",
        min_confidence: float = 0.3,
    ) -> list[KnowledgeTriple]:
        """Get all relationships involving an entity as knowledge triples."""
        assert self._db is not None

        triples: list[KnowledgeTriple] = []

        if direction in ("out", "both"):
            rows = await self._db.execute_fetchall(
                """SELECT ef.name, r.relation_type, et.name, r.confidence
                   FROM relationships r
                   JOIN entities ef ON ef.id = r.from_entity_id
                   JOIN entities et ON et.id = r.to_entity_id
                   WHERE ef.name = ? AND r.confidence >= ?
                   ORDER BY r.confidence DESC""",
                (entity_name, min_confidence),
            )
            for row in rows:
                triples.append(KnowledgeTriple(
                    subject=row[0], predicate=row[1], obj=row[2], confidence=row[3]
                ))

        if direction in ("in", "both"):
            rows = await self._db.execute_fetchall(
                """SELECT ef.name, r.relation_type, et.name, r.confidence
                   FROM relationships r
                   JOIN entities ef ON ef.id = r.from_entity_id
                   JOIN entities et ON et.id = r.to_entity_id
                   WHERE et.name = ? AND r.confidence >= ?
                   ORDER BY r.confidence DESC""",
                (entity_name, min_confidence),
            )
            for row in rows:
                triples.append(KnowledgeTriple(
                    subject=row[0], predicate=row[1], obj=row[2], confidence=row[3]
                ))

        return triples

    async def search_entities(
        self,
        query: str,
        entity_type: str | None = None,
        limit: int = 10,
    ) -> list[Entity]:
        """Search entities by name (LIKE match)."""
        assert self._db is not None

        if entity_type:
            rows = await self._db.execute_fetchall(
                "SELECT id, name, entity_type, attributes_json, created_at, updated_at "
                "FROM entities WHERE name LIKE ? AND entity_type = ? LIMIT ?",
                (f"%{query}%", entity_type, limit),
            )
        else:
            rows = await self._db.execute_fetchall(
                "SELECT id, name, entity_type, attributes_json, created_at, updated_at "
                "FROM entities WHERE name LIKE ? LIMIT ?",
                (f"%{query}%", limit),
            )

        return [self._row_to_entity(r) for r in rows]

    async def get_all_triples(
        self,
        min_confidence: float = 0.3,
        limit: int = 100,
    ) -> list[KnowledgeTriple]:
        """Get all knowledge triples above a confidence threshold."""
        assert self._db is not None

        rows = await self._db.execute_fetchall(
            """SELECT ef.name, r.relation_type, et.name, r.confidence
               FROM relationships r
               JOIN entities ef ON ef.id = r.from_entity_id
               JOIN entities et ON et.id = r.to_entity_id
               WHERE r.confidence >= ?
               ORDER BY r.confidence DESC
               LIMIT ?""",
            (min_confidence, limit),
        )

        return [
            KnowledgeTriple(subject=r[0], predicate=r[1], obj=r[2], confidence=r[3])
            for r in rows
        ]

    async def count(self) -> int:
        """Total number of entities stored."""
        assert self._db is not None
        row = await self._db.execute_fetchall("SELECT COUNT(*) FROM entities")
        return row[0][0] if row else 0

    async def clear(self) -> int:
        """Delete all entities and relationships. Returns entity count deleted."""
        assert self._db is not None
        row = await self._db.execute_fetchall("SELECT COUNT(*) FROM entities")
        count = row[0][0] if row else 0
        await self._db.execute("DELETE FROM relationships")
        await self._db.execute("DELETE FROM entities")
        await self._db.commit()
        return count

    async def close(self) -> None:
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

    def _row_to_entity(self, row: tuple) -> Entity:
        return Entity(
            id=row[0],
            name=row[1],
            entity_type=row[2],
            attributes=json.loads(row[3]) if row[3] else {},
            created_at=row[4] if len(row) > 4 else 0.0,
            updated_at=row[5] if len(row) > 5 else 0.0,
        )
