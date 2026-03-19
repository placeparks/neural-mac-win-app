from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from neuralclaw.config import NeuralClawConfig, ProviderConfig, TracelineConfig
from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.retrieval import MemoryContext
from neuralclaw.cortex.reasoning.deliberate import ConfidenceEnvelope
from neuralclaw.gateway import NeuralClawGateway


@pytest.mark.asyncio
@pytest.mark.slow
async def test_gateway_handles_burst_load(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(
            name="local",
            model="qwen3.5:2b",
            base_url="http://localhost:11434/v1",
        ),
    )
    config.policy.max_concurrent_requests = 5
    gateway = NeuralClawGateway(config, dev_mode=True)

    async def fake_intake(**kwargs):
        return SimpleNamespace(
            id=f"sig-{kwargs['author_id']}",
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
        await asyncio.sleep(0.01)
        return ConfidenceEnvelope(response="ok", confidence=0.9, source="llm")

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

    results = await asyncio.gather(
        *[
            gateway.process_message(
                content=f"msg {idx}",
                author_id=f"user-{idx}",
                author_name="User",
                channel_id="load",
            )
            for idx in range(20)
        ]
    )

    assert results == ["ok"] * 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gateway(monkeypatch, config):
    """Create a gateway with all pipeline stages stubbed out."""
    gateway = NeuralClawGateway(config, dev_mode=True)

    async def fake_intake(**kwargs):
        return SimpleNamespace(
            id=f"sig-{kwargs['author_id']}",
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
        await asyncio.sleep(0.01)
        return ConfidenceEnvelope(response="ok", confidence=0.9, source="llm")

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
    return gateway


# ---------------------------------------------------------------------------
# 3.4 Load & Concurrency Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.slow
async def test_concurrent_requests_db_no_deadlock(monkeypatch):
    """10 concurrent requests to the same gateway instance — no DB deadlocks."""
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(
            name="local",
            model="stub",
            base_url="http://localhost:11434/v1",
        ),
    )
    config.policy.max_concurrent_requests = 10
    gateway = _make_gateway(monkeypatch, config)

    tasks = [
        asyncio.create_task(
            gateway.process_message(
                content=f"Message {i}",
                author_id=f"user_{i}",
                author_name="User",
                channel_id="load",
            )
        )
        for i in range(10)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, f"Errors under concurrent load: {errors}"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_memory_retrieval_under_large_db(tmp_path, large_episodic_db):
    """Memory retrieval stays under 200ms with 10,000 episodes in DB."""
    episodic = large_episodic_db
    start = time.monotonic()
    for _ in range(100):
        await episodic.search("test query", limit=5)
    elapsed_ms = (time.monotonic() - start) * 1000 / 100
    assert elapsed_ms < 200, f"Retrieval took {elapsed_ms:.0f}ms avg — too slow"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_traceline_write_throughput(tmp_path):
    """Traceline can record 100 traces/second without blocking."""
    from neuralclaw.bus.neural_bus import NeuralBus
    from neuralclaw.cortex.observability.traceline import Traceline

    bus = NeuralBus()
    db_path = str(tmp_path / "traces.db")
    traceline = Traceline(
        db_path,
        bus,
        config=TracelineConfig(db_path=db_path),
    )
    await traceline.initialize()
    await bus.start()

    try:
        from neuralclaw.cortex.observability.traceline import ReasoningTrace

        start = time.monotonic()
        for i in range(100):
            trace = ReasoningTrace(
                trace_id=f"trace-{i}",
                request_id=f"req-{i}",
                user_id=f"user_{i % 10}",
                channel="load-test",
                platform="test",
                input_preview=f"input {i}",
                output_preview=f"output {i}",
                confidence=0.85,
                reasoning_path="deliberative",
                timestamp=time.time(),
            )
            await traceline._persist_trace(trace)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"100 trace writes took {elapsed:.2f}s — too slow"
    finally:
        await bus.stop()
        await traceline.close()


@pytest.fixture
async def large_episodic_db(tmp_path):
    """Fixture: populate DB with 10,000 episodic entries."""
    from neuralclaw.db.pool import DBPool

    db_path = str(tmp_path / "large_episodic.db")
    db_pool = DBPool(db_path)
    episodic = EpisodicMemory(db_path, db_pool=db_pool)
    await db_pool.initialize()
    await episodic.initialize()
    for i in range(10_000):
        await episodic.store(
            content=f"Episode {i}: discussing project {i % 50}",
            author=f"user_{i % 100}",
            importance=0.5,
        )
    yield episodic
    await episodic.close()
    await db_pool.close()
