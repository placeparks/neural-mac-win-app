"""
Agent Store — Persistent agent definitions in SQLite.

Stores agent blueprints that survive gateway restarts.
Each definition includes provider config, system prompt, capabilities,
and memory namespace for full isolation.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiosqlite


@dataclass
class AgentDefinition:
    """Persistent agent blueprint."""

    agent_id: str
    name: str
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    provider: str = "local"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    system_prompt: str = ""
    memory_namespace: str = ""
    auto_start: bool = False
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "capabilities": self.capabilities,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "system_prompt": self.system_prompt,
            "memory_namespace": self.memory_namespace,
            "auto_start": self.auto_start,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


class AgentStore:
    """SQLite CRUD for persistent agent definitions."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS agent_definitions (
                agent_id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                capabilities TEXT DEFAULT '[]',
                provider TEXT DEFAULT 'local',
                model TEXT DEFAULT '',
                base_url TEXT DEFAULT '',
                api_key TEXT DEFAULT '',
                system_prompt TEXT DEFAULT '',
                memory_namespace TEXT NOT NULL,
                auto_start INTEGER DEFAULT 0,
                created_at REAL,
                updated_at REAL,
                metadata TEXT DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_agent_name
                ON agent_definitions(name);
            CREATE INDEX IF NOT EXISTS idx_agent_auto_start
                ON agent_definitions(auto_start);
        """)
        await self._db.commit()

    async def create(self, defn: AgentDefinition) -> str:
        """Insert a new agent definition. Returns agent_id."""
        assert self._db is not None
        if not defn.agent_id:
            defn.agent_id = uuid.uuid4().hex[:12]
        if not defn.memory_namespace:
            defn.memory_namespace = f"agent:{defn.name}"
        now = time.time()
        defn.created_at = now
        defn.updated_at = now

        await self._db.execute(
            """INSERT INTO agent_definitions
               (agent_id, name, description, capabilities, provider, model,
                base_url, api_key, system_prompt, memory_namespace,
                auto_start, created_at, updated_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                defn.agent_id, defn.name, defn.description,
                json.dumps(defn.capabilities), defn.provider, defn.model,
                defn.base_url, defn.api_key, defn.system_prompt,
                defn.memory_namespace, int(defn.auto_start),
                defn.created_at, defn.updated_at, json.dumps(defn.metadata),
            ),
        )
        await self._db.commit()
        return defn.agent_id

    async def get(self, agent_id: str) -> AgentDefinition | None:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT * FROM agent_definitions WHERE agent_id = ?",
            (agent_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_defn(row) if row else None

    async def get_by_name(self, name: str) -> AgentDefinition | None:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT * FROM agent_definitions WHERE name = ?",
            (name,),
        )
        row = await cursor.fetchone()
        return self._row_to_defn(row) if row else None

    async def list_all(self) -> list[AgentDefinition]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT * FROM agent_definitions ORDER BY created_at DESC",
        )
        rows = await cursor.fetchall()
        return [self._row_to_defn(r) for r in rows]

    async def update(self, agent_id: str, **kwargs: Any) -> bool:
        assert self._db is not None
        defn = await self.get(agent_id)
        if not defn:
            return False

        kwargs["updated_at"] = time.time()
        sets = []
        vals = []
        for key, val in kwargs.items():
            if key in ("capabilities", "metadata"):
                val = json.dumps(val)
            elif key == "auto_start":
                val = int(val)
            col = key
            sets.append(f"{col} = ?")
            vals.append(val)

        vals.append(agent_id)
        await self._db.execute(
            f"UPDATE agent_definitions SET {', '.join(sets)} WHERE agent_id = ?",
            tuple(vals),
        )
        await self._db.commit()
        return True

    async def delete(self, agent_id: str) -> bool:
        assert self._db is not None
        cursor = await self._db.execute(
            "DELETE FROM agent_definitions WHERE agent_id = ?",
            (agent_id,),
        )
        await self._db.commit()
        return (cursor.rowcount or 0) > 0

    async def get_auto_start(self) -> list[AgentDefinition]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT * FROM agent_definitions WHERE auto_start = 1 ORDER BY created_at",
        )
        rows = await cursor.fetchall()
        return [self._row_to_defn(r) for r in rows]

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _row_to_defn(self, row: tuple) -> AgentDefinition:
        return AgentDefinition(
            agent_id=row[0],
            name=row[1],
            description=row[2],
            capabilities=json.loads(row[3]) if row[3] else [],
            provider=row[4],
            model=row[5],
            base_url=row[6],
            api_key=row[7],
            system_prompt=row[8],
            memory_namespace=row[9],
            auto_start=bool(row[10]),
            created_at=row[11],
            updated_at=row[12],
            metadata=json.loads(row[13]) if row[13] else {},
        )
