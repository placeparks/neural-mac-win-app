"""
Persistent user identity and mental model store.

Tracks a canonical user model across channels and synthesizes prompt-facing
context from stored interaction history plus semantic memory.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

import aiosqlite

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.evolution.calibrator import BehavioralCalibrator
from neuralclaw.cortex.memory.db import DBPool
from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.semantic import SemanticMemory

_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "build", "by", "can", "do",
    "for", "from", "get", "help", "how", "i", "in", "is", "it", "me", "my",
    "of", "on", "or", "please", "project", "that", "the", "this", "to",
    "use", "want", "we", "with", "you",
}


@dataclass
class UserModel:
    user_id: str
    display_name: str
    platform_aliases: dict[str, str] = field(default_factory=dict)
    communication_style: dict[str, Any] = field(default_factory=dict)
    active_projects: list[str] = field(default_factory=list)
    expertise_domains: list[str] = field(default_factory=list)
    language: str = "en"
    timezone: str = ""
    preferences: dict[str, Any] = field(default_factory=dict)
    last_seen: float = 0.0
    first_seen: float = 0.0
    session_count: int = 0
    message_count: int = 0
    notes: str = ""


class UserIdentityStore:
    """SQLite-backed persistent user identity store."""

    def __init__(
        self,
        db_path: str,
        bus: NeuralBus | None = None,
        episodic: EpisodicMemory | None = None,
        semantic: SemanticMemory | None = None,
        calibrator: BehavioralCalibrator | None = None,
        db_pool: DBPool | None = None,
    ) -> None:
        self._db_path = db_path
        self._bus = bus
        self._episodic = episodic
        self._semantic = semantic
        self._calibrator = calibrator
        self._db: aiosqlite.Connection | DBPool | None = None
        self._db_pool = db_pool
        self._owns_db = db_pool is None

    def set_calibrator(self, calibrator: BehavioralCalibrator | None) -> None:
        self._calibrator = calibrator

    async def initialize(self) -> None:
        try:
            if self._db_pool:
                await self._db_pool.initialize()
                self._db = self._db_pool
            else:
                self._db = await aiosqlite.connect(self._db_path)
                await self._db.execute("PRAGMA journal_mode=WAL")
                await self._db.execute("PRAGMA foreign_keys=ON")
            await self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_models (
                    user_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    platform_aliases_json TEXT NOT NULL DEFAULT '{}',
                    communication_style_json TEXT NOT NULL DEFAULT '{}',
                    active_projects_json TEXT NOT NULL DEFAULT '[]',
                    expertise_domains_json TEXT NOT NULL DEFAULT '[]',
                    language TEXT NOT NULL DEFAULT 'en',
                    timezone TEXT NOT NULL DEFAULT '',
                    preferences_json TEXT NOT NULL DEFAULT '{}',
                    last_seen REAL NOT NULL DEFAULT 0,
                    first_seen REAL NOT NULL DEFAULT 0,
                    session_count INTEGER NOT NULL DEFAULT 0,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS user_aliases (
                    platform TEXT NOT NULL,
                    platform_user_id TEXT NOT NULL,
                    user_id TEXT NOT NULL REFERENCES user_models(user_id) ON DELETE CASCADE,
                    display_name TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL DEFAULT (unixepoch('now')),
                    PRIMARY KEY (platform, platform_user_id)
                );
                """
            )
            await self._db.commit()
        except Exception as exc:
            await self._publish_error("initialize", exc)

    async def get_or_create(
        self,
        platform: str,
        platform_user_id: str,
        display_name: str,
    ) -> UserModel:
        """Resolve a canonical user or create one if absent."""
        if not self._db:
            await self._publish_error("get_or_create", RuntimeError("Identity store is not initialized"))
            return UserModel(user_id=self._canonical_id(platform, platform_user_id), display_name=display_name)

        try:
            now = time.time()
            rows = await self._db.execute_fetchall(
                """
                SELECT m.user_id, m.display_name, m.platform_aliases_json,
                       m.communication_style_json, m.active_projects_json,
                       m.expertise_domains_json, m.language, m.timezone,
                       m.preferences_json, m.last_seen, m.first_seen,
                       m.session_count, m.message_count, m.notes
                FROM user_aliases a
                JOIN user_models m ON m.user_id = a.user_id
                WHERE a.platform = ? AND a.platform_user_id = ?
                """,
                (platform, platform_user_id),
            )

            if rows:
                model = self._row_to_model(rows[0])
                updates = {
                    "display_name": display_name or model.display_name,
                    "last_seen": now,
                    "message_count": model.message_count + 1,
                }
                await self.update(model.user_id, updates)
                return await self.get(model.user_id) or model

            user_id = self._canonical_id(platform, platform_user_id)
            model = UserModel(
                user_id=user_id,
                display_name=display_name or platform_user_id,
                platform_aliases={platform: platform_user_id},
                first_seen=now,
                last_seen=now,
                session_count=1,
                message_count=1,
            )

            await self._db.execute(
                """
                INSERT OR REPLACE INTO user_models (
                    user_id, display_name, platform_aliases_json, communication_style_json,
                    active_projects_json, expertise_domains_json, language, timezone,
                    preferences_json, last_seen, first_seen, session_count, message_count, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model.user_id,
                    model.display_name,
                    json.dumps(model.platform_aliases),
                    json.dumps(model.communication_style),
                    json.dumps(model.active_projects),
                    json.dumps(model.expertise_domains),
                    model.language,
                    model.timezone,
                    json.dumps(model.preferences),
                    model.last_seen,
                    model.first_seen,
                    model.session_count,
                    model.message_count,
                    model.notes,
                ),
            )
            await self._db.execute(
                """
                INSERT OR REPLACE INTO user_aliases (platform, platform_user_id, user_id, display_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (platform, platform_user_id, user_id, model.display_name, now),
            )
            await self._db.commit()
            await self._publish_state("created", model)
            return model
        except Exception as exc:
            await self._publish_error("get_or_create", exc)
            return UserModel(user_id=self._canonical_id(platform, platform_user_id), display_name=display_name)

    async def get(self, user_id: str) -> UserModel | None:
        if not self._db:
            return None
        try:
            rows = await self._db.execute_fetchall(
                """
                SELECT user_id, display_name, platform_aliases_json,
                       communication_style_json, active_projects_json,
                       expertise_domains_json, language, timezone,
                       preferences_json, last_seen, first_seen,
                       session_count, message_count, notes
                FROM user_models WHERE user_id = ?
                """,
                (user_id,),
            )
            return self._row_to_model(rows[0]) if rows else None
        except Exception as exc:
            await self._publish_error("get", exc)
            return None

    async def update(self, user_id: str, updates: dict[str, Any]) -> None:
        """Merge updates into an existing user model."""
        if not self._db:
            await self._publish_error("update", RuntimeError("Identity store is not initialized"))
            return

        try:
            current = await self.get(user_id)
            if not current:
                return

            merged = asdict(current)
            for key, value in updates.items():
                if key not in merged or value is None:
                    continue
                if isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key] = {**merged[key], **value}
                elif isinstance(merged[key], list) and isinstance(value, list):
                    merged[key] = list(dict.fromkeys([*merged[key], *value]))
                else:
                    merged[key] = value

            model = UserModel(**merged)
            await self._db.execute(
                """
                UPDATE user_models
                SET display_name = ?, platform_aliases_json = ?, communication_style_json = ?,
                    active_projects_json = ?, expertise_domains_json = ?, language = ?,
                    timezone = ?, preferences_json = ?, last_seen = ?, first_seen = ?,
                    session_count = ?, message_count = ?, notes = ?
                WHERE user_id = ?
                """,
                (
                    model.display_name,
                    json.dumps(model.platform_aliases),
                    json.dumps(model.communication_style),
                    json.dumps(model.active_projects),
                    json.dumps(model.expertise_domains),
                    model.language,
                    model.timezone,
                    json.dumps(model.preferences),
                    model.last_seen,
                    model.first_seen,
                    model.session_count,
                    model.message_count,
                    model.notes,
                    model.user_id,
                ),
            )
            await self._db.commit()
            await self._publish_state("updated", model)
        except Exception as exc:
            await self._publish_error("update", exc)

    async def merge_aliases(
        self,
        canonical_id: str,
        platform: str,
        platform_user_id: str,
    ) -> None:
        """Attach an additional platform identity to a canonical user."""
        if not self._db:
            await self._publish_error("merge_aliases", RuntimeError("Identity store is not initialized"))
            return

        try:
            model = await self.get(canonical_id)
            if not model:
                return

            model.platform_aliases[platform] = platform_user_id
            await self._db.execute(
                """
                INSERT OR REPLACE INTO user_aliases (platform, platform_user_id, user_id, display_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (platform, platform_user_id, canonical_id, model.display_name, time.time()),
            )
            await self.update(canonical_id, {"platform_aliases": model.platform_aliases})
        except Exception as exc:
            await self._publish_error("merge_aliases", exc)

    async def synthesize_model(self, user_id: str) -> UserModel:
        """Rebuild derived user fields from memories and calibrator state."""
        model = await self.get(user_id)
        if not model:
            return UserModel(user_id=user_id, display_name="User")

        try:
            if self._episodic:
                episodes = await self._episodic.get_recent_for_user(user_id, limit=300)
                user_texts: list[str] = [ep.content for ep in episodes]

                if user_texts:
                    model.active_projects = self._extract_topics(user_texts, limit=5)
                    model.language = self._detect_language(user_texts)

                    if self._semantic:
                        model.expertise_domains = await self._infer_expertise_domains(user_texts)

            if self._calibrator:
                prefs = self._calibrator.preferences
                model.communication_style = {
                    "formality": prefs.formality,
                    "verbosity": prefs.verbosity,
                    "proactiveness": prefs.proactiveness,
                    "emoji_usage": prefs.emoji_usage,
                }
                model.preferences = {
                    **model.preferences,
                    "custom_rules": prefs.custom_rules,
                    "code_style": prefs.code_style,
                }
                if prefs.timezone:
                    model.timezone = prefs.timezone

            await self.update(
                user_id,
                {
                    "active_projects": model.active_projects,
                    "expertise_domains": model.expertise_domains,
                    "communication_style": model.communication_style,
                    "preferences": model.preferences,
                    "language": model.language,
                    "timezone": model.timezone,
                },
            )
        except Exception as exc:
            await self._publish_error("synthesize_model", exc)

        refreshed = await self.get(user_id)
        return refreshed or model

    async def to_prompt_section(self, user_id: str) -> str:
        """Render the user model as system prompt context."""
        try:
            model = await self.synthesize_model(user_id)
            parts = ["## Who I'm Talking To", f"- Name: {model.display_name}"]
            if model.language:
                parts.append(f"- Language: {model.language}")
            if model.timezone:
                parts.append(f"- Timezone: {model.timezone}")
            if model.active_projects:
                parts.append(f"- Active Projects: {', '.join(model.active_projects[:5])}")
            if model.expertise_domains:
                parts.append(f"- Expertise Domains: {', '.join(model.expertise_domains[:5])}")
            if model.communication_style:
                style_bits = []
                for key, value in model.communication_style.items():
                    if isinstance(value, float):
                        style_bits.append(f"{key}={value:.2f}")
                    else:
                        style_bits.append(f"{key}={value}")
                if style_bits:
                    parts.append(f"- Style: {', '.join(style_bits)}")
            custom_rules = model.preferences.get("custom_rules", []) if isinstance(model.preferences, dict) else []
            if custom_rules:
                parts.append(f"- Preferences: {'; '.join(custom_rules[:4])}")
            if model.notes:
                parts.append(f"- Notes: {model.notes[:250]}")

            section = "\n".join(parts)
            if self._bus:
                await self._bus.publish(
                    EventType.MEMORY_RETRIEVED,
                    {
                        "component": "identity_store",
                        "user_id": user_id,
                        "chars": len(section),
                    },
                    source="memory.identity",
                )
            return section
        except Exception as exc:
            await self._publish_error("to_prompt_section", exc)
            return ""

    async def close(self) -> None:
        if self._db and self._owns_db:
            await self._db.close()
        self._db = None

    async def _infer_expertise_domains(self, texts: list[str]) -> list[str]:
        if not self._semantic:
            return []

        counts: Counter[str] = Counter()
        for token in self._extract_topics(texts, limit=12):
            entities = await self._semantic.search_entities(token, limit=5)
            for entity in entities:
                if entity.entity_type and entity.entity_type != "unknown":
                    counts[entity.entity_type] += 1

        return [name for name, _count in counts.most_common(5)]

    def _extract_topics(self, texts: list[str], limit: int = 5) -> list[str]:
        counter: Counter[str] = Counter()
        for text in texts:
            cleaned = re.sub(r"^[^:]+:\s*", "", text)
            tokens = re.findall(r"[a-z0-9][a-z0-9_\-]{2,}", cleaned.lower())
            for token in tokens:
                if token not in _STOP_WORDS:
                    counter[token] += 1
        return [token for token, _count in counter.most_common(limit)]

    def _detect_language(self, texts: list[str]) -> str:
        joined = " ".join(texts)
        if re.search(r"[\u0600-\u06FF]", joined):
            return "ur"
        return "en"

    def _canonical_id(self, platform: str, platform_user_id: str) -> str:
        digest = hashlib.sha256(f"{platform}:{platform_user_id}".encode()).hexdigest()
        return digest[:16]

    def _row_to_model(self, row: tuple[Any, ...]) -> UserModel:
        return UserModel(
            user_id=row[0],
            display_name=row[1],
            platform_aliases=json.loads(row[2]) if row[2] else {},
            communication_style=json.loads(row[3]) if row[3] else {},
            active_projects=json.loads(row[4]) if row[4] else [],
            expertise_domains=json.loads(row[5]) if row[5] else [],
            language=row[6] or "en",
            timezone=row[7] or "",
            preferences=json.loads(row[8]) if row[8] else {},
            last_seen=float(row[9] or 0.0),
            first_seen=float(row[10] or 0.0),
            session_count=int(row[11] or 0),
            message_count=int(row[12] or 0),
            notes=row[13] or "",
        )

    async def _publish_state(self, action: str, model: UserModel) -> None:
        if self._bus:
            await self._bus.publish(
                EventType.MEMORY_STORED,
                {
                    "component": "identity_store",
                    "action": action,
                    "user_id": model.user_id,
                    "display_name": model.display_name,
                },
                source="memory.identity",
            )

    async def _publish_error(self, operation: str, exc: Exception) -> None:
        if self._bus:
            await self._bus.publish(
                EventType.ERROR,
                {
                    "component": "identity_store",
                    "operation": operation,
                    "error": str(exc),
                },
                source="memory.identity",
            )
