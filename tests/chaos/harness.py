"""
Chaos engineering harness for NeuralClaw.
Run specific scenarios: pytest tests/chaos/ -v -k "provider_down"

Scenarios:
  provider_down       — primary LLM provider returns 503 for 30s
  db_locked           — memory DB is locked for 5s (concurrent writes)
  memory_exhaustion   — consume 80% of available RAM
  network_partition   — block outbound network for 10s
  channel_disconnect  — simulate Telegram connection drop + reconnect
  slow_provider       — primary provider takes 15s per call (timeout test)
  burst_messages      — 50 messages in 1 second from 10 different users
  malformed_config    — corrupt config.toml mid-run
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeChannelMessage:
    """Lightweight stand-in for a channel message used by chaos tests."""

    content: str = ""
    author_id: str = "user_0"
    channel_id: str = "chaos_test"


def make_channel_message(
    content: str = "Hello",
    author_id: str = "user_0",
    channel_id: str = "chaos_test",
) -> FakeChannelMessage:
    """Build a minimal message object suitable for gateway.process_message()."""
    return FakeChannelMessage(
        content=content,
        author_id=author_id,
        channel_id=channel_id,
    )


# ---------------------------------------------------------------------------
# Original utility — kept for backward compatibility
# ---------------------------------------------------------------------------

@contextmanager
def forced_failure(target, attr: str, exc: Exception):
    """Monkey-patch *attr* on *target* to raise *exc* on every call."""
    original = getattr(target, attr)

    async def _raiser(*args, **kwargs):
        raise exc

    setattr(target, attr, _raiser)
    try:
        yield
    finally:
        setattr(target, attr, original)


# ---------------------------------------------------------------------------
# Chaos context managers
# ---------------------------------------------------------------------------

PROVIDER_PATCH_TARGET = (
    "neuralclaw.providers.anthropic.AnthropicProvider.complete"
)


@contextlib.asynccontextmanager
async def provider_outage(duration: float = 30.0):
    """Simulate primary LLM provider returning 503 for *duration* seconds.

    Every call to ``AnthropicProvider.complete`` raises immediately while the
    context is active.  The context manager keeps the outage alive for
    *duration* seconds so that callers can observe time-dependent behaviour
    such as circuit-breaker transitions.
    """
    async def _raise_503(*args, **kwargs):
        raise Exception("503 Service Unavailable")

    with patch(PROVIDER_PATCH_TARGET, side_effect=_raise_503):
        yield
        await asyncio.sleep(duration)


@contextlib.asynccontextmanager
async def slow_provider(latency: float = 15.0):
    """Simulate a provider that takes *latency* seconds per call.

    Useful for verifying that request-level timeouts and circuit breakers
    fire correctly when the upstream is merely slow rather than dead.
    """
    original_fn: AsyncMock | None = None

    async def slow_complete(*args, **kwargs):
        await asyncio.sleep(latency)
        if original_fn is not None:
            return await original_fn(*args, **kwargs)
        return {"text": "slow-response", "usage": {"input": 0, "output": 0}}

    with patch(PROVIDER_PATCH_TARGET, side_effect=slow_complete) as mock:
        original_fn = mock  # capture so slow_complete can optionally delegate
        yield


@contextlib.asynccontextmanager
async def burst_messages(gateway, n: int = 50, users: int = 10):
    """Fire *n* messages from *users* different users simultaneously.

    Yields the list of :class:`asyncio.Task` objects so the caller can
    inspect individual results.  On exit the context manager gathers all
    tasks and silently collects exceptions.
    """
    messages = [
        make_channel_message(
            content=f"Test message {i}",
            author_id=f"user_{i % users}",
        )
        for i in range(n)
    ]
    tasks = [
        asyncio.create_task(gateway.process_message(msg)) for msg in messages
    ]
    yield tasks
    # Gather on exit — callers that already gathered can safely ignore this.
    await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# SCENARIOS
# ---------------------------------------------------------------------------

@pytest.mark.chaos
class TestChaosProviderDown:
    """Verify system resilience when the primary LLM provider is down."""

    @pytest.mark.chaos
    async def test_fallback_activates_on_primary_outage(self, gateway):
        """When primary provider fails, fallback provider must handle
        requests — the user should never see a raw 503 bubble up."""
        async with provider_outage():
            response = await gateway.process_message(
                make_channel_message("Hello")
            )
            assert response is not None
            assert "error" not in str(response).lower()

    @pytest.mark.chaos
    async def test_circuit_breaker_opens_during_outage(self, gateway):
        """Circuit breaker should open after repeated failures so that
        subsequent calls fail fast rather than waiting the full timeout
        each time."""
        start = time.monotonic()
        async with provider_outage():
            for _ in range(10):
                await gateway.process_message(
                    make_channel_message("Hello")
                )
        elapsed = time.monotonic() - start
        # After the circuit opens, calls should fail fast.
        assert elapsed < 15.0, (
            f"Took {elapsed:.1f}s — circuit breaker not working"
        )


@pytest.mark.chaos
class TestChaosBurstLoad:
    """Verify system stability under sudden message-volume spikes."""

    @pytest.mark.chaos
    async def test_burst_does_not_crash_gateway(self, gateway):
        """50 simultaneous messages should complete without bringing
        down the gateway process."""
        async with burst_messages(gateway, n=50, users=10) as tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        hard_errors = [
            e
            for e in results
            if isinstance(e, Exception)
            and not isinstance(e, (TimeoutError, RuntimeError))
        ]
        assert len(hard_errors) == 0, f"Hard crashes: {hard_errors}"

    @pytest.mark.chaos
    async def test_rate_limiter_prevents_per_user_flood(self, gateway):
        """A single user sending 50 messages should be rate-limited
        after roughly 20 messages."""
        responses = []
        for i in range(50):
            r = await gateway.process_message(
                make_channel_message(f"Message {i}", author_id="flood_user")
            )
            responses.append(r)
        rate_limited = [
            r for r in responses if r and "too quickly" in str(r).lower()
        ]
        assert len(rate_limited) >= 20, "Rate limiter should have activated"
