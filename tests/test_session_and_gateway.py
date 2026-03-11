from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from neuralclaw.config import NeuralClawConfig, ProviderConfig
from neuralclaw.gateway import NeuralClawGateway
from neuralclaw.providers.app_session import AppSessionProvider
from neuralclaw.session.runtime import ManagedBrowserSession, SessionRuntimeConfig


class DummyProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.supports_tools = True

    async def complete(self, messages, tools=None, temperature=0.7, max_tokens=4096):
        raise AssertionError("not used")

    async def is_available(self):
        return True


def test_gateway_provider_override_uses_configured_proxy(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="llama3", base_url="http://localhost:11434/v1"),
        _raw={"providers": {"proxy": {"base_url": "http://proxy.local/v1", "model": "gpt-4.1"}}},
    )
    gateway = NeuralClawGateway(config, provider_override="proxy")

    captured = {}

    def fake_build_proxy(cfg):
        captured["base_url"] = cfg.base_url
        captured["model"] = cfg.model
        return DummyProvider("proxy")

    monkeypatch.setattr(gateway, "_build_proxy", fake_build_proxy)
    router = gateway._build_provider()
    assert router is not None
    assert captured["base_url"] == "http://proxy.local/v1"
    assert captured["model"] == "gpt-4.1"


def test_gateway_provider_override_uses_configured_chatgpt_app(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="llama3", base_url="http://localhost:11434/v1"),
        _raw={"providers": {"chatgpt_app": {"profile_dir": "/tmp/chatgpt", "site_url": "https://chatgpt.com/", "model": "auto"}}},
    )
    gateway = NeuralClawGateway(config, provider_override="chatgpt_app")

    captured = {}

    def fake_build_chatgpt(cfg):
        captured["profile_dir"] = cfg.profile_dir
        return DummyProvider("chatgpt_app")

    monkeypatch.setattr(gateway, "_build_chatgpt_app", fake_build_chatgpt)
    router = gateway._build_provider()
    assert router is not None
    assert captured["profile_dir"] == "/tmp/chatgpt"


@pytest.mark.asyncio
async def test_managed_browser_session_reports_missing_playwright(monkeypatch):
    runtime = ManagedBrowserSession(SessionRuntimeConfig(
        provider="chatgpt_app",
        profile_dir="/tmp/chatgpt",
        site_url="https://chatgpt.com/",
    ))
    monkeypatch.setattr(ManagedBrowserSession, "is_supported", property(lambda self: False))
    health = await runtime.health()
    assert not health.ready
    assert "Playwright" in health.message


@pytest.mark.asyncio
async def test_app_session_provider_health(monkeypatch):
    provider = AppSessionProvider(
        provider_name="chatgpt_app",
        model="auto",
        profile_dir="/tmp/chatgpt",
        site_url="https://chatgpt.com/",
    )

    async def fake_health():
        return SimpleNamespace(
            provider="chatgpt_app",
            ready=True,
            logged_in=True,
            state="ready",
            message="session ready",
            recommendation="",
            last_completion_at=None,
        )

    monkeypatch.setattr(provider._runtime, "health", fake_health)
    health = await provider.get_health()
    assert health["logged_in"] is True
    assert health["supports_tools"] is False


def test_managed_browser_session_runtime_contains_stealth_hardening():
    source = Path("neuralclaw/session/runtime.py").read_text(encoding="utf-8")

    assert "ignore_default_args" in source
    assert "--enable-automation" in source
    assert "--disable-blink-features=AutomationControlled" in source
    assert "navigator, 'webdriver'" in source


@pytest.mark.asyncio
async def test_managed_browser_session_detects_auth_rejection(monkeypatch):
    runtime = ManagedBrowserSession(SessionRuntimeConfig(
        provider="chatgpt_app",
        profile_dir="/tmp/chatgpt",
        site_url="https://chatgpt.com/",
    ))

    class FakeBody:
        async def inner_text(self):
            return ""

    class FakeLocator:
        def __init__(self, selector):
            self.selector = selector

        async def count(self):
            return 0

        async def inner_text(self):
            return ""

    class FakePage:
        url = "https://chatgpt.com/api/auth/error"

        async def goto(self, *_args, **_kwargs):
            return None

        async def title(self):
            return "ChatGPT"

        def locator(self, selector):
            if selector == "body":
                return FakeBody()
            return FakeLocator(selector)

    async def fake_launch(*_args, **_kwargs):
        runtime._page = FakePage()

    monkeypatch.setattr(runtime, "launch", fake_launch)
    monkeypatch.setattr(ManagedBrowserSession, "is_supported", property(lambda self: True))

    health = await runtime.health()

    assert health.state == "auth_rejected"
    assert not health.logged_in
    assert "proxy" in health.recommendation


@pytest.mark.asyncio
async def test_gateway_routes_slack_reply_with_thread_ts(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    gateway = NeuralClawGateway(config)

    class DummyAdapter:
        def __init__(self):
            self.calls = []

        async def send(self, channel_id, content, **kwargs):
            self.calls.append((channel_id, content, kwargs))

    adapter = DummyAdapter()
    gateway._channels["slack"] = adapter

    async def fake_process_message(**_kwargs):
        return "paired response"

    monkeypatch.setattr(gateway, "process_message", fake_process_message)

    msg = SimpleNamespace(
        content="hello",
        author_id="u1",
        author_name="User",
        channel_id="C123",
        raw=None,
        metadata={"platform": "slack", "thread_ts": "12345.67"},
    )

    await gateway._on_channel_message(msg)

    assert adapter.calls == [("C123", "paired response", {"thread_ts": "12345.67"})]
