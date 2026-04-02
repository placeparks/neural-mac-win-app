"""
Fast Path — Reflexive responses without LLM call.

For simple, well-understood patterns. Uses cached knowledge and
heuristics to respond in <100ms without burning API credits.
Falls through to the deliberative path when it can't handle a request.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.memory.retrieval import MemoryContext
from neuralclaw.cortex.perception.intake import Signal


# ---------------------------------------------------------------------------
# Fast path result
# ---------------------------------------------------------------------------

@dataclass
class FastPathResult:
    """Result from the fast path, or None if no fast path available."""
    content: str
    confidence: float
    source: str = "fast_path"


# ---------------------------------------------------------------------------
# Fast path patterns
# ---------------------------------------------------------------------------

_GREETING_PATTERNS = {
    "hello", "hi", "hey", "howdy", "greetings", "good morning",
    "good afternoon", "good evening", "yo", "sup", "hola",
    "what's up", "whats up",
}

_FAREWELL_PATTERNS = {
    "bye", "goodbye", "see you", "see ya", "later", "goodnight",
    "good night", "cya", "peace", "take care",
}

_IDENTITY_PATTERNS = {
    "who are you", "what are you", "what's your name",
    "whats your name", "introduce yourself",
}

_TIME_PATTERNS = {
    "what time is it", "whats the time", "what's the time",
    "current time", "time now", "what time",
}

_DATE_PATTERNS = {
    "what's the date", "whats the date", "what day is it",
    "today's date", "todays date", "current date",
}

_THANKS_PATTERNS = {
    "thanks", "thank you", "thx", "ty", "much appreciated",
    "appreciate it", "thanks a lot", "thank you so much",
}


# ---------------------------------------------------------------------------
# Fast Path Reasoner
# ---------------------------------------------------------------------------

class FastPathReasoner:
    """
    Reflexive fast-path reasoner for <100ms responses.

    Handles:
    - Greetings / farewells
    - Identity questions
    - Time / date queries
    - Gratitude responses
    - Recent memory lookups (if exact match in recent context)

    Returns None if no fast path matches → falls through to deliberative.
    """

    def __init__(self, bus: NeuralBus, agent_name: str = "NeuralClaw") -> None:
        self._bus = bus
        self._agent_name = agent_name

    async def try_fast_path(
        self,
        signal: Signal,
        memory_ctx: MemoryContext | None = None,
    ) -> FastPathResult | None:
        """
        Attempt a fast-path response. Returns None if no match.
        """
        text = signal.content.strip().lower().rstrip("?!.")
        start = time.time()

        result: FastPathResult | None = None

        # Greetings
        if text in _GREETING_PATTERNS or any(text.startswith(g) for g in _GREETING_PATTERNS):
            result = FastPathResult(
                content=f"Hey there! 👋 I'm {self._agent_name}. How can I help you?",
                confidence=0.95,
            )

        # Farewells
        elif text in _FAREWELL_PATTERNS or any(text.startswith(f) for f in _FAREWELL_PATTERNS):
            result = FastPathResult(
                content="See you later! Take care! 👋",
                confidence=0.95,
            )

        # Identity
        elif text in _IDENTITY_PATTERNS or any(text.startswith(p) for p in _IDENTITY_PATTERNS):
            result = FastPathResult(
                content=(
                    f"I'm **{self._agent_name}**, running on the **NeuralClaw** framework as a self-evolving cognitive AI assistant. "
                    "I can help you with web searches, manage your calendar, "
                    "execute code, and much more — all while learning from our interactions "
                    "to serve you better over time."
                ),
                confidence=0.98,
            )

        # Time
        elif text in _TIME_PATTERNS or any(text.startswith(p) for p in _TIME_PATTERNS):
            now = datetime.now()
            result = FastPathResult(
                content=f"It's currently **{now.strftime('%I:%M %p')}** ({now.strftime('%H:%M')}).",
                confidence=0.99,
                source="system_clock",
            )

        # Date
        elif text in _DATE_PATTERNS or any(text.startswith(p) for p in _DATE_PATTERNS):
            now = datetime.now()
            result = FastPathResult(
                content=f"Today is **{now.strftime('%A, %B %d, %Y')}**.",
                confidence=0.99,
                source="system_clock",
            )

        # Thanks
        elif text in _THANKS_PATTERNS or any(text.startswith(p) for p in _THANKS_PATTERNS):
            result = FastPathResult(
                content="You're welcome! Let me know if there's anything else I can help with. 😊",
                confidence=0.95,
            )

        if result:
            elapsed_ms = (time.time() - start) * 1000
            await self._bus.publish(
                EventType.REASONING_FAST_PATH,
                {
                    "signal_id": signal.id,
                    "response_preview": result.content[:60],
                    "confidence": result.confidence,
                    "elapsed_ms": round(elapsed_ms, 1),
                },
                source="reasoning.fast_path",
            )

        return result
