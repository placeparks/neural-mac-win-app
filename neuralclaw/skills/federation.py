"""Federated skill distribution — share skill manifests across NeuralClaw peers."""

from __future__ import annotations
import json, time, hashlib
from pathlib import Path
from typing import Any
import aiosqlite

class SkillFederation:
    """Distributes skill manifests across federation peers.

    Skills are shared as manifests (metadata + tool definitions) not as
    code. Receiving peers can then use Forge to synthesize compatible
    implementations.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS federated_skills (
                    manifest_id TEXT PRIMARY KEY,
                    skill_name TEXT NOT NULL,
                    version TEXT NOT NULL DEFAULT '0.1.0',
                    description TEXT NOT NULL DEFAULT '',
                    tool_defs_json TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    dependencies_json TEXT NOT NULL DEFAULT '[]',
                    source_peer TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    probation_status TEXT NOT NULL DEFAULT 'pending',
                    local_implementation_path TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_fs_name_peer
                    ON federated_skills(skill_name, source_peer);

                CREATE TABLE IF NOT EXISTS federation_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    peer TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    payload_json TEXT,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_fe_peer ON federation_events(peer);
            """)
        self._initialized = True

    async def publish_skill(self, manifest: Any) -> str:
        """Publish a local skill manifest for federation distribution."""
        await self.initialize()
        manifest_id = f"fsk-{hashlib.sha256(f'{manifest.name}:{time.time_ns()}'.encode()).hexdigest()[:12]}"
        tool_defs = []
        for tool in getattr(manifest, "tools", []):
            tool_defs.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.to_json_schema() if hasattr(tool, "to_json_schema") else {},
            })
        capabilities = [str(c.value if hasattr(c, "value") else c) for c in getattr(manifest, "capabilities", [])]
        now = time.time()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO federated_skills
                    (manifest_id, skill_name, version, description, tool_defs_json,
                     capabilities_json, source_peer, status, probation_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'local', 'published', 'accepted', ?, ?)
            """, (manifest_id, manifest.name, getattr(manifest, "version", "0.1.0"),
                  manifest.description, json.dumps(tool_defs), json.dumps(capabilities), now, now))
            await db.commit()
        return manifest_id

    async def export_catalog(self) -> list[dict]:
        """Export the local skill catalog for sharing with peers."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""
                SELECT * FROM federated_skills WHERE source_peer = 'local' AND status = 'published'
            """)
            rows = await cur.fetchall()
        return [{
            "manifest_id": r["manifest_id"],
            "skill_name": r["skill_name"],
            "version": r["version"],
            "description": r["description"],
            "tool_defs": json.loads(r["tool_defs_json"]),
            "capabilities": json.loads(r["capabilities_json"]),
            "dependencies": json.loads(r["dependencies_json"]),
        } for r in rows]

    async def import_from_peer(self, peer_name: str, catalog: list[dict]) -> dict:
        """Import skill manifests from a federation peer. All start in probation."""
        await self.initialize()
        imported = 0
        skipped = 0
        now = time.time()
        for entry in catalog:
            skill_name = entry.get("skill_name", "")
            if not skill_name:
                skipped += 1
                continue
            manifest_id = entry.get("manifest_id") or f"fsk-{hashlib.sha256(f'{skill_name}:{peer_name}'.encode()).hexdigest()[:12]}"
            async with aiosqlite.connect(self._db_path) as db:
                cur = await db.execute(
                    "SELECT manifest_id FROM federated_skills WHERE skill_name = ? AND source_peer = ?",
                    (skill_name, peer_name))
                if await cur.fetchone():
                    skipped += 1
                    continue
                await db.execute("""
                    INSERT INTO federated_skills
                        (manifest_id, skill_name, version, description, tool_defs_json,
                         capabilities_json, dependencies_json, source_peer, status,
                         probation_status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'available', 'pending', ?, ?)
                """, (manifest_id, skill_name, entry.get("version", "0.1.0"),
                      entry.get("description", ""), json.dumps(entry.get("tool_defs", [])),
                      json.dumps(entry.get("capabilities", [])),
                      json.dumps(entry.get("dependencies", [])),
                      peer_name, now, now))
                # Log event
                event_id = f"fe-{hashlib.sha256(f'{manifest_id}:{now}'.encode()).hexdigest()[:12]}"
                await db.execute("""
                    INSERT INTO federation_events (event_id, event_type, peer, skill_name, created_at)
                    VALUES (?, 'imported', ?, ?, ?)
                """, (event_id, peer_name, skill_name, now))
                await db.commit()
            imported += 1
        return {"ok": True, "imported": imported, "skipped": skipped, "peer": peer_name}

    async def review_federated_skill(self, manifest_id: str, action: str) -> dict:
        """Accept or reject a federated skill. action: 'accept' | 'reject'"""
        await self.initialize()
        if action not in ("accept", "reject"):
            return {"ok": False, "error": f"Invalid action: {action}"}
        new_status = "accepted" if action == "accept" else "rejected"
        now = time.time()
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute("SELECT manifest_id FROM federated_skills WHERE manifest_id = ?", (manifest_id,))
            if not await cur.fetchone():
                return {"ok": False, "error": "Manifest not found"}
            await db.execute("""
                UPDATE federated_skills SET probation_status = ?, updated_at = ? WHERE manifest_id = ?
            """, (new_status, now, manifest_id))
            await db.commit()
        return {"ok": True, "manifest_id": manifest_id, "probation_status": new_status}

    async def list_federated_skills(self, status: str | None = None, peer: str | None = None) -> list[dict]:
        """List federated skills with optional filters."""
        await self.initialize()
        conditions: list[str] = []
        params: list[Any] = []
        if status:
            conditions.append("probation_status = ?")
            params.append(status)
        if peer:
            conditions.append("source_peer = ?")
            params.append(peer)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(f"SELECT * FROM federated_skills {where} ORDER BY updated_at DESC", params)
            rows = await cur.fetchall()
        return [{
            "manifest_id": r["manifest_id"],
            "skill_name": r["skill_name"],
            "version": r["version"],
            "description": r["description"],
            "tool_count": len(json.loads(r["tool_defs_json"])),
            "source_peer": r["source_peer"],
            "status": r["status"],
            "probation_status": r["probation_status"],
            "has_local_impl": bool(r["local_implementation_path"]),
            "updated_at": r["updated_at"],
        } for r in rows]

    async def get_federation_stats(self) -> dict:
        """Get federation statistics."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM federated_skills WHERE source_peer = 'local'")
            published = (await cur.fetchone())[0]
            cur = await db.execute("SELECT COUNT(*) FROM federated_skills WHERE source_peer != 'local'")
            imported = (await cur.fetchone())[0]
            cur = await db.execute("SELECT COUNT(*) FROM federated_skills WHERE probation_status = 'pending'")
            pending = (await cur.fetchone())[0]
            cur = await db.execute("SELECT COUNT(DISTINCT source_peer) FROM federated_skills WHERE source_peer != 'local'")
            peers = (await cur.fetchone())[0]
        return {
            "published_skills": published,
            "imported_skills": imported,
            "pending_review": pending,
            "connected_peers": peers,
        }
