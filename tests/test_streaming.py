"""Tests for streaming response support."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from neuralclaw.channels.discord_adapter import DiscordAdapter
from neuralclaw.channels.protocol import ChannelAdapter, ChannelMessage
from neuralclaw.config import NeuralClawConfig, ProviderConfig
from neuralclaw.gateway import NeuralClawGateway
from neuralclaw.providers.router import _chunk_text


async def _aiter(parts):
    for part in parts:
        yield part


class DummyAdapter(ChannelAdapter):
    name = "dummy"

    def __init__(self):
        super().__init__()
        self.sent = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, channel_id: str, content: str, **kwargs):
        self.sent.append((channel_id, content, kwargs))


@pytest.mark.asyncio
async def test_send_stream_default_fallback_buffers_content():
    adapter = DummyAdapter()

    await adapter.send_stream("chan-1", _aiter(["hello", " ", "world"]), confidence=0.9)

    assert adapter.sent == [("chan-1", "hello world", {"confidence": 0.9})]


@pytest.mark.asyncio
async def test_discord_send_stream_edits_placeholder():
    adapter = DiscordAdapter("token")
    edits = []

    class FakeMessage:
        async def edit(self, content):
            edits.append(content)

    class FakeChannel:
        async def send(self, content):
            edits.append(content)
            return FakeMessage()

    adapter._client = SimpleNamespace(
        get_channel=lambda channel_id: FakeChannel(),
        fetch_channel=lambda channel_id: FakeChannel(),
    )

    await adapter.send_stream("123", _aiter(["hello ", "world", "!"]), edit_interval=2)

    assert edits[0] == "▌"
    assert edits[-1] == "hello world!"


@pytest.mark.asyncio
async def test_gateway_uses_send_stream_when_feature_enabled(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    config.features.streaming_responses = True
    config.security.output_filtering = False
    gateway = NeuralClawGateway(config)

    calls = []

    class StreamingAdapter:
        async def send_stream(self, channel_id, token_iterator, **kwargs):
            parts = []
            async for token in token_iterator:
                parts.append(token)
            calls.append((channel_id, "".join(parts), kwargs))

        async def send(self, channel_id, content, **kwargs):
            calls.append(("fallback", content, kwargs))

    async def fake_build_streaming_response(msg):
        return {
            "token_iterator": _aiter(["stream ", "works"]),
            "confidence": 0.7,
            "user_id": "user-1",
            "memory_ctx": None,
        }

    async def fake_store(*args, **kwargs):
        return None

    async def fake_post(*args, **kwargs):
        return None

    monkeypatch.setattr(gateway, "_build_streaming_response", fake_build_streaming_response)
    monkeypatch.setattr(gateway, "_store_interaction", fake_store)
    monkeypatch.setattr(gateway, "_post_process", fake_post)
    gateway._provider = object()
    gateway._channels["web"] = StreamingAdapter()

    msg = ChannelMessage(
        content="hello",
        author_id="u1",
        author_name="User",
        channel_id="sess-1",
        metadata={"platform": "web", "source": "web"},
    )

    handled = await gateway._try_stream_channel_message(msg)

    assert handled is True
    assert calls[0][0] == "sess-1"
    assert calls[0][1] == "stream works"


@pytest.mark.asyncio
async def test_gateway_disables_streaming_when_output_filtering_enabled():
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    config.features.streaming_responses = True
    config.security.output_filtering = True
    gateway = NeuralClawGateway(config)
    gateway._provider = object()
    gateway._channels["web"] = DummyAdapter()

    msg = ChannelMessage(
        content="hello",
        author_id="u1",
        author_name="User",
        channel_id="sess-1",
        metadata={"platform": "web", "source": "web"},
    )

    handled = await gateway._try_stream_channel_message(msg)

    assert handled is False


def test_router_chunk_text_preserves_content_order():
    parts = _chunk_text("hello world from neuralclaw", chunk_size=8)
    assert "".join(parts) == "hello world from neuralclaw"
