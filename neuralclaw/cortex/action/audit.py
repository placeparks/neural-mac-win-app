"""Audit logging and forensic replay for tool execution."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.config import AuditConfig, AUDIT_LOG
from neuralclaw.security.redaction import redact_secrets


@dataclass
class AuditRecord:
    """A single action audit record."""

    timestamp: float
    request_id: str
    skill_name: str
    action: str
    args_preview: str
    result_preview: str
    allowed: bool
    denied_reason: str
    success: bool
    execution_time_ms: float
    user_id: str = ""
    channel_id: str = ""
    platform: str = ""
    capabilities_used: list[str] = field(default_factory=list)
    signal_id: str | None = None
    correlation_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditRecord":
        """Normalize legacy and current JSONL schemas."""
        request_id = str(
            data.get("request_id")
            or data.get("signal_id")
            or data.get("correlation_id")
            or ""
        )
        allowed = bool(data.get("allowed", data.get("success", True)))
        denied_reason = str(data.get("denied_reason", ""))
        return cls(
            timestamp=float(data.get("timestamp", time.time()) or time.time()),
            request_id=request_id,
            skill_name=str(data.get("skill_name", data.get("skill", ""))),
            action=str(data.get("action", "execute")),
            args_preview=str(data.get("args_preview", data.get("input", ""))),
            result_preview=str(data.get("result_preview", data.get("output", ""))),
            allowed=allowed,
            denied_reason=denied_reason,
            success=bool(data.get("success", allowed and not denied_reason)),
            execution_time_ms=float(data.get("execution_time_ms", data.get("time_ms", 0.0)) or 0.0),
            user_id=str(data.get("user_id", "")),
            channel_id=str(data.get("channel_id", "")),
            platform=str(data.get("platform", "")),
            capabilities_used=list(data.get("capabilities_used", data.get("capabilities", [])) or []),
            signal_id=str(data.get("signal_id", request_id) or request_id),
            correlation_id=str(data.get("correlation_id", request_id) or request_id),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditSearchIndex:
    """In-memory replay index built from the audit JSONL log."""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._by_tool: dict[str, list[int]] = {}
        self._by_user: dict[str, list[int]] = {}
        self._by_request: dict[str, list[int]] = {}

    def rebuild(self, records: list[AuditRecord]) -> None:
        self._records = list(records)
        self._by_tool = {}
        self._by_user = {}
        self._by_request = {}
        for idx, record in enumerate(self._records):
            self._add_indexes(idx, record)

    def add(self, record: AuditRecord) -> None:
        idx = len(self._records)
        self._records.append(record)
        self._add_indexes(idx, record)

    def trim_to_recent(self, max_entries: int) -> None:
        if len(self._records) <= max_entries:
            return
        self.rebuild(self._records[-max_entries:])

    def records(self) -> list[AuditRecord]:
        return list(self._records)

    async def search(
        self,
        tool: str | None = None,
        user_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
        denied_only: bool = False,
        limit: int = 100,
    ) -> list[AuditRecord]:
        candidates = self._candidate_indexes(tool=tool, user_id=user_id)
        ordered = sorted(candidates, reverse=True)
        results: list[AuditRecord] = []
        for idx in ordered:
            record = self._records[idx]
            if since is not None and record.timestamp < since:
                continue
            if until is not None and record.timestamp > until:
                continue
            if denied_only and record.allowed:
                continue
            results.append(record)
            if len(results) >= limit:
                break
        return results

    async def get_trace_actions(self, request_id: str) -> list[AuditRecord]:
        indexes = sorted(self._by_request.get(request_id, []))
        return [self._records[idx] for idx in indexes]

    async def stats(self) -> dict[str, Any]:
        records = list(self._records)
        total = len(records)
        denied = sum(1 for record in records if not record.allowed)
        tool_counts = Counter(record.skill_name for record in records if record.skill_name)
        user_counts = Counter(record.user_id for record in records if record.user_id)
        return {
            "total_records": total,
            "denied_records": denied,
            "denial_rate": (denied / total) if total else 0.0,
            "top_tools": tool_counts.most_common(5),
            "top_users": user_counts.most_common(5),
        }

    def _candidate_indexes(self, tool: str | None, user_id: str | None) -> set[int]:
        if tool and user_id:
            return set(self._by_tool.get(tool, [])) & set(self._by_user.get(user_id, []))
        if tool:
            return set(self._by_tool.get(tool, []))
        if user_id:
            return set(self._by_user.get(user_id, []))
        return set(range(len(self._records)))

    def _add_indexes(self, idx: int, record: AuditRecord) -> None:
        if record.skill_name:
            self._by_tool.setdefault(record.skill_name, []).append(idx)
        if record.user_id:
            self._by_user.setdefault(record.user_id, []).append(idx)
        if record.request_id:
            self._by_request.setdefault(record.request_id, []).append(idx)


class AuditLogger:
    """Persistent action audit logger with replay search and export."""

    def __init__(
        self,
        config: AuditConfig | None = None,
        bus: NeuralBus | None = None,
    ) -> None:
        self._config = config or AuditConfig()
        self._bus = bus
        self._log_file = Path(self._config.jsonl_path or AUDIT_LOG)
        self._entries: list[AuditRecord] = []
        self._index = AuditSearchIndex()
        self._lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._log_file

    async def initialize(self) -> None:
        """Create the log file if needed and rebuild the in-memory index."""
        if not self._config.enabled:
            self._entries = []
            self._index.rebuild([])
            return

        await asyncio.to_thread(self._log_file.parent.mkdir, parents=True, exist_ok=True)
        if not self._log_file.exists():
            await asyncio.to_thread(self._log_file.touch)

        loaded_records = await self._load_records()
        records = list(loaded_records)
        records = self._apply_retention(records)
        self._entries = records[-self._config.max_memory_entries:]
        self._index.rebuild(records)
        if len(records) != len(loaded_records):
            await self._rewrite_records(records)

    async def log_action(
        self,
        skill_name: str,
        action: str,
        args_preview: str,
        result_preview: str,
        success: bool,
        execution_time_ms: float,
        *,
        request_id: str = "",
        user_id: str = "",
        channel_id: str = "",
        platform: str = "",
        capabilities_used: list[str] | None = None,
        allowed: bool = True,
        denied_reason: str = "",
        signal_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Log a single action record."""
        safe_args = redact_secrets(args_preview[:500]) if self._config.include_args else ""
        safe_result = redact_secrets(result_preview[:500])
        safe_denied_reason = redact_secrets(denied_reason[:200])
        record = AuditRecord(
            timestamp=time.time(),
            request_id=request_id or signal_id or correlation_id or "",
            skill_name=skill_name,
            action=action,
            args_preview=safe_args,
            result_preview=safe_result,
            allowed=allowed,
            denied_reason=safe_denied_reason,
            success=success,
            execution_time_ms=execution_time_ms,
            user_id=user_id,
            channel_id=channel_id,
            platform=platform,
            capabilities_used=list(capabilities_used or []),
            signal_id=signal_id or request_id or "",
            correlation_id=correlation_id or request_id or "",
        )

        if not self._config.enabled:
            return record

        async with self._lock:
            self._index.add(record)
            self._entries.append(record)
            if len(self._entries) > self._config.max_memory_entries:
                self._entries = self._entries[-self._config.max_memory_entries:]
            try:
                await asyncio.to_thread(self._append_record, record)
            except OSError as exc:
                await self._publish_error(f"Audit log write failed: {exc}")

        return record

    def get_recent(self, limit: int = 50) -> list[AuditRecord]:
        return self._entries[-limit:]

    async def search(
        self,
        tool: str | None = None,
        user_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
        denied_only: bool = False,
        limit: int = 100,
    ) -> list[AuditRecord]:
        return await self._index.search(
            tool=tool,
            user_id=user_id,
            since=since,
            until=until,
            denied_only=denied_only,
            limit=limit,
        )

    async def get_trace_actions(self, request_id: str) -> list[AuditRecord]:
        return await self._index.get_trace_actions(request_id)

    async def export(
        self,
        path: str,
        *,
        format: str = "jsonl",
        since: float | None = None,
    ) -> int:
        records = await self.search(since=since, limit=100000)
        payload = self._serialize(records, format=format)
        out_path = Path(path)

        def _write() -> None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(payload, encoding="utf-8")

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:
            await self._publish_error(f"Audit export failed: {exc}")
            return 0
        return len(records)

    async def stats(self) -> dict[str, Any]:
        return await self._index.stats()

    async def close(self) -> None:
        return None

    async def _load_records(self) -> list[AuditRecord]:
        def _read() -> list[AuditRecord]:
            records: list[AuditRecord] = []
            if not self._log_file.exists():
                return records
            with self._log_file.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(AuditRecord.from_dict(json.loads(line)))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
            return records

        try:
            return await asyncio.to_thread(_read)
        except OSError as exc:
            await self._publish_error(f"Audit log read failed: {exc}")
            return []

    def _apply_retention(self, records: list[AuditRecord]) -> list[AuditRecord]:
        if self._config.retention_days <= 0:
            return records
        cutoff = time.time() - (self._config.retention_days * 86400)
        return [record for record in records if record.timestamp >= cutoff]

    async def _rewrite_records(self, records: list[AuditRecord]) -> None:
        def _write() -> None:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
            with self._log_file.open("w", encoding="utf-8") as fh:
                for record in records:
                    fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:
            await self._publish_error(f"Audit retention rewrite failed: {exc}")

    def _append_record(self, record: AuditRecord) -> None:
        with self._log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def _serialize(self, records: list[AuditRecord], *, format: str) -> str:
        normalized = format.lower()
        if normalized == "jsonl":
            return "".join(
                json.dumps(record.to_dict(), ensure_ascii=False) + "\n"
                for record in records
            )
        if normalized == "csv":
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=list(AuditRecord(0, "", "", "", "", "", True, "", True, 0.0).to_dict().keys()))
            writer.writeheader()
            for record in records:
                writer.writerow(record.to_dict())
            return buffer.getvalue()
        if normalized == "cef":
            return "".join(self._to_cef(record) + "\n" for record in records)
        raise ValueError(f"Unsupported audit export format: {format}")

    def _to_cef(self, record: AuditRecord) -> str:
        extension = {
            "rt": int(record.timestamp * 1000),
            "request": record.request_id,
            "tool": record.skill_name,
            "user": record.user_id,
            "deviceExternalId": record.channel_id,
            "cs1": record.action,
            "cs1Label": "action",
            "cs2": "allowed" if record.allowed else "denied",
            "cs2Label": "policy_decision",
            "msg": record.denied_reason or record.result_preview[:200],
        }
        serialized = " ".join(
            f"{key}={self._cef_escape(str(value))}"
            for key, value in extension.items()
            if value not in ("", None)
        )
        severity = "3" if record.allowed else "8"
        return (
            f"CEF:0|NeuralClaw|Audit|1.0|tool_call|{self._cef_escape(record.skill_name or 'unknown')}|"
            f"{severity}|{serialized}"
        )

    def _cef_escape(self, value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace("=", "\\=")
            .replace("\n", "\\n")
            .replace("|", "\\|")
        )

    async def _publish_error(self, message: str) -> None:
        if not self._bus:
            return
        await self._bus.publish(
            EventType.ERROR,
            {"error": message, "component": "audit"},
            source="action.audit",
        )
