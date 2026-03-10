"""Secret redaction utilities.

Used to prevent credentials/tokens from appearing in logs, telemetry,
and LLM-visible tool traces.
"""

from __future__ import annotations

import re


_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # OpenAI / API keys
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "[REDACTED_API_KEY]"),
    # Anthropic keys
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "[REDACTED_API_KEY]"),
    # Slack tokens
    (re.compile(r"xoxb-[A-Za-z0-9_-]{20,}"), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"xoxp-[A-Za-z0-9_-]{20,}"), "[REDACTED_SLACK_TOKEN]"),
    # Discord tokens
    (re.compile(r"[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}"), "[REDACTED_DISCORD_TOKEN]"),
    # Bearer tokens
    (re.compile(r"Bearer\s+[A-Za-z0-9_.\-/+=]{20,}"), "Bearer [REDACTED]"),
    # Generic long hex strings (potential keys)
    (re.compile(r"\b[0-9a-fA-F]{40,}\b"), "[REDACTED_HEX_KEY]"),
    # AWS-style keys
    (re.compile(r"AKIA[A-Z0-9]{16}"), "[REDACTED_AWS_KEY]"),
    # GitHub PATs
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"gho_[A-Za-z0-9]{36}"), "[REDACTED_GITHUB_TOKEN]"),
]


def redact_secrets(text: str) -> str:
    """Redact known secret patterns from text."""
    if not text:
        return text
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
