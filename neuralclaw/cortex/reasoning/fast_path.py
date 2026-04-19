"""
Fast path reflexive responses without an LLM call.

Only deterministic utility lookups stay on the fast path. Conversational
messages fall through to the main model so the agent does not sound canned.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.memory.retrieval import MemoryContext
from neuralclaw.cortex.perception.intake import Signal


@dataclass
class FastPathResult:
    """Result from the fast path, or None if no fast path is available."""

    content: str
    confidence: float
    source: str = "fast_path"


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


class FastPathReasoner:
    """
    Reflexive fast-path reasoner for deterministic responses.

    Conversational small talk intentionally falls through to deliberative
    reasoning so the assistant can stay contextual and less repetitive.
    """

    def __init__(self, bus: NeuralBus, agent_name: str = "NeuralClaw") -> None:
        self._bus = bus
        self._agent_name = agent_name

    async def try_fast_path(
        self,
        signal: Signal,
        memory_ctx: MemoryContext | None = None,
    ) -> FastPathResult | None:
        """Attempt a fast-path response. Returns None if no match."""
        del memory_ctx  # Reserved for future deterministic lookups.

        text = signal.content.strip().lower().rstrip("?!.")
        start = time.time()

        if text in _GREETING_PATTERNS or any(text.startswith(g) for g in _GREETING_PATTERNS):
            return None
        if text in _FAREWELL_PATTERNS or any(text.startswith(f) for f in _FAREWELL_PATTERNS):
            return None
        if text in _IDENTITY_PATTERNS or any(text.startswith(p) for p in _IDENTITY_PATTERNS):
            return None
        if text in _THANKS_PATTERNS or any(text.startswith(p) for p in _THANKS_PATTERNS):
            return None

        result: FastPathResult | None = None
        if text in _TIME_PATTERNS or any(text.startswith(p) for p in _TIME_PATTERNS):
            now = datetime.now()
            result = FastPathResult(
                content=f"It's currently **{now.strftime('%I:%M %p')}** ({now.strftime('%H:%M')}).",
                confidence=0.99,
                source="system_clock",
            )
        elif text in _DATE_PATTERNS or any(text.startswith(p) for p in _DATE_PATTERNS):
            now = datetime.now()
            result = FastPathResult(
                content=f"Today is **{now.strftime('%A, %B %d, %Y')}**.",
                confidence=0.99,
                source="system_clock",
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
