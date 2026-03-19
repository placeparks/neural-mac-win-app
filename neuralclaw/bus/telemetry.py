"""
Telemetry — Structured reasoning trace logging with cost metrics.

Every decision NeuralClaw makes is logged with full provenance using
the reasoning trace format from the blueprint:

    [2026-02-22 14:30:15] PERCEPTION: Message from Telegram, intent=command, threat=0.02

Cost metrics tracked per session:
- LLM calls, tokens in/out
- Tool calls, tool denials
- Memory injection chars
- Circuit breaker opens
"""

from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from neuralclaw.bus.neural_bus import Event, EventType
from neuralclaw.config import LOG_DIR
from neuralclaw.security.redaction import redact_secrets

if TYPE_CHECKING:
    from rich.console import Console


# ---------------------------------------------------------------------------
# Cost Metrics
# ---------------------------------------------------------------------------

@dataclass
class CostMetrics:
    """Per-session cost and usage metrics."""

    # LLM usage
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    # Tool usage
    tool_calls: int = 0
    tool_denials: int = 0

    # Memory
    memory_inject_chars: int = 0
    memory_budget_hits: int = 0

    # Reliability
    circuit_breaker_opens: int = 0
    provider_retries: int = 0

    # Timing
    total_request_ms: float = 0.0
    session_start: float = field(default_factory=time.time)

    @property
    def session_duration_seconds(self) -> float:
        return time.time() - self.session_start

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    def to_dict(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "total_tokens": self.total_tokens,
            "tool_calls": self.tool_calls,
            "tool_denials": self.tool_denials,
            "memory_inject_chars": self.memory_inject_chars,
            "memory_budget_hits": self.memory_budget_hits,
            "circuit_breaker_opens": self.circuit_breaker_opens,
            "provider_retries": self.provider_retries,
            "total_request_ms": round(self.total_request_ms, 1),
            "session_seconds": round(self.session_duration_seconds, 1),
        }


# ---------------------------------------------------------------------------
# Cortex label mapping
# ---------------------------------------------------------------------------

_CORTEX_MAP: dict[EventType, str] = {
    EventType.SIGNAL_RECEIVED: "PERCEPTION",
    EventType.THREAT_SCREENED: "SECURITY",
    EventType.INTENT_CLASSIFIED: "PERCEPTION",
    EventType.CONTEXT_ENRICHED: "PERCEPTION",
    EventType.MEMORY_QUERY: "MEMORY",
    EventType.MEMORY_RETRIEVED: "MEMORY",
    EventType.MEMORY_STORED: "MEMORY",
    EventType.REASONING_STARTED: "REASONING",
    EventType.REASONING_FAST_PATH: "REASONING",
    EventType.REASONING_DELIBERATE: "REASONING",
    EventType.REASONING_COMPLETE: "REASONING",
    EventType.ACTION_REQUESTED: "ACTION",
    EventType.ACTION_EXECUTING: "ACTION",
    EventType.ACTION_COMPLETE: "ACTION",
    EventType.ACTION_DENIED: "ACTION",
    EventType.RESPONSE_READY: "RESPONSE",
    EventType.RESPONSE_SENT: "RESPONSE",
    EventType.ERROR: "ERROR",
    EventType.SHUTDOWN: "SYSTEM",
}

_CORTEX_COLORS: dict[str, str] = {
    "PERCEPTION": "cyan",
    "SECURITY": "red",
    "MEMORY": "magenta",
    "REASONING": "yellow",
    "ACTION": "green",
    "RESPONSE": "blue",
    "ERROR": "bold red",
    "SYSTEM": "dim white",
    "CONFIDENCE": "bright_yellow",
}


# ---------------------------------------------------------------------------
# Telemetry logger
# ---------------------------------------------------------------------------

class Telemetry:
    """
    Structured reasoning trace logger with cost metrics.

    Subscribes to ALL events on the neural bus and outputs formatted
    reasoning traces to both file and (optionally) stdout via Rich.
    Also tracks cost-related metrics for monitoring and budgeting.

    Rich and aiohttp are lazy-loaded only when actually needed,
    keeping the import footprint minimal for headless deployments.
    """

    def __init__(
        self,
        log_to_file: bool = True,
        log_to_stdout: bool = True,
        log_dir: Path | None = None,
        log_file: str | None = None,
        log_level: str = "INFO",
        log_max_bytes: int = 10 * 1024 * 1024,
        log_backups: int = 5,
        dev_mode: bool = False,
    ) -> None:
        self._log_to_stdout = log_to_stdout
        self._dev_mode = dev_mode
        self._log_level = str(log_level).upper()
        self._metrics = CostMetrics()
        self._console: Console | None = None  # lazy-loaded
        self._Text: type | None = None  # lazy-loaded Rich Text class

        # Lazy-load Rich only when stdout logging is enabled
        if log_to_stdout and dev_mode:
            try:
                from rich.console import Console as _Console
                self._console = _Console(stderr=True)
            except ImportError:
                self._console = None

        # File logger
        self._file_logger: logging.Logger | None = None
        if log_to_file:
            target = Path(log_file).expanduser() if log_file else (log_dir or LOG_DIR) / "reasoning_traces.log"
            target.parent.mkdir(parents=True, exist_ok=True)

            self._file_logger = logging.getLogger("neuralclaw.telemetry")
            self._file_logger.handlers.clear()
            self._file_logger.setLevel(getattr(logging, self._log_level, logging.INFO))
            handler = logging.handlers.RotatingFileHandler(
                target,
                maxBytes=max(log_max_bytes, 1024),
                backupCount=max(log_backups, 0),
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._file_logger.addHandler(handler)
            self._file_logger.propagate = False

        # Async queue for non-blocking file writes
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=2000)
        self._flush_task: asyncio.Task | None = None

    def start_async_flush(self) -> None:
        """Start background log-flush task. Call after the event loop is running."""
        if self._file_logger and self._flush_task is None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    self._flush_task = loop.create_task(self._flush_loop())
            except RuntimeError:
                pass  # No event loop yet — will fall back to sync writes

    async def _flush_loop(self) -> None:
        """Background coroutine: drain the queue and write to file."""
        while True:
            try:
                line = await self._queue.get()
                if self._file_logger:
                    self._file_logger.info(line)
                self._queue.task_done()
            except asyncio.CancelledError:
                # Drain remaining on shutdown
                while not self._queue.empty():
                    try:
                        line = self._queue.get_nowait()
                        if self._file_logger:
                            self._file_logger.info(line)
                    except asyncio.QueueEmpty:
                        break
                return

    async def stop(self) -> None:
        """Cancel background flush task gracefully."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

    @property
    def metrics(self) -> CostMetrics:
        """Get the current session metrics object."""
        return self._metrics

    def get_metrics(self) -> dict:
        """Get metrics as a dictionary for API responses or monitoring."""
        return self._metrics.to_dict()

    def reset_metrics(self) -> None:
        """Reset metrics for a new session."""
        self._metrics = CostMetrics()

    def handle_event(self, event: Event) -> None:
        """Event handler — subscribe this to the neural bus with subscribe_all()."""
        cortex = _CORTEX_MAP.get(event.type, "SYSTEM")
        ts = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # Update cost metrics based on event type
        self._update_metrics(event)

        # Build detail string from event data
        details = self._format_details(event)
        line = f"[{ts}] {cortex}: {details}"
        payload = {
            "ts": event.timestamp,
            "level": "ERROR" if event.type == EventType.ERROR else self._log_level,
            "logger": "neuralclaw.telemetry",
            "event_type": event.type.name,
            "cortex": cortex,
            "source": event.source,
            "correlation_id": event.correlation_id or "",
            "message": details,
            "line": line,
        }
        rendered_json = json.dumps(payload, ensure_ascii=False)

        # File output — push to async queue (non-blocking), fallback to sync
        if self._file_logger:
            try:
                self._queue.put_nowait(rendered_json)
            except asyncio.QueueFull:
                # Queue full (very high throughput) — write sync as fallback
                self._file_logger.info(rendered_json)

        # Rich stdout output
        if self._console and self._log_to_stdout and self._dev_mode:
            if self._Text is None:
                from rich.text import Text
                self._Text = Text
            Text = self._Text
            color = _CORTEX_COLORS.get(cortex, "white")
            ts_text = Text(f"[{ts}] ", style="dim")
            cortex_text = Text(f"{cortex}: ", style=f"bold {color}")
            detail_text = Text(details, style=color)
            self._console.print(ts_text + cortex_text + detail_text, highlight=False)
        elif self._log_to_stdout:
            print(rendered_json)

    def _update_metrics(self, event: Event) -> None:
        """Update cost metrics based on event data."""
        data = event.data
        etype = event.type

        # Track LLM usage from reasoning complete events
        if etype == EventType.REASONING_COMPLETE:
            self._metrics.llm_calls += 1
            usage = data.get("usage", {})
            self._metrics.tokens_in += usage.get("prompt_tokens", 0)
            self._metrics.tokens_out += usage.get("completion_tokens", 0)

        # Track tool calls
        elif etype == EventType.ACTION_EXECUTING:
            self._metrics.tool_calls += 1

        elif etype == EventType.ACTION_DENIED:
            self._metrics.tool_denials += 1

        # Track memory injection
        elif etype == EventType.MEMORY_RETRIEVED:
            chars = data.get("formatted_chars", 0)
            self._metrics.memory_inject_chars += chars
            if data.get("budget_hit", False):
                self._metrics.memory_budget_hits += 1

        # Track response timing
        elif etype == EventType.RESPONSE_READY:
            time_ms = data.get("time_ms", 0)
            self._metrics.total_request_ms += time_ms

    def _format_details(self, event: Event) -> str:
        """Format event data into a human-readable detail string."""
        data = event.data
        etype = event.type

        if etype == EventType.SIGNAL_RECEIVED:
            src = data.get("source", "unknown")
            preview = redact_secrets(data.get("content", "")[:60])
            truncated = " [truncated]" if data.get("was_truncated") else ""
            return f"Message from {src}: \"{preview}\"{truncated}"

        if etype == EventType.THREAT_SCREENED:
            score = data.get("score", 0)
            blocked = data.get("blocked", False)
            status = "BLOCKED" if blocked else "passed"
            verifier = " [verifier]" if data.get("verifier_used") else ""
            return f"threat={score:.2f}, status={status}{verifier}"

        if etype == EventType.INTENT_CLASSIFIED:
            intent = data.get("intent", "unknown")
            conf = data.get("confidence", 0)
            return f"intent={intent}, confidence={conf:.2f}"

        if etype == EventType.MEMORY_RETRIEVED:
            ep = data.get("episodic_count", 0)
            sem = data.get("semantic_count", 0)
            chars = data.get("formatted_chars", 0)
            budget = " [BUDGET HIT]" if data.get("budget_hit") else ""
            return f"Retrieved {ep} episodic, {sem} semantic ({chars} chars){budget}"

        if etype == EventType.REASONING_STARTED:
            path = data.get("path", "deliberative")
            return f"{path.capitalize()} path selected"

        if etype == EventType.REASONING_COMPLETE:
            conf = data.get("confidence", 0)
            source = data.get("source", "llm")
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", 0)
            tok_str = f" | tokens={tokens}" if tokens else ""
            return f"Confidence: {conf:.2f} | Source: {source}{tok_str}"

        if etype == EventType.ACTION_REQUESTED:
            skill = data.get("skill", "unknown")
            cap = data.get("capability", "")
            return f"{skill} invoked (capability: {cap})"

        if etype == EventType.ACTION_DENIED:
            skill = data.get("skill", "unknown")
            reason = redact_secrets(data.get("reason", ""))
            return f"{skill} DENIED — {reason}"

        if etype == EventType.RESPONSE_READY:
            preview = redact_secrets(data.get("content", "")[:80])
            return f"\"{preview}\""

        if etype == EventType.ERROR:
            return f"ERROR: {redact_secrets(str(data.get('error', 'unknown')))}"

        # Default: dump data keys
        parts = [f"{k}={redact_secrets(str(v))}" for k, v in data.items()]
        return ", ".join(parts) if parts else event.type.name
