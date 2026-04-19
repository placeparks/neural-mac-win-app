"""
Classifier — Zero-shot intent classification.

Classifies user intent using lightweight heuristics first (no LLM call),
falling back to the LLM only for ambiguous messages. This keeps response
latency low for obvious intents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.perception.intake import Signal


# ---------------------------------------------------------------------------
# Intent model
# ---------------------------------------------------------------------------

class Intent(Enum):
    """Classified intent types."""
    COMMAND = auto()       # Direct instruction: "search for X", "remind me"
    QUESTION = auto()      # Information request: "what is X?", "how do I"
    CONTINUATION = auto()  # Follow-up to previous conversation
    EMOTIONAL = auto()     # Emotional expression: "thanks!", "I'm frustrated"
    NOISE = auto()         # Non-actionable: empty, spam, gibberish
    UNKNOWN = auto()       # Could not classify — needs LLM


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent: Intent
    confidence: float  # 0.0 – 1.0
    sub_intent: str | None = None  # e.g. "web_search", "calendar_create"


# ---------------------------------------------------------------------------
# Heuristic patterns
# ---------------------------------------------------------------------------

_COMMAND_PATTERNS = [
    re.compile(r"^/\w+", re.IGNORECASE),                        # /command
    re.compile(r"^(search|find|look up|remind|set|create|make|send|open|run|execute|delete|update|add)\b", re.IGNORECASE),
    re.compile(r"^(please |can you |could you )?(search|find|remind|set|create|make|send)", re.IGNORECASE),
    re.compile(r"\b(do|perform|execute|run)\b.*\b(this|that|it)\b", re.IGNORECASE),
]

_QUESTION_PATTERNS = [
    re.compile(r"\?$"),
    re.compile(r"^(what|who|where|when|why|how|is|are|do|does|did|can|could|would|should|will)\b", re.IGNORECASE),
    re.compile(r"^(tell me|explain|describe|define)\b", re.IGNORECASE),
]

_EMOTIONAL_PATTERNS = [
    re.compile(r"^(thanks|thank you|thx|ty|great|awesome|perfect|nice|love it|cool|wow)\b", re.IGNORECASE),
    re.compile(r"^(sorry|ugh|damn|frustrated|annoyed|sad|happy|excited)\b", re.IGNORECASE),
    re.compile(r"^[!.]{2,}$"),  # "!!!" or "..."
    re.compile(r"^[\U0001f600-\U0001faff]+$"),  # Emoji-only messages
]

_CONTINUATION_TRIGGERS = [
    re.compile(r"^(yes|no|yep|nope|sure|ok|okay|yeah|nah|go ahead|do it)\b", re.IGNORECASE),
    re.compile(r"^(and |also |plus |then |but |what about)\b", re.IGNORECASE),
]

_NOISE_PATTERNS = [
    re.compile(r"^\s*$"),
    re.compile(r"^(.)\1{10,}$"),  # Repeated single char
]


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

_LLM_CLASSIFY_PROMPT = (
    "Classify the user message into exactly ONE intent: "
    "COMMAND, QUESTION, CONTINUATION, EMOTIONAL, or NOISE.\n"
    "A request to do something, inspect something, open something, schedule something, "
    "or change something is COMMAND even if phrased politely or indirectly.\n"
    "Respond with ONLY the intent word, nothing else.\n\n"
    "User message: {text}"
)

_INTENT_MAP = {
    "COMMAND": Intent.COMMAND,
    "QUESTION": Intent.QUESTION,
    "CONTINUATION": Intent.CONTINUATION,
    "EMOTIONAL": Intent.EMOTIONAL,
    "NOISE": Intent.NOISE,
}


class IntentClassifier:
    """
    Zero-shot intent classifier with heuristic fast-path and optional LLM fallback.

    Flow:
        1. Check noise patterns → NOISE (confidence 0.95)
        2. Check command patterns → COMMAND (confidence 0.85)
        3. Check question patterns → QUESTION (confidence 0.85)
        4. Check emotional patterns → EMOTIONAL (confidence 0.80)
        5. Check continuation triggers → CONTINUATION (confidence 0.75)
        6. If role_router available → LLM classify via micro model (confidence 0.70)
        7. Fallback → UNKNOWN (confidence 0.0) — caller should use LLM
    """

    def __init__(self, bus: NeuralBus) -> None:
        self._bus = bus
        self._role_router: Any = None

    def set_role_router(self, role_router: Any) -> None:
        """Set role router for LLM-based classification of ambiguous intents."""
        self._role_router = role_router

    async def classify(self, signal: Signal) -> IntentResult:
        """Classify the intent of a Signal."""
        text = signal.content.strip()

        # 1. Noise
        if not text or any(p.match(text) for p in _NOISE_PATTERNS):
            result = IntentResult(Intent.NOISE, confidence=0.95)
            signal.intent = result.intent.name
            await self._publish(signal, result)
            return result

        # 2. Command
        if any(p.search(text) for p in _COMMAND_PATTERNS):
            sub = self._extract_sub_intent(text)
            result = IntentResult(Intent.COMMAND, confidence=0.85, sub_intent=sub)
            signal.intent = result.intent.name
            await self._publish(signal, result)
            return result

        # 3. Question
        if any(p.search(text) for p in _QUESTION_PATTERNS):
            result = IntentResult(Intent.QUESTION, confidence=0.85)
            signal.intent = result.intent.name
            await self._publish(signal, result)
            return result

        # 4. Emotional
        if any(p.search(text) for p in _EMOTIONAL_PATTERNS):
            result = IntentResult(Intent.EMOTIONAL, confidence=0.80)
            signal.intent = result.intent.name
            await self._publish(signal, result)
            return result

        # 5. Continuation
        if any(p.search(text) for p in _CONTINUATION_TRIGGERS):
            result = IntentResult(Intent.CONTINUATION, confidence=0.75)
            signal.intent = result.intent.name
            await self._publish(signal, result)
            return result

        # 6. LLM classification via micro model (fast, cheap)
        if self._role_router:
            llm_result = await self._llm_classify(text)
            if llm_result:
                signal.intent = llm_result.intent.name
                await self._publish(signal, llm_result)
                return llm_result

        # 7. Unknown — no heuristic match and no LLM available
        result = IntentResult(Intent.UNKNOWN, confidence=0.0)
        signal.intent = result.intent.name
        await self._publish(signal, result)
        return result

    def _extract_sub_intent(self, text: str) -> str | None:
        """Try to identify a specific command sub-intent."""
        lower = text.lower()
        if any(w in lower for w in ("search", "find", "look up", "google")):
            return "web_search"
        if any(w in lower for w in ("remind", "reminder", "alarm")):
            return "reminder"
        if any(w in lower for w in ("calendar", "schedule", "event", "meeting", "agenda", "appointment")):
            return "calendar"
        if any(w in lower for w in ("file", "read", "write", "save", "open", "folder", "document")):
            return "file_ops"
        if any(w in lower for w in ("run", "execute", "code", "script", "program", "terminal", "command")):
            return "code_exec"
        return None

    async def _llm_classify(self, text: str) -> IntentResult | None:
        """Use a fast model for intent classification on ambiguous messages."""
        try:
            response = await self._role_router.complete(
                role="fast",
                messages=[{
                    "role": "user",
                    "content": _LLM_CLASSIFY_PROMPT.format(text=text[:500]),
                }],
                temperature=0.0,
                max_tokens=32,
            )
            label = (response.content or "").strip().splitlines()[0].strip().upper()
            intent = _INTENT_MAP.get(label)
            if intent:
                return IntentResult(intent, confidence=0.78, sub_intent=self._extract_sub_intent(text))
        except Exception:
            pass
        return None

    async def _publish(self, signal: Signal, result: IntentResult) -> None:
        await self._bus.publish(
            EventType.INTENT_CLASSIFIED,
            {
                "signal_id": signal.id,
                "intent": result.intent.name,
                "confidence": result.confidence,
                "sub_intent": result.sub_intent,
            },
            source="perception.classifier",
        )
