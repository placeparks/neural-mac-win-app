"""
Queryable reasoning trace store assembled from neural bus events.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite

from neuralclaw.bus.neural_bus import Event, EventType, NeuralBus
from neuralclaw.config import TracelineConfig


@dataclass
class ToolCallTrace:
    tool: str
    args_preview: str = ""
    result_preview: str = ""
    duration_ms: float = 0.0
    success: bool = True
    idempotency_key: str = ""


@dataclass
class ReasoningTrace:
    trace_id: str
    request_id: str
    user_id: str = ""
    channel: str = ""
    platform: str = ""
    input_preview: str = ""
    output_preview: str = ""
    confidence: float = 0.0
    reasoning_path: str = ""
    threat_score: float = 0.0
    memory_hits: int = 0
    tool_calls: list[ToolCallTrace] = field(default_factory=list)
    total_tool_calls: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    error: str = ""
    tags: list[str] = field(default_factory=list)


class Traceline:
    """Subscribe to neural bus events and persist compact request traces."""

    def __init__(
        self,
        db_path: str,
        bus: NeuralBus,
        config: TracelineConfig | None = None,
    ) -> None:
        self._db_path = db_path
        self._bus = bus
        self._config = config or TracelineConfig(db_path=db_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._partial: dict[str, ReasoningTrace] = {}

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                platform TEXT NOT NULL DEFAULT '',
                input_preview TEXT NOT NULL DEFAULT '',
                output_preview TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.0,
                reasoning_path TEXT NOT NULL DEFAULT '',
                threat_score REAL NOT NULL DEFAULT 0.0,
                memory_hits INTEGER NOT NULL DEFAULT 0,
                tool_calls_json TEXT NOT NULL DEFAULT '[]',
                total_tool_calls INTEGER NOT NULL DEFAULT 0,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                duration_ms REAL NOT NULL DEFAULT 0.0,
                timestamp REAL NOT NULL DEFAULT 0.0,
                error TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_traces_user_id ON traces(user_id)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_traces_channel ON traces(channel)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces(timestamp)")
        await self._db.commit()
        self._bus.subscribe_all(self.handle_event)

    async def close(self) -> None:
        if self._db:
            await self._db.commit()
            await self._db.close()
            self._db = None

    async def handle_event(self, event: Event) -> None:
        request_id = self._request_id_for(event)
        if not request_id:
            return

        async with self._lock:
            trace = self._partial.get(request_id) or ReasoningTrace(
                trace_id=request_id,
                request_id=request_id,
                timestamp=event.timestamp,
            )
            self._partial[request_id] = trace

            if event.type == EventType.SIGNAL_RECEIVED:
                self._on_signal_received(trace, event)
            elif event.type == EventType.THREAT_SCREENED:
                trace.threat_score = float(event.data.get("score", trace.threat_score) or 0.0)
            elif event.type == EventType.REASONING_STARTED:
                trace.reasoning_path = self._normalize_path(str(event.data.get("path", "")))
            elif event.type == EventType.REASONING_FAST_PATH:
                trace.reasoning_path = "fast_path"
                trace.confidence = float(event.data.get("confidence", trace.confidence) or trace.confidence)
            elif event.type == EventType.REASONING_COMPLETE:
                self._on_reasoning_complete(trace, event)
            elif event.type == EventType.REFLECTION_STARTED:
                trace.reasoning_path = "reflective"
            elif event.type == EventType.REFLECTION_COMPLETE:
                trace.reasoning_path = "reflective"
                trace.confidence = float(event.data.get("confidence", trace.confidence) or trace.confidence)
            elif event.type == EventType.CONTEXT_ENRICHED:
                trace.memory_hits = int(event.data.get("memory_hits", trace.memory_hits) or 0)
                trace.user_id = str(event.data.get("user_id", trace.user_id) or trace.user_id)
                trace.channel = str(event.data.get("channel_id", trace.channel) or trace.channel)
                trace.platform = str(event.data.get("platform", trace.platform) or trace.platform)
            elif event.type == EventType.ACTION_EXECUTING:
                self._on_action_executing(trace, event)
            elif event.type == EventType.ACTION_COMPLETE:
                self._on_action_complete(trace, event)
            elif event.type == EventType.ERROR:
                self._on_error(trace, event)
            elif event.type == EventType.RESPONSE_READY:
                self._on_response_ready(trace, event)
                await self._persist_trace(trace)
                self._partial.pop(request_id, None)

    async def get_trace(self, trace_id: str) -> ReasoningTrace | None:
        assert self._db is not None
        rows = await self._db.execute_fetchall("SELECT * FROM traces WHERE trace_id = ?", (trace_id,))
        return self._row_to_trace(rows[0]) if rows else None

    async def query_traces(
        self,
        user_id: str | None = None,
        channel: str | None = None,
        tool: str | None = None,
        since: float | None = None,
        until: float | None = None,
        min_confidence: float | None = None,
        limit: int = 50,
    ) -> list[ReasoningTrace]:
        assert self._db is not None
        clauses: list[str] = []
        params: list[Any] = []

        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if channel:
            clauses.append("channel = ?")
            params.append(channel)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until)
        if min_confidence is not None:
            clauses.append("confidence >= ?")
            params.append(min_confidence)

        sql = "SELECT * FROM traces"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = await self._db.execute_fetchall(sql, tuple(params))
        traces = [self._row_to_trace(row) for row in rows]
        if tool:
            traces = [t for t in traces if any(call.tool == tool for call in t.tool_calls)]
        return traces

    async def export_jsonl(self, path: str, since: float | None = None) -> int:
        traces = await self.query_traces(since=since, limit=100000)
        lines = [json.dumps(asdict(trace), ensure_ascii=False) for trace in traces]

        def _write() -> None:
            out = Path(path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

        await asyncio.to_thread(_write)
        return len(traces)

    async def get_metrics(self) -> dict[str, Any]:
        assert self._db is not None
        rows = await self._db.execute_fetchall(
            """
            SELECT COUNT(*), AVG(confidence), AVG(duration_ms), AVG(cost_usd)
            FROM traces
            """
        )
        total, avg_confidence, avg_duration, avg_cost = rows[0]
        traces = await self.query_traces(limit=100000)
        tool_usage: dict[str, int] = {}
        path_dist: dict[str, int] = {}
        errors = 0
        for trace in traces:
            path_dist[trace.reasoning_path or "unknown"] = path_dist.get(trace.reasoning_path or "unknown", 0) + 1
            if trace.error:
                errors += 1
            for call in trace.tool_calls:
                tool_usage[call.tool] = tool_usage.get(call.tool, 0) + 1
        return {
            "total_traces": int(total or 0),
            "avg_confidence": round(float(avg_confidence or 0.0), 3),
            "avg_duration_ms": round(float(avg_duration or 0.0), 3),
            "tool_usage_breakdown": tool_usage,
            "reasoning_path_distribution": path_dist,
            "error_rate": round((errors / max(1, len(traces))), 3),
            "cost_last_7d": round(float(avg_cost or 0.0) * len([t for t in traces if t.timestamp >= time.time() - 7 * 86400]), 6),
        }

    async def prune(self, keep_days: int = 30) -> int:
        assert self._db is not None
        cutoff = time.time() - keep_days * 86400
        rows = await self._db.execute_fetchall("SELECT COUNT(*) FROM traces WHERE timestamp < ?", (cutoff,))
        count = int(rows[0][0] or 0)
        await self._db.execute("DELETE FROM traces WHERE timestamp < ?", (cutoff,))
        await self._db.commit()
        return count

    def _on_signal_received(self, trace: ReasoningTrace, event: Event) -> None:
        data = event.data
        trace.user_id = str(data.get("author_id", trace.user_id) or trace.user_id)
        trace.channel = str(data.get("channel_id", trace.channel) or trace.channel)
        trace.platform = str(data.get("source", trace.platform) or trace.platform)
        if self._config.include_input:
            trace.input_preview = str(data.get("content", ""))[: self._config.max_preview_chars]
        trace.timestamp = event.timestamp

    def _on_reasoning_complete(self, trace: ReasoningTrace, event: Event) -> None:
        data = event.data
        trace.confidence = float(data.get("confidence", trace.confidence) or 0.0)
        trace.reasoning_path = self._normalize_path(str(data.get("source", trace.reasoning_path) or trace.reasoning_path))
        trace.total_tool_calls = int(data.get("tool_calls", trace.total_tool_calls) or trace.total_tool_calls)
        trace.tokens_used = int(data.get("tokens_used", trace.tokens_used) or trace.tokens_used)
        trace.duration_ms = float(data.get("duration_ms", trace.duration_ms) or trace.duration_ms)

    def _on_action_executing(self, trace: ReasoningTrace, event: Event) -> None:
        data = event.data
        trace.tool_calls.append(
            ToolCallTrace(
                tool=str(data.get("skill", "")),
                args_preview=str(data.get("args", ""))[:200],
                success=True,
            )
        )

    def _on_action_complete(self, trace: ReasoningTrace, event: Event) -> None:
        data = event.data
        skill = str(data.get("skill", ""))
        for call in reversed(trace.tool_calls):
            if call.tool == skill and not call.result_preview:
                call.success = bool(data.get("success", True))
                call.result_preview = str(data.get("result_preview", data.get("error", "")))[:200]
                break
        trace.total_tool_calls = len(trace.tool_calls)

    def _on_error(self, trace: ReasoningTrace, event: Event) -> None:
        trace.error = str(event.data.get("error", trace.error) or trace.error)

    def _on_response_ready(self, trace: ReasoningTrace, event: Event) -> None:
        data = event.data
        trace.user_id = str(data.get("user_id", trace.user_id) or trace.user_id)
        trace.channel = str(data.get("channel_id", trace.channel) or trace.channel)
        trace.platform = str(data.get("platform", trace.platform) or trace.platform)
        trace.confidence = float(data.get("confidence", trace.confidence) or 0.0)
        if self._config.include_output:
            trace.output_preview = str(data.get("content", ""))[: self._config.max_preview_chars]
        trace.tags = [tag for tag in [trace.platform, trace.reasoning_path] if tag]

    async def _persist_trace(self, trace: ReasoningTrace) -> None:
        assert self._db is not None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO traces (
                trace_id, request_id, user_id, channel, platform, input_preview, output_preview,
                confidence, reasoning_path, threat_score, memory_hits, tool_calls_json,
                total_tool_calls, tokens_used, cost_usd, duration_ms, timestamp, error, tags_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace.trace_id,
                trace.request_id,
                trace.user_id,
                trace.channel,
                trace.platform,
                trace.input_preview,
                trace.output_preview,
                trace.confidence,
                trace.reasoning_path,
                trace.threat_score,
                trace.memory_hits,
                json.dumps([asdict(call) for call in trace.tool_calls]),
                trace.total_tool_calls,
                trace.tokens_used,
                trace.cost_usd,
                trace.duration_ms,
                trace.timestamp,
                trace.error,
                json.dumps(trace.tags),
            ),
        )
        await self._db.commit()

    def _request_id_for(self, event: Event) -> str:
        data = event.data or {}
        return str(
            data.get("signal_id")
            or data.get("request_id")
            or event.correlation_id
            or ""
        )

    def _normalize_path(self, path: str) -> str:
        lower = path.lower()
        if "reflect" in lower:
            return "reflective"
        if "fast" in lower:
            return "fast_path"
        if "deliberative" in lower or "llm" in lower:
            return "deliberative"
        return lower

    def _row_to_trace(self, row: tuple[Any, ...]) -> ReasoningTrace:
        return ReasoningTrace(
            trace_id=row[0],
            request_id=row[1],
            user_id=row[2],
            channel=row[3],
            platform=row[4],
            input_preview=row[5],
            output_preview=row[6],
            confidence=float(row[7] or 0.0),
            reasoning_path=row[8],
            threat_score=float(row[9] or 0.0),
            memory_hits=int(row[10] or 0),
            tool_calls=[ToolCallTrace(**item) for item in json.loads(row[11] or "[]")],
            total_tool_calls=int(row[12] or 0),
            tokens_used=int(row[13] or 0),
            cost_usd=float(row[14] or 0.0),
            duration_ms=float(row[15] or 0.0),
            timestamp=float(row[16] or 0.0),
            error=row[17] or "",
            tags=json.loads(row[18] or "[]"),
        )
