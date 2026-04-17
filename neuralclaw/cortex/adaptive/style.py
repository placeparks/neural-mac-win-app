"""Style Adaptation v2 — learns and applies per-channel/user communication preferences."""

from __future__ import annotations
import json, time, hashlib, re
from collections import Counter
from typing import Any
from pathlib import Path
import aiosqlite

class StyleAdapter:
    """Learns communication style preferences from observed interactions
    and generates prompt modifiers to adapt LLM output accordingly."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS style_profiles (
                    profile_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    tone TEXT NOT NULL DEFAULT 'neutral',
                    verbosity TEXT NOT NULL DEFAULT 'moderate',
                    formality TEXT NOT NULL DEFAULT 'neutral',
                    decision_style TEXT NOT NULL DEFAULT 'balanced',
                    jargon_json TEXT NOT NULL DEFAULT '[]',
                    preferred_format TEXT NOT NULL DEFAULT 'prose',
                    custom_rules_json TEXT NOT NULL DEFAULT '[]',
                    observation_count INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_sp_scope ON style_profiles(scope, scope_id);

                CREATE TABLE IF NOT EXISTS style_observations (
                    obs_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    detected_tone TEXT,
                    detected_verbosity TEXT,
                    detected_formality TEXT,
                    jargon_found_json TEXT,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_so_scope ON style_observations(scope, scope_id);
            """)
        self._initialized = True

    async def observe_message(self, scope: str, scope_id: str, message: str) -> None:
        """Observe a user message to learn style preferences.

        scope: "channel" | "user" | "project"
        scope_id: channel name, user id, or project id
        """
        await self.initialize()
        if not message or len(message) < 10:
            return

        tone = self._detect_tone(message)
        verbosity = self._detect_verbosity(message)
        formality = self._detect_formality(message)
        jargon = self._extract_jargon(message)

        obs_id = f"sobs-{hashlib.sha256(f'{scope}:{scope_id}:{time.time_ns()}'.encode()).hexdigest()[:12]}"
        now = time.time()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                INSERT INTO style_observations
                    (obs_id, scope, scope_id, message_text, detected_tone, detected_verbosity,
                     detected_formality, jargon_found_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (obs_id, scope, scope_id, message[:500], tone, verbosity, formality,
                  json.dumps(jargon), now))
            await db.commit()

        # Update profile with running averages
        await self._update_profile(scope, scope_id)

    async def _update_profile(self, scope: str, scope_id: str) -> None:
        """Recompute style profile from recent observations."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""
                SELECT detected_tone, detected_verbosity, detected_formality, jargon_found_json
                FROM style_observations WHERE scope = ? AND scope_id = ?
                ORDER BY created_at DESC LIMIT 30
            """, (scope, scope_id))
            rows = await cur.fetchall()

        if not rows:
            return

        tones = Counter(r["detected_tone"] for r in rows if r["detected_tone"])
        verbosities = Counter(r["detected_verbosity"] for r in rows if r["detected_verbosity"])
        formalities = Counter(r["detected_formality"] for r in rows if r["detected_formality"])
        all_jargon: list[str] = []
        for r in rows:
            try:
                all_jargon.extend(json.loads(r["jargon_found_json"] or "[]"))
            except Exception:
                pass

        dominant_tone = tones.most_common(1)[0][0] if tones else "neutral"
        dominant_verbosity = verbosities.most_common(1)[0][0] if verbosities else "moderate"
        dominant_formality = formalities.most_common(1)[0][0] if formalities else "neutral"
        top_jargon = [word for word, _ in Counter(all_jargon).most_common(20)]

        # Detect decision style from verbosity + formality
        decision_style = "balanced"
        if dominant_verbosity == "brief" and dominant_formality in ("informal", "neutral"):
            decision_style = "brief"
        elif dominant_verbosity == "detailed" and dominant_formality == "formal":
            decision_style = "analytical"

        profile_id = f"profile-{hashlib.sha256(f'{scope}:{scope_id}'.encode()).hexdigest()[:12]}"
        now = time.time()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                INSERT INTO style_profiles
                    (profile_id, scope, scope_id, tone, verbosity, formality, decision_style,
                     jargon_json, observation_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, scope_id) DO UPDATE SET
                    tone = excluded.tone, verbosity = excluded.verbosity,
                    formality = excluded.formality, decision_style = excluded.decision_style,
                    jargon_json = excluded.jargon_json,
                    observation_count = observation_count + 1,
                    updated_at = excluded.updated_at
            """, (profile_id, scope, scope_id, dominant_tone, dominant_verbosity,
                  dominant_formality, decision_style, json.dumps(top_jargon),
                  len(rows), now, now))
            await db.commit()

    async def get_prompt_modifier(self, scope: str, scope_id: str) -> str:
        """Generate a prompt section that adapts the LLM's style based on the learned profile."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""
                SELECT * FROM style_profiles WHERE scope = ? AND scope_id = ?
            """, (scope, scope_id))
            row = await cur.fetchone()

        if not row or row["observation_count"] < 3:
            return ""  # Not enough data to adapt

        parts: list[str] = ["## Communication Style Preferences"]

        tone = row["tone"]
        if tone != "neutral":
            parts.append(f"- Tone: Be {tone} in your responses")

        verbosity = row["verbosity"]
        if verbosity == "brief":
            parts.append("- Length: Keep responses concise and to-the-point. Prefer bullet points over paragraphs.")
        elif verbosity == "detailed":
            parts.append("- Length: Provide thorough, detailed explanations. Include context and reasoning.")

        formality = row["formality"]
        if formality == "formal":
            parts.append("- Formality: Use professional, formal language. Avoid slang and contractions.")
        elif formality == "informal":
            parts.append("- Formality: Use casual, friendly language. Contractions are fine.")

        decision_style = row["decision_style"]
        if decision_style == "brief":
            parts.append("- Decision style: Give direct recommendations quickly. Skip extensive analysis unless asked.")
        elif decision_style == "analytical":
            parts.append("- Decision style: Present options with pros/cons analysis before recommending.")

        try:
            jargon = json.loads(row["jargon_json"] or "[]")
            if jargon:
                parts.append(f"- Domain terms the user commonly uses: {', '.join(jargon[:10])}")
        except Exception:
            pass

        try:
            custom_rules = json.loads(row["custom_rules_json"] or "[]")
            for rule in custom_rules[:5]:
                parts.append(f"- {rule}")
        except Exception:
            pass

        if len(parts) <= 1:
            return ""
        return "\n".join(parts)

    async def get_profile(self, scope: str, scope_id: str) -> dict | None:
        """Get the current style profile."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""
                SELECT * FROM style_profiles WHERE scope = ? AND scope_id = ?
            """, (scope, scope_id))
            row = await cur.fetchone()
        if not row:
            return None
        return {
            "profile_id": row["profile_id"],
            "scope": row["scope"],
            "scope_id": row["scope_id"],
            "tone": row["tone"],
            "verbosity": row["verbosity"],
            "formality": row["formality"],
            "decision_style": row["decision_style"],
            "jargon": json.loads(row["jargon_json"] or "[]"),
            "preferred_format": row["preferred_format"],
            "custom_rules": json.loads(row["custom_rules_json"] or "[]"),
            "observation_count": row["observation_count"],
            "updated_at": row["updated_at"],
        }

    async def set_custom_rule(self, scope: str, scope_id: str, rule: str) -> dict:
        """Add a custom style rule."""
        await self.initialize()
        profile = await self.get_profile(scope, scope_id)
        rules = profile.get("custom_rules", []) if profile else []
        rules.append(rule)
        rules = rules[-10:]  # Keep last 10

        profile_id = f"profile-{hashlib.sha256(f'{scope}:{scope_id}'.encode()).hexdigest()[:12]}"
        now = time.time()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                INSERT INTO style_profiles
                    (profile_id, scope, scope_id, custom_rules_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, scope_id) DO UPDATE SET
                    custom_rules_json = excluded.custom_rules_json,
                    updated_at = excluded.updated_at
            """, (profile_id, scope, scope_id, json.dumps(rules), now, now))
            await db.commit()
        return {"ok": True, "rules": rules}

    async def list_profiles(self) -> list[dict]:
        """List all style profiles."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM style_profiles ORDER BY updated_at DESC")
            rows = await cur.fetchall()
        return [{
            "profile_id": r["profile_id"],
            "scope": r["scope"],
            "scope_id": r["scope_id"],
            "tone": r["tone"],
            "verbosity": r["verbosity"],
            "formality": r["formality"],
            "decision_style": r["decision_style"],
            "observation_count": r["observation_count"],
            "updated_at": r["updated_at"],
        } for r in rows]

    # -- Detection heuristics --

    @staticmethod
    def _detect_tone(text: str) -> str:
        lower = text.lower()
        positive = sum(1 for w in ("thanks", "great", "awesome", "love", "excellent", "perfect", "nice") if w in lower)
        negative = sum(1 for w in ("bad", "wrong", "terrible", "hate", "awful", "broken", "fix") if w in lower)
        if positive > negative + 1:
            return "friendly"
        if negative > positive + 1:
            return "direct"
        return "neutral"

    @staticmethod
    def _detect_verbosity(text: str) -> str:
        word_count = len(text.split())
        if word_count < 15:
            return "brief"
        if word_count > 60:
            return "detailed"
        return "moderate"

    @staticmethod
    def _detect_formality(text: str) -> str:
        lower = text.lower()
        informal_markers = sum(1 for w in ("lol", "btw", "gonna", "wanna", "u ", "ur ", "thx", "plz", "pls", "hey", "yo") if w in lower)
        formal_markers = sum(1 for w in ("please", "kindly", "regarding", "pursuant", "hereby", "respectfully", "accordingly") if w in lower)
        contractions = len(re.findall(r"\w+n't|\w+'re|\w+'ve|\w+'ll|\w+'d", lower))
        informal_markers += min(contractions, 3)
        if informal_markers > formal_markers + 2:
            return "informal"
        if formal_markers > informal_markers + 1:
            return "formal"
        return "neutral"

    @staticmethod
    def _extract_jargon(text: str) -> list[str]:
        """Extract potential domain jargon (unusual/technical words)."""
        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b', text)
        common_words = {
            "this", "that", "with", "from", "have", "will", "been", "were", "they",
            "what", "when", "where", "which", "there", "their", "about", "would",
            "could", "should", "these", "those", "other", "after", "before", "your",
            "some", "them", "than", "just", "like", "also", "into", "over", "such",
            "then", "each", "only", "very", "make", "made", "more", "most", "much",
            "many", "well", "back", "even", "here", "still", "every", "want", "need",
            "know", "think", "good", "help", "please", "thanks",
        }
        jargon = [w for w in words if w.lower() not in common_words and not w.lower().startswith("http")]
        # Filter to words that look technical
        return [w for w in jargon if any(c in w for c in ("_", "A", "B", "C")) or len(w) >= 6][:10]
