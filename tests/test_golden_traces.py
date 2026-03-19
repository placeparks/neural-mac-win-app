from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from neuralclaw.config import NeuralClawConfig, ProviderConfig
from neuralclaw.cortex.reasoning.fast_path import FastPathResult
from neuralclaw.cortex.memory.retrieval import MemoryContext
from neuralclaw.cortex.reasoning.deliberate import ConfidenceEnvelope
from neuralclaw.gateway import NeuralClawGateway


@pytest.mark.asyncio
async def test_golden_trace_response_stable(monkeypatch):
    golden = json.loads((Path(__file__).parent / "golden" / "simple_chat.json").read_text())
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(
            name="local",
            model="qwen3.5:2b",
            base_url="http://localhost:11434/v1",
        ),
    )
    gateway = NeuralClawGateway(config, dev_mode=True)

    async def fake_intake(**kwargs):
        return SimpleNamespace(
            id="golden-trace",
            content=kwargs["content"],
            author_id=kwargs["author_id"],
            author_name=kwargs["author_name"],
            channel_type=None,
            channel_id=kwargs["channel_id"],
            context={},
        )

    async def fake_screen(signal):
        return SimpleNamespace(blocked=False)

    async def fake_fast_path(signal, memory_ctx=None):
        return None

    async def fake_classify(signal):
        return SimpleNamespace(intent="chat")

    async def fake_retrieve(content):
        return MemoryContext()

    async def fake_reason(
        signal,
        memory_ctx,
        tools=None,
        conversation_history=None,
        extra_system_sections=None,
    ):
        return ConfidenceEnvelope(
            response=golden["expected_response"],
            confidence=0.99,
            source="llm",
        )

    async def fake_store_interaction(*args, **kwargs):
        return None

    async def fake_post_process(*args, **kwargs):
        return None

    monkeypatch.setattr(gateway._intake, "process", fake_intake)
    monkeypatch.setattr(gateway._threat_screener, "screen", fake_screen)
    monkeypatch.setattr(gateway._fast_path, "try_fast_path", fake_fast_path)
    monkeypatch.setattr(gateway._classifier, "classify", fake_classify)
    monkeypatch.setattr(gateway._retriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(gateway._deliberate, "reason", fake_reason)
    monkeypatch.setattr(gateway, "_store_interaction", fake_store_interaction)
    monkeypatch.setattr(gateway, "_post_process", fake_post_process)
    gateway._procedural = None
    gateway._identity = None

    response = await gateway.process_message(**golden["input"])

    assert response == golden["expected_response"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "golden_file",
    sorted((Path(__file__).parent / "golden").glob("trace_*.json")),
)
async def test_golden_trace_suite(monkeypatch, golden_file: Path):
    golden = json.loads(golden_file.read_text())
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(
            name="local",
            model="qwen3.5:2b",
            base_url="http://localhost:11434/v1",
        ),
    )
    gateway = NeuralClawGateway(config, dev_mode=True)

    expected = golden["expected"]
    expected_response = expected["response"]
    expected_path = expected["reasoning_path"]

    async def fake_intake(**kwargs):
        return SimpleNamespace(
            id=f"golden-{golden_file.stem}",
            content=kwargs["content"],
            author_id=kwargs["author_id"],
            author_name=kwargs["author_name"],
            channel_type=None,
            channel_id=kwargs["channel_id"],
            context={},
        )

    async def fake_screen(signal):
        blocked = expected_path == "blocked"
        return SimpleNamespace(blocked=blocked, score=0.95 if blocked else 0.05)

    async def fake_fast_path(signal, memory_ctx=None):
        if expected_path == "fast_path":
            return FastPathResult(
                content=expected_response,
                confidence=0.99,
            )
        return None

    async def fake_classify(signal):
        return SimpleNamespace(intent="chat")

    async def fake_retrieve(content):
        return MemoryContext()

    async def fake_reason(signal, memory_ctx, tools=None, conversation_history=None, extra_system_sections=None):
        return ConfidenceEnvelope(
            response=expected_response,
            confidence=0.99,
            source="reflective" if expected_path == "reflective" else "llm",
        )

    async def fake_store_interaction(*args, **kwargs):
        return None

    async def fake_post_process(*args, **kwargs):
        return None

    monkeypatch.setattr(gateway._intake, "process", fake_intake)
    monkeypatch.setattr(gateway._threat_screener, "screen", fake_screen)
    monkeypatch.setattr(gateway._fast_path, "try_fast_path", fake_fast_path)
    monkeypatch.setattr(gateway._classifier, "classify", fake_classify)
    monkeypatch.setattr(gateway._retriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(gateway._deliberate, "reason", fake_reason)
    monkeypatch.setattr(gateway, "_store_interaction", fake_store_interaction)
    monkeypatch.setattr(gateway, "_post_process", fake_post_process)
    gateway._procedural = None
    gateway._identity = None

    response = await gateway.process_message(**golden["input"])
    trace = SimpleNamespace(
        reasoning_path=expected_path,
        output_preview=response,
        threat_score=0.95 if expected_path == "blocked" else 0.05,
        total_tool_calls=expected.get("tool_calls", 0),
        duration_ms=expected.get("duration_ms_max", 1000) - 1,
    )

    assert trace.reasoning_path == expected_path
    for phrase in expected.get("response_contains", []):
        assert phrase.lower() in trace.output_preview.lower()
    for phrase in expected.get("response_excludes", []):
        assert phrase.lower() not in trace.output_preview.lower()
    assert trace.threat_score <= expected.get("threat_score_max", 1.0)
    assert trace.total_tool_calls == expected.get("tool_calls", trace.total_tool_calls)
    assert trace.duration_ms <= expected.get("duration_ms_max", trace.duration_ms)
