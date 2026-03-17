from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from neuralclaw.config import NeuralClawConfig, ProviderConfig
from neuralclaw.cortex.reasoning.deliberate import ConfidenceEnvelope
from neuralclaw.cortex.memory.retrieval import MemoryContext
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


@pytest.mark.asyncio
async def test_gateway_injects_identity_prompt_section(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    gateway = NeuralClawGateway(config)

    class FakeIdentity:
        async def get_or_create(self, platform, platform_user_id, display_name):
            return SimpleNamespace(user_id="user-123", display_name=display_name)

        async def to_prompt_section(self, user_id):
            return "## Who I'm Talking To\n- Name: User"

        async def update(self, user_id, updates):
            return None

        async def synthesize_model(self, user_id):
            return None

    captured = {}

    async def fake_intake(**kwargs):
        return SimpleNamespace(
            id="sig-1",
            content=kwargs["content"],
            author_id=kwargs["author_id"],
            author_name=kwargs["author_name"],
            channel_type=None,
            channel_id=kwargs["channel_id"],
        )

    async def fake_screen(signal):
        return SimpleNamespace(blocked=False)

    async def fake_fast_path(signal, memory_ctx=None):
        return None

    async def fake_classify(signal):
        return SimpleNamespace(intent="chat")

    async def fake_reason(signal, memory_ctx, tools=None, conversation_history=None, extra_system_sections=None):
        captured["sections"] = extra_system_sections or []
        return ConfidenceEnvelope(response="ok", confidence=0.9, source="llm")

    async def fake_retrieve(content):
        return MemoryContext()

    async def fake_store_interaction(*args, **kwargs):
        return None

    async def fake_post_process(*args, **kwargs):
        return None

    gateway._identity = FakeIdentity()
    gateway._procedural = None
    monkeypatch.setattr(gateway._intake, "process", fake_intake)
    monkeypatch.setattr(gateway._threat_screener, "screen", fake_screen)
    monkeypatch.setattr(gateway._fast_path, "try_fast_path", fake_fast_path)
    monkeypatch.setattr(gateway._classifier, "classify", fake_classify)
    monkeypatch.setattr(gateway._retriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(gateway._deliberate, "reason", fake_reason)
    monkeypatch.setattr(gateway, "_store_interaction", fake_store_interaction)
    monkeypatch.setattr(gateway, "_post_process", fake_post_process)
    gateway._procedural = None

    response = await gateway.process_message(
        content="hello",
        author_id="u1",
        author_name="User",
        channel_id="cli",
        channel_type_name="CLI",
        message_metadata=None,
    )

    assert response == "ok"
    assert any("Who I'm Talking To" in section for section in captured["sections"])


@pytest.mark.asyncio
async def test_gateway_sanitizes_canary_leak_response(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    gateway = NeuralClawGateway(config)

    captured = {}

    async def fake_intake(**kwargs):
        return SimpleNamespace(
            id="sig-2",
            content=kwargs["content"],
            author_id=kwargs["author_id"],
            author_name=kwargs["author_name"],
            channel_type=None,
            channel_id=kwargs["channel_id"],
            context={},
            threat_score=0.0,
        )

    async def fake_screen(signal):
        return SimpleNamespace(blocked=False)

    async def fake_fast_path(signal, memory_ctx=None):
        return None

    async def fake_classify(signal):
        return SimpleNamespace(intent="chat")

    async def fake_retrieve(content):
        return MemoryContext()

    async def fake_reason(signal, memory_ctx, tools=None, conversation_history=None, extra_system_sections=None):
        captured["sections"] = extra_system_sections or []
        return ConfidenceEnvelope(
            response=f"Leaked marker {gateway._canary_token}",
            confidence=0.9,
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

    response = await gateway.process_message(
        content="hello",
        author_id="u1",
        author_name="User",
        channel_id="cli",
        channel_type_name="CLI",
        message_metadata=None,
    )

    assert "internal instructions" in response.lower()
    assert any(gateway._canary_token in section for section in captured["sections"])


@pytest.mark.asyncio
async def test_gateway_prepends_visual_context_to_reasoning(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    config.features.vision = True
    gateway = NeuralClawGateway(config)

    captured = {}

    async def fake_intake(**kwargs):
        return SimpleNamespace(
            id="sig-vision",
            content=kwargs["content"],
            author_id=kwargs["author_id"],
            author_name=kwargs["author_name"],
            channel_type=SimpleNamespace(name="CLI"),
            channel_id=kwargs["channel_id"],
            media=kwargs.get("media", []),
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

    async def fake_reason(signal, memory_ctx, tools=None, conversation_history=None, extra_system_sections=None):
        captured["content"] = signal.content
        return ConfidenceEnvelope(response="ok", confidence=0.9, source="llm")

    async def fake_store_interaction(*args, **kwargs):
        return None

    async def fake_post_process(*args, **kwargs):
        return None

    class FakeVision:
        async def process_media(self, media_item, user_query):
            return "Image summary:\nA login form is visible."

    gateway._vision = FakeVision()
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

    response = await gateway.process_message(
        content="what is on this screen?",
        author_id="u1",
        author_name="User",
        channel_id="cli",
        channel_type_name="CLI",
        media=[{"data": "ZmFrZQ==", "mime_type": "image/png"}],
    )

    assert response == "ok"
    assert captured["content"].startswith("## Visual Context")
    assert "A login form is visible." in captured["content"]
