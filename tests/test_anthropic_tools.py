from __future__ import annotations

import json

import pytest

from neuralclaw.providers.anthropic import AnthropicProvider


class _FakeResponse:
    def __init__(self, payload_ref):
        self.status = 200
        self._payload_ref = payload_ref

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return ""

    async def json(self):
        return {"content": [{"type": "text", "text": "done"}], "model": "claude"}


class _FakeSession:
    def __init__(self, payload_ref):
        self._payload_ref = payload_ref

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json=None, headers=None, timeout=None):
        self._payload_ref["payload"] = json
        return _FakeResponse(self._payload_ref)


@pytest.mark.asyncio
async def test_anthropic_converts_tool_replay(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "neuralclaw.providers.anthropic.aiohttp.ClientSession",
        lambda: _FakeSession(captured),
    )

    provider = AnthropicProvider(api_key="test-key")
    await provider.complete([
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "fetch weather"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1",
            "function": {"name": "get_weather", "arguments": json.dumps({"city": "Karachi"})},
        }]},
        {"role": "tool", "tool_call_id": "call_1", "content": "{\"temp\": 80}"},
    ])

    payload = captured["payload"]
    assert payload["messages"][1]["role"] == "assistant"
    assert payload["messages"][1]["content"][0]["type"] == "tool_use"
    assert payload["messages"][2]["role"] == "user"
    assert payload["messages"][2]["content"][0]["type"] == "tool_result"
