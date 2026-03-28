"""
Evolution orchestrator for controlled capability self-improvement.

This module turns repeated runtime failures into candidate skills using the
existing Forge/Scout stack, activates them in probation, and promotes or
quarantines them based on real tool outcomes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

import aiosqlite

from neuralclaw.bus.neural_bus import Event, EventType, NeuralBus
from neuralclaw.config import DATA_DIR
from neuralclaw.cortex.reasoning.deliberate import ConfidenceEnvelope
from neuralclaw.skills.loader import load_skill_manifest
from neuralclaw.skills.paths import quarantine_skill_file, resolve_user_skills_dir


class EvolutionOrchestrator:
    """Controlled, persistent capability evolution loop."""

    FAILURE_THRESHOLD = 3
    PROMOTION_SUCCESSES = 2
    QUARANTINE_FAILURES = 2

    def __init__(
        self,
        *,
        bus: NeuralBus,
        registry: Any,
        forge: Any,
        scout: Any | None = None,
        policy_config: Any | None = None,
        db_path: str | Path | None = None,
        candidate_dir: str | Path | None = None,
        user_skills_dir: str | Path | None = None,
    ) -> None:
        self._bus = bus
        self._registry = registry
        self._forge = forge
        self._scout = scout
        self._policy_config = policy_config
        self._db_path = Path(db_path) if db_path is not None else DATA_DIR / "evolution.db"
        self._candidate_dir = Path(candidate_dir) if candidate_dir is not None else DATA_DIR / "evolution" / "candidates"
        self._user_skills_dir = resolve_user_skills_dir(user_skills_dir)
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._candidate_dir.mkdir(parents=True, exist_ok=True)
        self._user_skills_dir.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL,
                    query TEXT NOT NULL,
                    response TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    uncertainty TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS initiatives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    query TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    state TEXT NOT NULL,
                    skill_name TEXT NOT NULL DEFAULT '',
                    candidate_path TEXT NOT NULL DEFAULT '',
                    user_path TEXT NOT NULL DEFAULT '',
                    tools_json TEXT NOT NULL DEFAULT '[]',
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    probation_successes INTEGER NOT NULL DEFAULT 0,
                    probation_failures INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    promoted_at REAL
                )
                """
            )
            await db.commit()
        self._bus.subscribe(EventType.ACTION_COMPLETE, self._handle_action_complete)
        self._initialized = True

    async def close(self) -> None:
        if not self._initialized:
            return
        self._bus.unsubscribe(EventType.ACTION_COMPLETE, self._handle_action_complete)
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._tasks.clear()
        self._initialized = False

    async def record_response(self, query: str, envelope: ConfidenceEnvelope) -> None:
        """Record a possible capability gap from a live response."""
        if not self._should_capture_failure(query, envelope):
            return

        fingerprint = self._fingerprint(query)
        now = time.time()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO failures (
                    fingerprint, query, response, confidence, source, uncertainty, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fingerprint,
                    query,
                    envelope.response,
                    envelope.confidence,
                    envelope.source,
                    json.dumps(envelope.uncertainty_factors),
                    self._derive_failure_reason(envelope),
                    now,
                ),
            )
            cursor = await db.execute(
                "SELECT COUNT(*) FROM failures WHERE fingerprint = ?",
                (fingerprint,),
            )
            failure_count = int((await cursor.fetchone())[0])
            await db.execute(
                """
                INSERT INTO initiatives (
                    fingerprint, query, strategy, state, failure_count, created_at, updated_at
                ) VALUES (?, ?, ?, 'observed', ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    query = excluded.query,
                    failure_count = excluded.failure_count,
                    updated_at = excluded.updated_at
                """,
                (
                    fingerprint,
                    query,
                    self._choose_strategy(query),
                    failure_count,
                    now,
                    now,
                ),
            )
            await db.commit()

        if failure_count >= self.FAILURE_THRESHOLD:
            await self._maybe_schedule_initiative(fingerprint, query)

    async def list_initiatives(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT fingerprint, query, strategy, state, skill_name, tools_json,
                       failure_count, attempts, probation_successes, probation_failures,
                       last_error, candidate_path, user_path
                FROM initiatives
                ORDER BY updated_at DESC
                """
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def _maybe_schedule_initiative(self, fingerprint: str, query: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT state FROM initiatives WHERE fingerprint = ?",
                (fingerprint,),
            )
            row = await cursor.fetchone()
        if row and row[0] in {"planning", "candidate", "probation", "promoted"}:
            return

        task = asyncio.create_task(self._run_initiative(fingerprint, query))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_initiative(self, fingerprint: str, query: str) -> None:
        lock = self._locks.setdefault(fingerprint, asyncio.Lock())
        async with lock:
            async with aiosqlite.connect(self._db_path) as db:
                cursor = await db.execute(
                    "SELECT failure_count, strategy FROM initiatives WHERE fingerprint = ?",
                    (fingerprint,),
                )
                row = await cursor.fetchone()
                if not row or int(row[0]) < self.FAILURE_THRESHOLD:
                    return
                strategy = str(row[1] or self._choose_strategy(query))
                await db.execute(
                    """
                    UPDATE initiatives
                    SET state = 'planning', strategy = ?, attempts = attempts + 1, updated_at = ?
                    WHERE fingerprint = ?
                    """,
                    (strategy, time.time(), fingerprint),
                )
                await db.commit()

            try:
                forge_result = await self._acquire_candidate(query, strategy)
            except Exception as exc:
                await self._mark_initiative_failure(fingerprint, f"Acquisition failed: {exc}")
                return

            if not forge_result or not getattr(forge_result, "success", False):
                await self._mark_initiative_failure(
                    fingerprint,
                    getattr(forge_result, "error", None) or "Candidate acquisition failed",
                )
                return

            candidate_path = Path(forge_result.file_path)
            if not candidate_path.exists():
                await self._mark_initiative_failure(fingerprint, "Candidate skill file was not persisted")
                return

            manifest = forge_result.manifest or load_skill_manifest(candidate_path, module_prefix="_evolution_candidate")
            self._registry.hot_register(manifest, source="runtime")
            self._allowlist_tools(manifest)

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """
                    UPDATE initiatives
                    SET state = 'probation',
                        skill_name = ?,
                        candidate_path = ?,
                        tools_json = ?,
                        probation_successes = 0,
                        probation_failures = 0,
                        last_error = '',
                        updated_at = ?
                    WHERE fingerprint = ?
                    """,
                    (
                        manifest.name,
                        str(candidate_path),
                        json.dumps([tool.name for tool in manifest.tools]),
                        time.time(),
                        fingerprint,
                    ),
                )
                await db.commit()

            await self._bus.publish(
                EventType.SKILL_SYNTHESIZED,
                {
                    "name": manifest.name,
                    "success": True,
                    "state": "probation",
                    "tools": [tool.name for tool in manifest.tools],
                },
                source="evolution.orchestrator",
            )

    async def _handle_action_complete(self, event: Event) -> None:
        tool_name = str(event.data.get("skill") or "")
        if not tool_name:
            return

        initiative = await self._find_probationary_initiative(tool_name)
        if not initiative:
            return

        success = bool(event.data.get("success"))
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                f"""
                UPDATE initiatives
                SET probation_successes = probation_successes + ?,
                    probation_failures = probation_failures + ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    1 if success else 0,
                    0 if success else 1,
                    "" if success else str(event.data.get("error") or "probation tool failed"),
                    time.time(),
                    initiative["id"],
                ),
            )
            cursor = await db.execute(
                """
                SELECT probation_successes, probation_failures
                FROM initiatives
                WHERE id = ?
                """,
                (initiative["id"],),
            )
            counts = await cursor.fetchone()
            await db.commit()

        successes = int(counts[0])
        failures = int(counts[1])
        if successes >= self.PROMOTION_SUCCESSES:
            await self._promote_initiative(initiative["id"])
        elif failures >= self.QUARANTINE_FAILURES:
            await self._quarantine_initiative(
                initiative["id"],
                str(event.data.get("error") or "probation failures exceeded threshold"),
            )

    async def _promote_initiative(self, initiative_id: int) -> None:
        initiative = await self._get_initiative_by_id(initiative_id)
        if not initiative:
            return

        candidate_path = Path(initiative["candidate_path"])
        if not candidate_path.exists():
            await self._quarantine_initiative(initiative_id, "Candidate file missing during promotion")
            return

        user_path = self._user_skills_dir / candidate_path.name
        user_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate_path, user_path)
        manifest = load_skill_manifest(user_path, module_prefix="_evolution_promoted")
        self._registry.hot_register(manifest, source="user")
        self._allowlist_tools(manifest)

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                UPDATE initiatives
                SET state = 'promoted',
                    user_path = ?,
                    promoted_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (str(user_path), time.time(), time.time(), initiative_id),
            )
            await db.commit()

    async def _quarantine_initiative(self, initiative_id: int, reason: str) -> None:
        initiative = await self._get_initiative_by_id(initiative_id)
        if not initiative:
            return

        skill_name = str(initiative["skill_name"] or "")
        if skill_name:
            self._registry.unregister_skill(skill_name)

        quarantined_path = ""
        for raw_path in (initiative["user_path"], initiative["candidate_path"]):
            if raw_path:
                path = Path(raw_path)
                if path.exists():
                    quarantined_path = str(quarantine_skill_file(path, reason="invalid"))
                    break

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                UPDATE initiatives
                SET state = 'quarantined',
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    f"{reason}. Quarantined to {quarantined_path}" if quarantined_path else reason,
                    time.time(),
                    initiative_id,
                ),
            )
            await db.commit()

    async def _acquire_candidate(self, query: str, strategy: str) -> Any:
        if strategy == "scout" and self._scout is not None:
            scout_result = await self._scout.scout(
                query,
                activate=False,
                skills_dir=self._candidate_dir,
                registry_source="candidate",
            )
            return scout_result.forge_result if scout_result and scout_result.forge_result else scout_result

        return await self._forge.forge_from_description(
            query,
            use_case=query,
            activate=False,
            skills_dir=self._candidate_dir,
            registry_source="candidate",
        )

    async def _mark_initiative_failure(self, fingerprint: str, error: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                UPDATE initiatives
                SET state = 'blocked',
                    last_error = ?,
                    updated_at = ?
                WHERE fingerprint = ?
                """,
                (error, time.time(), fingerprint),
            )
            await db.commit()

    async def _find_probationary_initiative(self, tool_name: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT *
                FROM initiatives
                WHERE state = 'probation'
                """
            )
            rows = await cursor.fetchall()
        for row in rows:
            try:
                tools = json.loads(row["tools_json"] or "[]")
            except Exception:
                tools = []
            if tool_name in tools:
                return dict(row)
        return None

    async def _get_initiative_by_id(self, initiative_id: int) -> dict[str, Any] | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM initiatives WHERE id = ?",
                (initiative_id,),
            )
            row = await cursor.fetchone()
        return dict(row) if row else None

    def _allowlist_tools(self, manifest: Any) -> None:
        if not self._policy_config or not hasattr(self._policy_config, "allowed_tools"):
            return
        for tool in getattr(manifest, "tools", []):
            if tool.name not in self._policy_config.allowed_tools:
                self._policy_config.allowed_tools.append(tool.name)

    def _choose_strategy(self, query: str) -> str:
        lowered = query.lower()
        scout_markers = (
            "github", "repo", "repository", "library", "package", "pypi", "npm",
            "api", "openapi", "graphql", "mcp",
        )
        if any(marker in lowered for marker in scout_markers) and self._scout is not None:
            return "scout"
        return "forge"

    def _should_capture_failure(self, query: str, envelope: ConfidenceEnvelope) -> bool:
        if not query.strip():
            return False
        if envelope.source == "tool_verified" and envelope.confidence >= 0.75 and not envelope.uncertainty_factors:
            return False
        lowered = envelope.response.lower()
        failure_markers = (
            "can't", "cannot", "couldn't", "not available", "not supported",
            "unable", "failed", "encountered an error", "missing", "don't have",
        )
        if any(marker in lowered for marker in failure_markers):
            return True
        if envelope.confidence < 0.55:
            return True
        return envelope.source != "tool_verified" and bool(envelope.uncertainty_factors)

    def _derive_failure_reason(self, envelope: ConfidenceEnvelope) -> str:
        if envelope.uncertainty_factors:
            return "; ".join(envelope.uncertainty_factors[:3])
        return f"low_confidence:{envelope.confidence:.2f}:{envelope.source}"

    def _fingerprint(self, query: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
        tokens = normalized.split()
        compact = " ".join(tokens[:12])
        return hashlib.sha256(compact.encode("utf-8")).hexdigest()[:16]
