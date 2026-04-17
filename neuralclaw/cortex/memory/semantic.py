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

    def __init__(self, db_path: str = ":memory:", db_pool: DBPool | None = None, namespace: str = "global") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | DBPool | None = None
        self._db_pool = db_pool
        self._owns_db = db_pool is None
        self._namespace = namespace

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
                namespace TEXT NOT NULL DEFAULT 'global',
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
                namespace TEXT NOT NULL DEFAULT 'global',
                created_at REAL NOT NULL DEFAULT (unixepoch('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_rel_from ON relationships(from_entity_id);
            CREATE INDEX IF NOT EXISTS idx_rel_to ON relationships(to_entity_id);
            CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(relation_type);
        """)
        await self._db.commit()

        if not await self._has_column("entities", "namespace"):
            await self._db.execute("ALTER TABLE entities ADD COLUMN namespace TEXT NOT NULL DEFAULT 'global'")
            await self._db.commit()

        if not await self._has_column("relationships", "namespace"):
            await self._db.execute("ALTER TABLE relationships ADD COLUMN namespace TEXT NOT NULL DEFAULT 'global'")
            await self._db.commit()

        await self._db.executescript("""
            CREATE INDEX IF NOT EXISTS idx_entities_namespace ON entities(namespace);
            CREATE INDEX IF NOT EXISTS idx_rel_namespace ON relationships(namespace);
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

        # Check if entity exists (by name + type + namespace)
        row = await self._db.execute_fetchall(
            "SELECT id, name, entity_type, attributes_json, created_at, updated_at "
            "FROM entities WHERE name = ? AND entity_type = ? AND namespace = ?",
            (name, entity_type, self._namespace),
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
                "INSERT INTO entities (id, name, entity_type, attributes_json, namespace, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (entity.id, entity.name, entity.entity_type, json.dumps(entity.attributes), self._namespace, now, now),
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
            "WHERE r.from_entity_id = ? AND r.relation_type = ? "
            "AND r.to_entity_id != ? AND r.namespace = ? AND e.namespace = ?",
            (from_entity.id, relation_type, to_entity.id, self._namespace, self._namespace),
        )

        # Predicates that are typically exclusive (entity can only have one at a time)
        EXCLUSIVE_PREDICATES = frozenset({
            "works_at", "lives_in", "born_in", "married_to", "capital_of",
            "ceo_of", "president_of", "located_in", "headquartered_in",
        })

        # If contradiction found for an exclusive predicate, decay existing relationship
        if relation_type in EXCLUSIVE_PREDICATES:
            for eid, ename in existing:
                # Only decay if the *existing* relationship had reasonable confidence
                rows = await self._db.execute_fetchall(
                    "SELECT confidence FROM relationships WHERE id = ?", (eid,),
                )
                if rows and rows[0][0] > 0.3:
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
            "INSERT INTO relationships (id, from_entity_id, to_entity_id, relation_type, confidence, source_event_id, namespace, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (rel.id, rel.from_entity_id, rel.to_entity_id, rel.relation_type, rel.confidence, rel.source_event_id, self._namespace, rel.created_at),
        )
        await self._db.commit()
        return rel

    async def query_entity(self, name: str) -> Entity | None:
        """Look up an entity by name within this namespace."""
        assert self._db is not None
        rows = await self._db.execute_fetchall(
            "SELECT id, name, entity_type, attributes_json, created_at, updated_at "
            "FROM entities WHERE name = ? AND namespace = ?",
            (name, self._namespace),
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
                   AND r.namespace = ? AND ef.namespace = ? AND et.namespace = ?
                   ORDER BY r.confidence DESC""",
                (entity_name, min_confidence, self._namespace, self._namespace, self._namespace),
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
                   AND r.namespace = ? AND ef.namespace = ? AND et.namespace = ?
                   ORDER BY r.confidence DESC""",
                (entity_name, min_confidence, self._namespace, self._namespace, self._namespace),
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
                "FROM entities WHERE name LIKE ? AND entity_type = ? AND namespace = ? LIMIT ?",
                (f"%{query}%", entity_type, self._namespace, limit),
            )
        else:
            rows = await self._db.execute_fetchall(
                "SELECT id, name, entity_type, attributes_json, created_at, updated_at "
                "FROM entities WHERE name LIKE ? AND namespace = ? LIMIT ?",
                (f"%{query}%", self._namespace, limit),
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
               WHERE r.confidence >= ? AND r.namespace = ?
               ORDER BY r.confidence DESC
               LIMIT ?""",
            (min_confidence, self._namespace, limit),
        )

        return [
            KnowledgeTriple(subject=r[0], predicate=r[1], obj=r[2], confidence=r[3])
            for r in rows
        ]

    async def count(self) -> int:
        """Total number of entities in this namespace."""
        assert self._db is not None
        row = await self._db.execute_fetchall(
            "SELECT COUNT(*) FROM entities WHERE namespace = ?",
            (self._namespace,),
        )
        return row[0][0] if row else 0

    async def get_by_id(self, entity_id: str) -> Entity | None:
        """Fetch a single entity by ID."""
        assert self._db is not None
        rows = await self._db.execute_fetchall(
            "SELECT id, name, entity_type, attributes_json, created_at, updated_at "
            "FROM entities WHERE id = ? AND namespace = ?",
            (entity_id, self._namespace),
        )
        return self._row_to_entity(rows[0]) if rows else None

    async def list_entities(
        self,
        query: str = "",
        limit: int = 50,
    ) -> list[Entity]:
        """List entities in this namespace for inspection."""
        assert self._db is not None
        params: list[object] = [self._namespace]
        sql = (
            "SELECT id, name, entity_type, attributes_json, created_at, updated_at "
            "FROM entities WHERE namespace = ?"
        )
        if query.strip():
            sql += " AND (name LIKE ? OR attributes_json LIKE ?)"
            like = f"%{query.strip()}%"
            params.extend([like, like])
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        rows = await self._db.execute_fetchall(sql, tuple(params))
        return [self._row_to_entity(row) for row in rows]

    async def update_entity(
        self,
        entity_id: str,
        *,
        name: str | None = None,
        entity_type: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Entity | None:
        """Update an entity in-place."""
        assert self._db is not None
        current = await self.get_by_id(entity_id)
        if not current:
            return None

        next_attributes = {**current.attributes, **(attributes or {})}
        now = time.time()
        await self._db.execute(
            """
            UPDATE entities
            SET name = ?, entity_type = ?, attributes_json = ?, updated_at = ?
            WHERE id = ? AND namespace = ?
            """,
            (
                name or current.name,
                entity_type or current.entity_type,
                json.dumps(next_attributes),
                now,
                entity_id,
                self._namespace,
            ),
        )
        await self._db.commit()
        return await self.get_by_id(entity_id)

    async def delete_entity(self, entity_id: str) -> bool:
        """Delete an entity and all attached relationships."""
        assert self._db is not None
        await self._db.execute(
            "DELETE FROM relationships WHERE (from_entity_id = ? OR to_entity_id = ?) AND namespace = ?",
            (entity_id, entity_id, self._namespace),
        )
        await self._db.execute(
            "DELETE FROM entities WHERE id = ? AND namespace = ?",
            (entity_id, self._namespace),
        )
        await self._db.commit()
        return True

    async def pin_entity(self, entity_id: str) -> Entity | None:
        """Mark an entity as pinned for desktop inspection."""
        return await self.update_entity(entity_id, attributes={"pinned": True})

    async def clear(self) -> int:
        """Delete all entities and relationships in this namespace."""
        assert self._db is not None
        row = await self._db.execute_fetchall(
            "SELECT COUNT(*) FROM entities WHERE namespace = ?",
            (self._namespace,),
        )
        count = row[0][0] if row else 0
        await self._db.execute(
            "DELETE FROM relationships WHERE namespace = ?",
            (self._namespace,),
        )
        await self._db.execute(
            "DELETE FROM entities WHERE namespace = ?",
            (self._namespace,),
        )
        await self._db.commit()
        return count

    async def prune(self, keep_days: int = 180) -> int:
        """Delete stale entities and relationships older than the retention window."""
        assert self._db is not None
        cutoff = time.time() - (keep_days * 86400)
        row = await self._db.execute_fetchall(
            "SELECT COUNT(*) FROM entities WHERE namespace = ? AND updated_at < ?",
            (self._namespace, cutoff),
        )
        count = row[0][0] if row else 0
        if count <= 0:
            return 0
        rows = await self._db.execute_fetchall(
            "SELECT id FROM entities WHERE namespace = ? AND updated_at < ?",
            (self._namespace, cutoff),
        )
        entity_ids = [row[0] for row in rows]
        if entity_ids:
            placeholders = ",".join("?" for _ in entity_ids)
            await self._db.execute(
                f"DELETE FROM relationships WHERE namespace = ? AND (from_entity_id IN ({placeholders}) OR to_entity_id IN ({placeholders}))",
                (self._namespace, *entity_ids, *entity_ids),
            )
            await self._db.execute(
                f"DELETE FROM entities WHERE namespace = ? AND id IN ({placeholders})",
                (self._namespace, *entity_ids),
            )
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

    async def _has_column(self, table: str, column: str) -> bool:
        assert self._db is not None
        rows = await self._db.execute_fetchall(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in rows)
