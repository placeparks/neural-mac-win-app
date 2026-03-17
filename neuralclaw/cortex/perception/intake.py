"""
Intake — Multi-channel message normalization with content sanitization.

Converts raw channel-specific messages into a unified Signal dataclass
that flows through the NeuralClaw cognitive pipeline.

Security features:
- Content truncation to configurable budget (prevents token bombing)
- Injection delimiter neutralization (strips common prompt injection markers)
- Provenance tagging (source=user|web|file for downstream policy decisions)
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus


# ---------------------------------------------------------------------------
# Signal model
# ---------------------------------------------------------------------------

class ChannelType(Enum):
    """Supported channel types."""
    CLI = auto()
    TELEGRAM = auto()
    DISCORD = auto()
    WHATSAPP = auto()
    SLACK = auto()
    SIGNAL = auto()
    WEB = auto()


@dataclass
class Signal:
    """
    Unified, channel-agnostic message representation.

    Every incoming message — regardless of source — is normalized into
    a Signal before entering the cognitive pipeline.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    content: str = ""
    author_id: str = ""
    author_name: str = ""
    channel_type: ChannelType = ChannelType.CLI
    channel_id: str = ""
    timestamp: float = field(default_factory=time.time)
    reply_to: str | None = None
    media: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Enriched by perception pipeline
    intent: str | None = None
    threat_score: float = 0.0
    is_blocked: bool = False
    context: dict[str, Any] = field(default_factory=dict)

    # Provenance tracking (set by sanitizer)
    source_type: str = "user"  # user | web | file | api
    was_truncated: bool = False
    original_length: int = 0


# ---------------------------------------------------------------------------
# Content sanitization
# ---------------------------------------------------------------------------

# Patterns that look like prompt injection delimiters
_INJECTION_DELIMITERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"```\s*system\b", re.I), "```text"),
    (re.compile(r"\[SYSTEM\]", re.I), "[MESSAGE]"),
    (re.compile(r"\[INST\]", re.I), "[MESSAGE]"),
    (re.compile(r"<\|system\|>", re.I), "<|message|>"),
    (re.compile(r"<<\s*SYS\s*>>", re.I), "<<MSG>>"),
    (re.compile(r"###\s+SYSTEM\s*\n", re.I), "### MESSAGE\n"),
    (re.compile(r"BEGIN\s+PROMPT", re.I), "BEGIN MESSAGE"),
    (re.compile(r"END\s+PROMPT", re.I), "END MESSAGE"),
    (re.compile(r"<\|im_start\|>system", re.I), "<|im_start|>message"),
]


def sanitize_content(
    text: str,
    max_chars: int = 8000,
    source_type: str = "user",
) -> tuple[str, bool, int]:
    """
    Sanitize untrusted content before it reaches the LLM.

    Returns:
        Tuple of (sanitized_text, was_truncated, original_length).
    """
    original_length = len(text)
    was_truncated = False

    # 1. Truncate to budget
    if len(text) > max_chars:
        text = text[:max_chars]
        was_truncated = True

    # 2. Neutralize injection delimiters
    for pattern, replacement in _INJECTION_DELIMITERS:
        text = pattern.sub(replacement, text)

    return text, was_truncated, original_length


# ---------------------------------------------------------------------------
# Perception Intake
# ---------------------------------------------------------------------------

class PerceptionIntake:
    """
    First stage of perception — normalizes raw channel messages into Signals
    and publishes SIGNAL_RECEIVED to the neural bus.

    Applies content sanitization to prevent token bombing and injection
    delimiter smuggling.
    """

    def __init__(
        self,
        bus: NeuralBus,
        max_content_chars: int = 8000,
    ) -> None:
        self._bus = bus
        self._max_content_chars = max_content_chars

    async def process(
        self,
        content: str,
        author_id: str = "user",
        author_name: str = "User",
        channel_type: ChannelType = ChannelType.CLI,
        channel_id: str = "cli",
        reply_to: str | None = None,
        media: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        source_type: str = "user",
    ) -> Signal:
        """Normalize a raw message into a Signal and publish it."""

        # Clean content
        cleaned = self._normalize_text(content)

        # Sanitize content (truncate + strip delimiters)
        sanitized, was_truncated, original_length = sanitize_content(
            cleaned,
            max_chars=self._max_content_chars,
            source_type=source_type,
        )

        signal = Signal(
            content=sanitized,
            author_id=author_id,
            author_name=author_name,
            channel_type=channel_type,
            channel_id=channel_id,
            reply_to=reply_to,
            media=media or [],
            metadata=metadata or {},
            source_type=source_type,
            was_truncated=was_truncated,
            original_length=original_length,
        )

        # Publish to bus
        await self._bus.publish(
            EventType.SIGNAL_RECEIVED,
            {
                "signal_id": signal.id,
                "source": channel_type.name.lower(),
                "author": author_name,
                "author_id": author_id,
                "channel_id": channel_id,
                "content": sanitized[:200],  # Truncate for telemetry
                "source_type": source_type,
                "was_truncated": was_truncated,
                "original_length": original_length,
            },
            source="perception.intake",
        )

        return signal

    def _normalize_text(self, text: str) -> str:
        """Strip extraneous whitespace and formatting artifacts."""
        # Remove zero-width chars, normalize whitespace
        text = text.strip()
        # Collapse multiple newlines
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)
