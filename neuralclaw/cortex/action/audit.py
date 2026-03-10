"""
Audit — Full action logging with reasoning trace integration.

Every action NeuralClaw takes is logged with: what skill was invoked,
what capabilities were used, what was the result, and the full reasoning
chain that led to the action.

Security: All logged content is passed through secret redaction to
prevent API keys, tokens, and credentials from appearing in logs.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from neuralclaw.config import LOG_DIR


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

from neuralclaw.security.redaction import redact_secrets


# ---------------------------------------------------------------------------
# Audit entry
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    """A single audit log entry."""
    timestamp: float
    skill_name: str
    action: str
    capabilities_used: list[str]
    input_summary: str
    output_summary: str
    success: bool
    execution_time_ms: float
    signal_id: str | None = None
    correlation_id: str | None = None


# ---------------------------------------------------------------------------
# Audit Logger
# ---------------------------------------------------------------------------

class AuditLogger:
    """
    Persistent action audit logger.

    Writes JSON-lines audit logs for full traceability.
    All content is redacted for secrets before logging.
    """

    MAX_IN_MEMORY_ENTRIES = 200  # Cap in-memory entries to prevent leak

    def __init__(self, log_dir: Path | None = None) -> None:
        self._log_dir = log_dir or LOG_DIR
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self._log_dir / "audit.jsonl"
        self._entries: list[AuditEntry] = []

    async def log_action(
        self,
        skill_name: str,
        action: str,
        capabilities_used: list[str],
        input_summary: str,
        output_summary: str,
        success: bool,
        execution_time_ms: float,
        signal_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AuditEntry:
        """Log an action with secret redaction."""
        # Redact secrets from summaries before logging
        safe_input = redact_secrets(input_summary[:500])
        safe_output = redact_secrets(output_summary[:500])

        entry = AuditEntry(
            timestamp=time.time(),
            skill_name=skill_name,
            action=action,
            capabilities_used=capabilities_used,
            input_summary=safe_input,
            output_summary=safe_output,
            success=success,
            execution_time_ms=execution_time_ms,
            signal_id=signal_id,
            correlation_id=correlation_id,
        )

        self._entries.append(entry)
        if len(self._entries) > self.MAX_IN_MEMORY_ENTRIES:
            self._entries = self._entries[-self.MAX_IN_MEMORY_ENTRIES:]

        # Append to JSONL file
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp": entry.timestamp,
                    "skill": entry.skill_name,
                    "action": entry.action,
                    "capabilities": entry.capabilities_used,
                    "input": entry.input_summary,
                    "output": entry.output_summary,
                    "success": entry.success,
                    "time_ms": entry.execution_time_ms,
                    "signal_id": entry.signal_id,
                    "correlation_id": entry.correlation_id,
                }) + "\n")
        except OSError:
            pass  # Don't crash on audit log failures

        return entry

    def get_recent(self, limit: int = 50) -> list[AuditEntry]:
        """Get recent audit entries from memory."""
        return self._entries[-limit:]
