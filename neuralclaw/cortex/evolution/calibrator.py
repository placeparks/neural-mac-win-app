"""
Behavioral Calibrator — Adaptive personality engine.

Tracks user corrections, satisfaction signals, and interaction patterns
to continuously adjust the agent's behavior:
- Communication style (formal ↔ casual)
- Detail level (concise ↔ verbose)
- Proactiveness (wait for instructions ↔ anticipate needs)
- Decision thresholds (when to ask vs. act)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.config import DATA_DIR


# ---------------------------------------------------------------------------
# Preference model
# ---------------------------------------------------------------------------

@dataclass
class UserPreferences:
    """Learned user preferences."""
    formality: float = 0.5        # 0=casual, 1=formal
    verbosity: float = 0.5        # 0=concise, 1=verbose
    proactiveness: float = 0.5    # 0=reactive, 1=proactive
    emoji_usage: float = 0.5      # 0=none, 1=frequent
    code_style: str = "python"    # Preferred language
    timezone: str = ""
    custom_rules: list[str] = field(default_factory=list)

    def to_persona_modifiers(self) -> str:
        """Generate persona modifiers from preferences."""
        modifiers = []

        if self.formality > 0.7:
            modifiers.append("Maintain a professional, formal tone.")
        elif self.formality < 0.3:
            modifiers.append("Use a casual, friendly tone.")

        if self.verbosity > 0.7:
            modifiers.append("Provide detailed, thorough explanations.")
        elif self.verbosity < 0.3:
            modifiers.append("Be concise and to-the-point.")

        if self.proactiveness > 0.7:
            modifiers.append("Anticipate the user's needs and suggest related actions.")
        elif self.proactiveness < 0.3:
            modifiers.append("Wait for explicit instructions before taking action.")

        if self.emoji_usage < 0.2:
            modifiers.append("Minimize emoji usage.")
        elif self.emoji_usage > 0.8:
            modifiers.append("Use emojis to make responses more engaging.")

        for rule in self.custom_rules:
            modifiers.append(rule)

        return "\n".join(modifiers) if modifiers else ""


# ---------------------------------------------------------------------------
# Interaction signal
# ---------------------------------------------------------------------------

@dataclass
class InteractionSignal:
    """A signal from a user interaction for calibration."""
    timestamp: float = field(default_factory=time.time)
    signal_type: str = ""       # correction, satisfaction, re-ask, short_response, long_response
    content: str = ""
    delta: float = 0.0          # Magnitude of adjustment (-1 to 1)


# ---------------------------------------------------------------------------
# Behavioral Calibrator
# ---------------------------------------------------------------------------

class BehavioralCalibrator:
    """
    Learns user preferences from interaction patterns.

    Tracks:
    - Explicit corrections ("be more concise", "use less emoji")
    - Implicit signals (re-asking → didn't understand, short replies → wants concise)
    - Feedback patterns over time
    """

    LEARNING_RATE = 0.05  # How fast preferences adjust

    def __init__(
        self,
        bus: NeuralBus | None = None,
        db_path: str | None = None,
    ) -> None:
        self._bus = bus
        self._db_path = db_path or str(DATA_DIR / "calibration.db")
        self._db: aiosqlite.Connection | None = None
        self._preferences = UserPreferences()
        self._signals: list[InteractionSignal] = []

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL DEFAULT (unixepoch('now'))
            );

            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_type TEXT NOT NULL,
                content TEXT DEFAULT '',
                delta REAL DEFAULT 0,
                timestamp REAL DEFAULT (unixepoch('now'))
            );
        """)
        await self._db.commit()

        # Load existing preferences
        await self._load_preferences()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    @property
    def preferences(self) -> UserPreferences:
        return self._preferences

    async def process_correction(self, correction: str) -> None:
        """Process an explicit user correction."""
        correction_lower = correction.lower()

        # Detect correction type
        adjustments: list[tuple[str, float]] = []

        if any(w in correction_lower for w in ("concise", "shorter", "brief", "less")):
            adjustments.append(("verbosity", -0.15))
        elif any(w in correction_lower for w in ("detail", "more", "elaborate", "explain")):
            adjustments.append(("verbosity", 0.15))

        if any(w in correction_lower for w in ("formal", "professional")):
            adjustments.append(("formality", 0.15))
        elif any(w in correction_lower for w in ("casual", "relax", "chill")):
            adjustments.append(("formality", -0.15))

        if any(w in correction_lower for w in ("no emoji", "stop emoji", "fewer emoji")):
            adjustments.append(("emoji_usage", -0.2))
        elif any(w in correction_lower for w in ("more emoji", "use emoji")):
            adjustments.append(("emoji_usage", 0.2))

        for attr, delta in adjustments:
            current = getattr(self._preferences, attr)
            new_val = max(0.0, min(1.0, current + delta))
            setattr(self._preferences, attr, round(new_val, 3))

            await self._record_signal("correction", correction, delta)

        # Check for custom rules
        if correction_lower.startswith("always ") or correction_lower.startswith("never "):
            self._preferences.custom_rules.append(correction)
            if len(self._preferences.custom_rules) > 20:
                self._preferences.custom_rules = self._preferences.custom_rules[-20:]

        await self._save_preferences()

        if self._bus and adjustments:
            await self._bus.publish(
                EventType.EVOLUTION_CALIBRATED,
                {
                    "correction": correction[:200],
                    "adjustments": {attr: delta for attr, delta in adjustments},
                    "preferences": {
                        "formality": self._preferences.formality,
                        "verbosity": self._preferences.verbosity,
                        "emoji_usage": self._preferences.emoji_usage,
                    },
                },
                source="evolution.calibrator",
            )

    async def process_implicit_signal(
        self,
        user_msg_length: int,
        agent_msg_length: int,
        is_reask: bool = False,
    ) -> None:
        """Process implicit interaction signals."""
        # Re-asks suggest the agent wasn't clear enough
        if is_reask:
            self._preferences.verbosity = min(
                1.0, self._preferences.verbosity + self.LEARNING_RATE
            )
            await self._record_signal("re_ask", "", self.LEARNING_RATE)

        # Short user messages + long responses → maybe too verbose
        if user_msg_length < 20 and agent_msg_length > 500:
            self._preferences.verbosity = max(
                0.0, self._preferences.verbosity - self.LEARNING_RATE * 0.5
            )

        # Long user messages suggest they want detailed responses
        if user_msg_length > 200:
            self._preferences.verbosity = min(
                1.0, self._preferences.verbosity + self.LEARNING_RATE * 0.3
            )

        await self._save_preferences()

    async def _record_signal(self, signal_type: str, content: str, delta: float) -> None:
        if self._db:
            await self._db.execute(
                "INSERT INTO signals (signal_type, content, delta, timestamp) VALUES (?, ?, ?, ?)",
                (signal_type, content[:500], delta, time.time()),
            )
            await self._db.commit()

    async def _save_preferences(self) -> None:
        if not self._db:
            return

        prefs = {
            "formality": self._preferences.formality,
            "verbosity": self._preferences.verbosity,
            "proactiveness": self._preferences.proactiveness,
            "emoji_usage": self._preferences.emoji_usage,
            "code_style": self._preferences.code_style,
            "timezone": self._preferences.timezone,
            "custom_rules": json.dumps(self._preferences.custom_rules),
        }

        for key, value in prefs.items():
            await self._db.execute(
                "INSERT OR REPLACE INTO preferences (key, value, updated_at) VALUES (?, ?, ?)",
                (key, str(value), time.time()),
            )
        await self._db.commit()

    async def _load_preferences(self) -> None:
        if not self._db:
            return

        rows = await self._db.execute_fetchall("SELECT key, value FROM preferences")
        for key, value in rows:
            if key == "custom_rules":
                try:
                    self._preferences.custom_rules = json.loads(value)
                except json.JSONDecodeError:
                    pass
            elif key in ("formality", "verbosity", "proactiveness", "emoji_usage"):
                try:
                    setattr(self._preferences, key, float(value))
                except ValueError:
                    pass
            elif key in ("code_style", "timezone"):
                setattr(self._preferences, key, value)
