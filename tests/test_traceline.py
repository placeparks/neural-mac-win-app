"""Tests for traceline observability."""

from __future__ import annotations

import asyncio
import json

import pytest

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.config import TracelineConfig
from neuralclaw.cortex.observability.traceline import Traceline


class TestTraceline:
    @pytest.fixture(autouse=True)
    async def setup(self, tmp_path):
        self.bus = NeuralBus()
        self.db_path = str(tmp_path / "traces.db")
        self.out_path = str(tmp_path / "traces.jsonl")
        self.traceline = Traceline(
            self.db_path,
            self.bus,
            config=TracelineConfig(db_path=self.db_path),
        )
        await self.traceline.initialize()
        await self.bus.start()
        yield
        await self.bus.stop()
        await self.traceline.close()

    @pytest.mark.asyncio
    async def test_trace_recorded_on_bus_events(self):
        request_id = "sig-123"
        await self.bus.publish(
            EventType.SIGNAL_RECEIVED,
            {
                "signal_id": request_id,
                "author_id": "user-1",
                "channel_id": "chan-1",
                "source": "telegram",
                "content": "hello world",
            },
            source="test",
        )
        await self.bus.publish(
            EventType.REASONING_COMPLETE,
            {
                "signal_id": request_id,
                "confidence": 0.82,
                "source": "llm",
                "tool_calls": 1,
            },
            source="test",
        )
        await self.bus.publish(
            EventType.ACTION_EXECUTING,
            {"signal_id": request_id, "skill": "web_search", "args": '{"q":"hello"}'},
            source="test",
        )
        await self.bus.publish(
            EventType.ACTION_COMPLETE,
            {
                "signal_id": request_id,
                "skill": "web_search",
                "success": True,
                "result_preview": '{"results":1}',
            },
            source="test",
        )
        await self.bus.publish(
            EventType.RESPONSE_READY,
            {
                "signal_id": request_id,
                "user_id": "user-1",
                "channel_id": "chan-1",
                "platform": "telegram",
                "content": "hi there",
                "confidence": 0.82,
            },
            source="test",
        )

        await asyncio.sleep(0.1)
        trace = await self.traceline.get_trace(request_id)

        assert trace is not None
        assert trace.request_id == request_id
        assert trace.user_id == "user-1"
        assert trace.channel == "chan-1"
        assert trace.platform == "telegram"
        assert trace.output_preview == "hi there"
        assert trace.total_tool_calls == 1
        assert trace.tool_calls[0].tool == "web_search"

    @pytest.mark.asyncio
    async def test_query_returns_filtered_results(self):
        for idx, user_id in enumerate(["u1", "u2"]):
            request_id = f"sig-{idx}"
            await self.bus.publish(
                EventType.SIGNAL_RECEIVED,
                {
                    "signal_id": request_id,
                    "author_id": user_id,
                    "channel_id": "chan-1",
                    "source": "web",
                    "content": f"message {idx}",
                },
                source="test",
            )
            await self.bus.publish(
                EventType.RESPONSE_READY,
                {
                    "signal_id": request_id,
                    "user_id": user_id,
                    "channel_id": "chan-1",
                    "platform": "web",
                    "content": "done",
                    "confidence": 0.5 + idx * 0.2,
                },
                source="test",
            )

        await asyncio.sleep(0.1)
        results = await self.traceline.query_traces(user_id="u2", min_confidence=0.6)

        assert len(results) == 1
        assert results[0].user_id == "u2"

    @pytest.mark.asyncio
    async def test_export_jsonl_and_metrics(self):
        request_id = "sig-export"
        await self.bus.publish(
            EventType.SIGNAL_RECEIVED,
            {
                "signal_id": request_id,
                "author_id": "user-export",
                "channel_id": "chan-export",
                "source": "discord",
                "content": "trace this",
            },
            source="test",
        )
        await self.bus.publish(
            EventType.RESPONSE_READY,
            {
                "signal_id": request_id,
                "user_id": "user-export",
                "channel_id": "chan-export",
                "platform": "discord",
                "content": "exported",
                "confidence": 0.91,
            },
            source="test",
        )

        await asyncio.sleep(0.1)
        exported = await self.traceline.export_jsonl(self.out_path)
        metrics = await self.traceline.get_metrics()

        assert exported >= 1
        with open(self.out_path, "r", encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]
        assert any(line["request_id"] == request_id for line in lines)
        assert metrics["total_traces"] >= 1
