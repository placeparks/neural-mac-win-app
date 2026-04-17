from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from neuralclaw.config import NeuralClawConfig, ProviderConfig
from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.action.policy import RequestContext
from neuralclaw.cortex.perception.intake import ChannelType, Signal
from neuralclaw.cortex.reasoning.deliberate import ConfidenceEnvelope, DeliberativeReasoner, ToolDef
from neuralclaw.cortex.memory.retrieval import MemoryContext
from neuralclaw.errors import ProviderError
from neuralclaw.gateway import NeuralClawGateway
from neuralclaw.health import ReadinessProbe, ReadinessState
from neuralclaw.providers.app_session import AppSessionProvider
from neuralclaw.providers.router import LLMResponse, ToolCall
from neuralclaw.session.runtime import ManagedBrowserSession, SessionRuntimeConfig
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition
from neuralclaw.swarm.delegation import DelegationResult, DelegationStatus
from neuralclaw.swarm.task_store import TaskRecord


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


def test_gateway_provider_override_uses_configured_vercel_gateway(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="llama3", base_url="http://localhost:11434/v1"),
        _raw={"providers": {"vercel": {"base_url": "https://ai-gateway.vercel.sh/v1", "model": "openai/gpt-5.4"}}},
    )
    gateway = NeuralClawGateway(config, provider_override="vercel")

    captured = {}

    def fake_openai_compatible(provider_name, cfg, *, default_model, default_base_url, request_timeout_seconds=None):
        captured["provider_name"] = provider_name
        captured["base_url"] = cfg.base_url
        captured["model"] = cfg.model
        captured["default_model"] = default_model
        captured["default_base_url"] = default_base_url
        return DummyProvider("vercel")

    monkeypatch.setattr(gateway, "_build_openai_compatible", fake_openai_compatible)
    router = gateway._build_provider()
    assert router is not None
    assert captured["provider_name"] == "vercel"
    assert captured["base_url"] == "https://ai-gateway.vercel.sh/v1"
    assert captured["model"] == "openai/gpt-5.4"


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
async def test_gateway_lists_active_user_skills_authoritatively(tmp_path):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    gateway = NeuralClawGateway(config)
    gateway._config.forge.user_skills_dir = str(tmp_path)
    (tmp_path / "user_monitor.py").write_text("# stub\n", encoding="utf-8")

    gateway._skills.hot_register(
        SkillManifest(
            name="user_monitor",
            description="User monitor",
            tools=[ToolDefinition(name="list_processes", description="List", handler=None)],
        ),
        source="user",
    )

    payload = await gateway._list_active_user_skills_tool()

    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["skills"][0]["name"] == "user_monitor"
    assert payload["skills"][0]["file_exists"] is True
    assert payload["ghost_skills"] == []


def test_gateway_builds_dedicated_forge_provider_with_relaxed_timeouts():
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    config.forge.provider_request_timeout_seconds = 360
    config.forge.provider_max_retries = 0
    config.forge.provider_circuit_timeout_seconds = 12
    config.forge.provider_slow_call_threshold_ms = 240000

    gateway = NeuralClawGateway(config)
    router = gateway._build_forge_provider()

    assert router is not None
    assert getattr(router._primary, "_request_timeout_seconds", None) == 360
    assert router._max_retries == 0
    assert router._breaker_config.timeout_seconds == 12
    assert router._breaker_config.slow_call_threshold_ms == 240000


def test_confidence_envelope_exposes_contract_fields():
    envelope = ConfidenceEnvelope(
        response="done",
        confidence=0.62,
        source="tool_verified",
        uncertainty_factors=["hedging_language"],
        tool_calls_made=2,
        evidence_sources=["memory", "tool_execution"],
        escalation_recommendation="operator_review_recommended",
        retry_rationale="Needed one corrective retry.",
    )

    payload = envelope.to_dict()

    assert payload["tool_calls_made"] == 2
    assert payload["evidence_sources"] == ["memory", "tool_execution"]
    assert payload["escalation_recommendation"] == "operator_review_recommended"


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


@pytest.mark.asyncio
async def test_gateway_rate_limits_repeated_messages(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    config.policy.user_requests_per_minute = 1
    gateway = NeuralClawGateway(config)

    async def fake_intake(**kwargs):
        return SimpleNamespace(
            id="sig-rate",
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

    async def fake_reason(signal, memory_ctx, tools=None, conversation_history=None, extra_system_sections=None):
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

    first = await gateway.process_message("hello", author_id="u1", author_name="User")
    second = await gateway.process_message("hello again", author_id="u1", author_name="User")

    assert first == "ok"
    assert "too quickly" in second


@pytest.mark.asyncio
async def test_gateway_pipeline_task_persists_stage_checkpoints(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    gateway = NeuralClawGateway(config)

    class FakeTaskStore:
        def __init__(self):
            self.records: dict[str, TaskRecord] = {}

        async def create(self, record: TaskRecord) -> str:
            record.task_id = record.task_id or f"task-{len(self.records) + 1}"
            self.records[record.task_id] = record
            return record.task_id

        async def get(self, task_id: str) -> TaskRecord | None:
            return self.records.get(task_id)

        async def update(self, task_id: str, **kwargs):
            record = self.records[task_id]
            for key, value in kwargs.items():
                setattr(record, key, value)
            return True

    class FakeDelegation:
        async def delegate(self, agent: str, ctx):
            stage_role = ctx.constraints["pipeline_stage_role"]
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.COMPLETED,
                result=f"{stage_role} output from {agent}",
                confidence=0.9,
                elapsed_seconds=0.25,
            )

    async def fake_retrieve(_content: str):
        return MemoryContext()

    gateway._task_store = FakeTaskStore()
    gateway._delegation = FakeDelegation()
    gateway._shared_bridge = None
    monkeypatch.setattr(gateway._retriever, "retrieve", fake_retrieve)

    result = await gateway._dashboard_pipeline_task({
        "task": "Ship the feature",
        "agent_names": ["planner", "executor", "reviewer"],
        "success_criteria": "A reviewed final answer",
    })

    assert result["ok"] is True
    assert result["status"] == "completed"
    task_id = result["task_id"]
    assert task_id is not None
    stored = gateway._task_store.records[task_id]
    checkpoints = stored.metadata["checkpoints"]
    assert [item["stage_role"] for item in checkpoints] == ["planner", "executor", "reviewer"]
    assert stored.metadata["plan"]["stages"][0]["agent"] == "planner"
    assert stored.metadata["review"]["status"] == "approved"
    assert stored.metadata["steps"][-1]["stage_role"] == "reviewer"


@pytest.mark.asyncio
async def test_gateway_pipeline_task_returns_partial_progress(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    gateway = NeuralClawGateway(config)

    class FakeTaskStore:
        def __init__(self):
            self.records: dict[str, TaskRecord] = {}

        async def create(self, record: TaskRecord) -> str:
            record.task_id = record.task_id or f"task-{len(self.records) + 1}"
            self.records[record.task_id] = record
            return record.task_id

        async def get(self, task_id: str) -> TaskRecord | None:
            return self.records.get(task_id)

        async def update(self, task_id: str, **kwargs):
            record = self.records[task_id]
            for key, value in kwargs.items():
                setattr(record, key, value)
            return True

    class FakeDelegation:
        async def delegate(self, agent: str, ctx):
            stage_index = ctx.constraints["pipeline_stage_index"]
            if stage_index == 0:
                return DelegationResult(
                    delegation_id="",
                    status=DelegationStatus.COMPLETED,
                    result=f"planned by {agent}",
                    confidence=0.9,
                    elapsed_seconds=0.2,
                )
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.FAILED,
                result="",
                error=f"{agent} failed",
                confidence=0.1,
                elapsed_seconds=0.2,
            )

    async def fake_retrieve(_content: str):
        return MemoryContext()

    gateway._task_store = FakeTaskStore()
    gateway._delegation = FakeDelegation()
    gateway._shared_bridge = None
    monkeypatch.setattr(gateway._retriever, "retrieve", fake_retrieve)

    result = await gateway._dashboard_pipeline_task({
        "task": "Try the staged run",
        "agent_names": ["planner", "reviewer"],
    })

    assert result["ok"] is True
    assert result["status"] == "partial"
    task_id = result["task_id"]
    assert task_id is not None
    stored = gateway._task_store.records[task_id]
    assert stored.status == "partial"
    assert len(stored.metadata["checkpoints"]) == 2
    assert stored.metadata["review"]["status"] == "needs_attention"


@pytest.mark.asyncio
async def test_gateway_operator_brief_includes_integration_activity(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    gateway = NeuralClawGateway(config)

    async def fake_memory():
        return {"episodic_count": 2, "semantic_count": 1}

    async def fake_tasks(limit=12):
        return [
            {
                "task_id": "task-1",
                "title": "GitHub triage",
                "status": "partial",
                "result_preview": "CI is failing on the main PR.",
                "metadata": {
                    "brief": {
                        "integration_targets": ["github"],
                    },
                },
            },
        ]

    async def fake_audit(_filters=None):
        return {
            "events": [
                {
                    "tool_name": "github_get_pull_request",
                    "allowed": True,
                    "success": True,
                },
            ],
            "stats": {"denied_records": 0, "total_records": 1},
        }

    async def fake_integrations():
        return {
            "integrations": [
                {
                    "id": "github",
                    "label": "GitHub",
                    "category": "developer",
                    "connected": True,
                    "summary": "PRs and CI",
                    "details": {"identity": {"login": "octocat"}},
                },
            ],
        }

    async def fake_kb_docs():
        return []

    async def fake_running_agents():
        return []

    monkeypatch.setattr(gateway, "_get_dashboard_memory", fake_memory)
    monkeypatch.setattr(gateway, "_dashboard_list_tasks", fake_tasks)
    monkeypatch.setattr(gateway, "_dashboard_get_audit", fake_audit)
    monkeypatch.setattr(gateway, "_dashboard_list_integrations", fake_integrations)
    monkeypatch.setattr(gateway, "_dashboard_list_kb_documents", fake_kb_docs)
    monkeypatch.setattr(gateway, "_dashboard_get_running_agents", fake_running_agents)

    brief = await gateway._dashboard_get_operator_brief()

    assert brief["ok"] is True
    assert brief["integration_context"][0]["id"] == "github"
    assert brief["integration_context"][0]["health"] == "warning"
    assert brief["integration_context"][0]["account"] == "octocat"
    assert any(action["integration_targets"] == ["github"] for action in brief["recommended_actions"])


@pytest.mark.asyncio
async def test_deliberative_tool_failures_emit_non_empty_error_detail():
    class BlankError(Exception):
        def __str__(self) -> str:
            return ""

    class AuditCapture:
        def __init__(self) -> None:
            self.records: list[dict[str, object]] = []

        async def log_action(self, **kwargs):
            self.records.append(kwargs)

    async def boom_tool(**_kwargs):
        raise BlankError()

    bus = NeuralBus()
    audit = AuditCapture()
    reasoner = DeliberativeReasoner(bus=bus, audit=audit)
    await bus.start()
    try:
        result = await reasoner._execute_tool_call(
            SimpleNamespace(name="forge_skill", arguments={}),
            [
                ToolDef(
                    name="forge_skill",
                    description="Forge a skill",
                    parameters={"type": "object", "properties": {}},
                    handler=boom_tool,
                )
            ],
            RequestContext(request_id="req-1", user_id="u1", channel_id="dashboard", platform="cli"),
        )
        await asyncio.sleep(0)
        events = [event for event in bus.get_event_log() if event.type == EventType.ACTION_COMPLETE]
    finally:
        await bus.stop()

    assert result["error"] == "BlankError()"
    assert audit.records[-1]["result_preview"] == "BlankError()"
    assert events[-1].data["error"] == "BlankError()"


@pytest.mark.asyncio
async def test_deliberative_retries_when_reply_only_describes_plan():
    class StubProvider:
        def __init__(self) -> None:
            self.calls = 0
            self.supports_tools = True

        async def complete(self, messages, tools=None, temperature=0.7, max_tokens=4096):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content="I'll create the file and wire it up for you.")
            if self.calls == 2:
                assert tools is not None
                return LLMResponse(
                    tool_calls=[ToolCall(id="tc-1", name="write_file", arguments={"path": "quote.txt"})]
                )
            return LLMResponse(content="Created the file and finished the task.")

        async def is_available(self):
            return True

    async def fake_tool(**_kwargs):
        return {"ok": True}

    bus = NeuralBus()
    reasoner = DeliberativeReasoner(bus=bus)
    reasoner.set_provider(StubProvider())
    await bus.start()
    try:
        envelope = await reasoner.reason(
            signal=Signal(
                id="sig-1",
                channel_type=ChannelType.WEB,
                channel_id="dashboard",
                author_id="u1",
                author_name="User",
                content="Create the file now",
            ),
            memory_ctx=MemoryContext(),
            tools=[
                ToolDef(
                    name="write_file",
                    description="Write a file",
                    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
                    handler=fake_tool,
                )
            ],
        )
    finally:
        await bus.stop()

    assert envelope.response == "Created the file and finished the task."
    assert envelope.tool_calls_made == 1


@pytest.mark.asyncio
async def test_gateway_readiness_failure_raises_provider_error():
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    gateway = NeuralClawGateway(config)

    async def bad_probe() -> bool:
        return False

    gateway._health._probes = [
        gateway._health._probes[0],
        ReadinessProbe(name="forced_failure", required=True, check=bad_probe),
    ]

    with pytest.raises(ProviderError):
        await gateway._run_startup_readiness()


@pytest.mark.asyncio
async def test_gateway_health_payload_exposes_runtime_contract():
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    gateway = NeuralClawGateway(config)
    gateway._startup_readiness = ReadinessState.READY
    gateway._ready_at = 123.0

    payload = gateway._get_health_payload()

    assert payload["runtime"]["process_state"] == "running"
    assert payload["runtime"]["dashboard_bound"] is True
    assert "adaptive_ready" in payload["runtime"]
    assert payload["ready_at"] == 123.0


@pytest.mark.asyncio
async def test_gateway_operator_brief_includes_database_recommendation(monkeypatch):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    gateway = NeuralClawGateway(config)

    async def fake_memory():
        return {"episodic_count": 0, "semantic_count": 0}

    async def fake_tasks(limit=12):
        return []

    async def fake_audit(payload=None):
        return {"events": [], "stats": {"denied_records": 0, "total_records": 0}}

    async def fake_integrations():
        return {"integrations": [{
            "id": "db:sales_db",
            "label": "sales_db",
            "category": "database",
            "connected": True,
            "summary": "Postgres analytical connection",
        }]}

    async def fake_kb():
        return []

    async def fake_agents():
        return []

    monkeypatch.setattr(gateway, "_get_dashboard_memory", fake_memory)
    monkeypatch.setattr(gateway, "_dashboard_list_tasks", fake_tasks)
    monkeypatch.setattr(gateway, "_dashboard_get_audit", fake_audit)
    monkeypatch.setattr(gateway, "_dashboard_list_integrations", fake_integrations)
    monkeypatch.setattr(gateway, "_dashboard_list_kb_documents", fake_kb)
    monkeypatch.setattr(gateway, "_dashboard_get_running_agents", fake_agents)

    brief = await gateway._dashboard_get_operator_brief()

    assert any(action["id"].startswith("database-brief-") for action in brief["recommended_actions"])
