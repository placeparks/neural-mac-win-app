"""Cross-instance distilled memory sharing -- share patterns, not raw content."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import aiosqlite

_VALID_PATTERN_TYPES = {"procedural", "behavioral", "skill_template"}
_VALID_SCOPES = {"public", "team", "private"}
_VALID_PROBATION_STATUSES = {"imported", "probation", "accepted", "rejected"}
_VALID_REVIEW_ACTIONS = {"accept", "reject"}


def _new_id(prefix: str = "sp") -> str:
    raw = f"{prefix}-{time.time_ns()}"
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


class DistilledSharingManager:
    """Share distilled behavioural/procedural patterns across NeuralClaw
    instances without leaking raw user content.

    Every imported pattern starts in **probation** and must be explicitly
    accepted or rejected before it is used by the runtime.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create tables: shared_patterns, import_log."""
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS shared_patterns (
                    pattern_id          TEXT PRIMARY KEY,
                    pattern_type        TEXT NOT NULL,
                    title               TEXT NOT NULL,
                    description         TEXT NOT NULL DEFAULT '',
                    content_json        TEXT NOT NULL,
                    scope               TEXT NOT NULL DEFAULT 'team',
                    source_instance_id  TEXT,
                    opt_in              INTEGER NOT NULL DEFAULT 1,
                    probation_status    TEXT NOT NULL DEFAULT 'imported',
                    created_at          REAL NOT NULL,
                    updated_at          REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sp_scope  ON shared_patterns(scope);
                CREATE INDEX IF NOT EXISTS idx_sp_status ON shared_patterns(probation_status);

                CREATE TABLE IF NOT EXISTS import_log (
                    import_id       TEXT PRIMARY KEY,
                    pattern_id      TEXT NOT NULL,
                    source_instance TEXT NOT NULL,
                    imported_at     REAL NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'imported'
                );
                CREATE INDEX IF NOT EXISTS idx_il_pattern ON import_log(pattern_id);
                """
            )
        self._initialized = True

    # ------------------------------------------------------------------
    # Distillation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_raw_content(content: dict) -> dict:
        """Remove any raw user content from a pattern, keeping only
        procedural/behavioural artifacts."""
        sanitized: dict[str, Any] = {}
        # Keep structural keys, drop anything that looks like raw user text
        _safe_keys = {
            "steps", "actions", "conditions", "triggers", "parameters",
            "workflow", "template", "metadata", "tags", "rules",
            "patterns", "sequence", "config",
        }
        for key, value in content.items():
            if key in _safe_keys:
                sanitized[key] = value
            elif key.startswith("_"):
                continue  # skip internal/private fields
            elif isinstance(value, (int, float, bool)):
                sanitized[key] = value
            elif isinstance(value, str) and len(value) <= 200:
                # Short strings are likely labels/identifiers, not user content
                sanitized[key] = value
            # Omit long strings (likely raw user content)
        return sanitized

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def distill_pattern(
        self,
        pattern_type: str,
        title: str,
        description: str,
        content: dict,
        scope: str = "team",
    ) -> str:
        """Distill a behavioural/procedural pattern for sharing. Returns pattern_id.

        MUST strip any raw user content -- only procedural/behavioural artifacts
        are kept.
        """
        await self.initialize()
        if pattern_type not in _VALID_PATTERN_TYPES:
            raise ValueError(
                f"Invalid pattern_type '{pattern_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_PATTERN_TYPES))}"
            )
        if scope not in _VALID_SCOPES:
            raise ValueError(
                f"Invalid scope '{scope}'. Must be one of: {', '.join(sorted(_VALID_SCOPES))}"
            )

        sanitized_content = self._strip_raw_content(content)
        pattern_id = _new_id("sp")
        now = time.time()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO shared_patterns
                    (pattern_id, pattern_type, title, description, content_json,
                     scope, opt_in, probation_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, 'accepted', ?, ?)
                """,
                (
                    pattern_id,
                    pattern_type,
                    title,
                    description,
                    json.dumps(sanitized_content, default=str),
                    scope,
                    now,
                    now,
                ),
            )
            await db.commit()
        return pattern_id

    async def export_patterns(self, scope: str = "team") -> list[dict]:
        """Export patterns available for sharing (only opted-in, accepted)."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT * FROM shared_patterns
                WHERE scope = ? AND opt_in = 1 AND probation_status = 'accepted'
                ORDER BY updated_at DESC
                """,
                (scope,),
            )
            rows = await cur.fetchall()
        return [
            {
                "pattern_id": r["pattern_id"],
                "pattern_type": r["pattern_type"],
                "title": r["title"],
                "description": r["description"],
                "content": json.loads(r["content_json"]),
                "scope": r["scope"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    async def import_pattern(self, pattern: dict, source_instance: str) -> dict:
        """Import a shared pattern. Always starts in probation."""
        await self.initialize()
        pattern_id = pattern.get("pattern_id") or _new_id("sp")
        now = time.time()
        import_id = _new_id("imp")

        async with aiosqlite.connect(self._db_path) as db:
            # Check if already imported
            cur = await db.execute(
                "SELECT pattern_id FROM shared_patterns WHERE pattern_id = ?",
                (pattern_id,),
            )
            exists = await cur.fetchone()

            if not exists:
                content = pattern.get("content", {})
                sanitized = self._strip_raw_content(content) if isinstance(content, dict) else {}
                await db.execute(
                    """
                    INSERT INTO shared_patterns
                        (pattern_id, pattern_type, title, description, content_json,
                         scope, source_instance_id, opt_in, probation_status,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'probation', ?, ?)
                    """,
                    (
                        pattern_id,
                        pattern.get("pattern_type", "procedural"),
                        pattern.get("title", "Imported pattern"),
                        pattern.get("description", ""),
                        json.dumps(sanitized, default=str),
                        pattern.get("scope", "team"),
                        source_instance,
                        now,
                        now,
                    ),
                )

            # Log the import
            await db.execute(
                """
                INSERT INTO import_log (import_id, pattern_id, source_instance, imported_at, status)
                VALUES (?, ?, ?, ?, 'imported')
                """,
                (import_id, pattern_id, source_instance, now),
            )
            await db.commit()

        return {
            "ok": True,
            "pattern_id": pattern_id,
            "import_id": import_id,
            "probation_status": "probation",
            "source_instance": source_instance,
        }

    async def review_import(self, pattern_id: str, action: str) -> dict:
        """Accept or reject an imported pattern.

        Parameters
        ----------
        action : str
            ``"accept"`` or ``"reject"``.
        """
        await self.initialize()
        if action not in _VALID_REVIEW_ACTIONS:
            return {
                "ok": False,
                "error": f"Invalid action '{action}'. Must be 'accept' or 'reject'.",
            }

        new_status = "accepted" if action == "accept" else "rejected"
        now = time.time()

        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                "SELECT pattern_id FROM shared_patterns WHERE pattern_id = ?",
                (pattern_id,),
            )
            row = await cur.fetchone()
            if not row:
                return {"ok": False, "error": f"Pattern {pattern_id} not found"}

            await db.execute(
                """
                UPDATE shared_patterns
                SET probation_status = ?, updated_at = ?
                WHERE pattern_id = ?
                """,
                (new_status, now, pattern_id),
            )
            await db.commit()

        return {
            "ok": True,
            "pattern_id": pattern_id,
            "probation_status": new_status,
        }

    async def list_patterns(
        self,
        scope: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """List patterns with optional filters."""
        await self.initialize()
        conditions: list[str] = []
        params: list[Any] = []
        if scope:
            conditions.append("scope = ?")
            params.append(scope)
        if status:
            conditions.append("probation_status = ?")
            params.append(status)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM shared_patterns {where} ORDER BY updated_at DESC"

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(query, params)
            rows = await cur.fetchall()

        return [
            {
                "pattern_id": r["pattern_id"],
                "pattern_type": r["pattern_type"],
                "title": r["title"],
                "description": r["description"],
                "content": json.loads(r["content_json"]),
                "scope": r["scope"],
                "source_instance_id": r["source_instance_id"],
                "probation_status": r["probation_status"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
