import base64
import copy
import json
from types import SimpleNamespace

import pytest

from neuralclaw.config import DEFAULT_CONFIG, ChannelConfig, NeuralClawConfig, ProviderConfig
from neuralclaw.cortex.adaptive import AdaptiveControlPlane
from neuralclaw.gateway import NeuralClawGateway
from neuralclaw.swarm.delegation import DelegationResult, DelegationStatus
from neuralclaw.swarm.mesh import AgentMesh


class _FakeAgentStore:
    def __init__(self, existing_name: str | None = None) -> None:
        self.existing_name = existing_name
        self.created = None

    async def get_by_name(self, name: str):
        return object() if self.existing_name == name else None

    async def create(self, defn):
        self.created = defn
        return "agent-123"


class _FakeWhatsAppAdapter:
    def __init__(self, *, on_qr=None, paired: bool = False) -> None:
        self._on_qr = on_qr
        self._paired = paired
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True
        if self._on_qr and not self._paired:
            self._on_qr("whatsapp://pair-me")

    async def stop(self) -> None:
        self.stopped = True

    async def test_connection(self):
        if self._paired:
            return True, "auth files found"
        return False, "not paired"


class _FakeWorkflow:
    def __init__(self, workflow_id: str, name: str) -> None:
        self.id = workflow_id
        self.name = name

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": "idle",
            "steps": [],
        }


class _FakeWorkflowEngine:
    def __init__(self) -> None:
        self.created = None
        self.executed = []
        self.paused = []
        self.deleted = []

    async def list_workflows(self) -> list[dict]:
        return [{"id": "wf-1", "name": "sync", "status": "idle"}]

    async def create_workflow(self, name: str, steps: list[dict], description: str = "", variables: dict | None = None):
        self.created = {
            "name": name,
            "steps": steps,
            "description": description,
            "variables": variables,
        }
        return _FakeWorkflow("wf-1", name)

    async def execute_workflow(self, workflow_id: str) -> dict:
        self.executed.append(workflow_id)
        return {"success": True, "workflow_id": workflow_id, "status": "running"}

    async def pause_workflow(self, workflow_id: str) -> dict:
        self.paused.append(workflow_id)
        return {"success": True, "workflow_id": workflow_id, "status": "paused"}

    async def delete_workflow(self, workflow_id: str) -> bool:
        self.deleted.append(workflow_id)
        return workflow_id == "wf-1"


def _make_gateway() -> NeuralClawGateway:
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(
            name="local",
            model="qwen3.5:35b",
            base_url="http://localhost:11434/v1",
        ),
    )
    config._raw = copy.deepcopy(DEFAULT_CONFIG)
    config.channels = [ChannelConfig(name="telegram", enabled=False, token=None)]
    return NeuralClawGateway(config=config)


def _make_cloud_gateway() -> NeuralClawGateway:
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(
            name="openai",
            model="gpt-5.4",
            base_url="https://api.openai.com/v1",
        ),
    )
    config._raw = copy.deepcopy(DEFAULT_CONFIG)
    config._raw["providers"]["primary"] = "openai"
    config._raw["providers"]["openai"]["model"] = "gpt-5.4"
    config._raw["providers"]["openai"]["base_url"] = "https://api.openai.com/v1"
    config.channels = [ChannelConfig(name="telegram", enabled=False, token=None)]
    return NeuralClawGateway(config=config)


@pytest.mark.asyncio
async def test_dashboard_update_config_persists_provider_secret(monkeypatch):
    gateway = _make_gateway()
    saved_updates = {}
    saved_secrets = []

    reloaded = _make_gateway()._config
    reloaded._raw["providers"]["primary"] = "anthropic"
    reloaded._raw["providers"]["anthropic"]["base_url"] = "https://api.anthropic.com"

    monkeypatch.setattr("neuralclaw.gateway.update_config", lambda updates, path=None: saved_updates.update(updates))
    monkeypatch.setattr("neuralclaw.gateway.set_api_key", lambda provider, key: saved_secrets.append((provider, key)))
    monkeypatch.setattr("neuralclaw.gateway.load_config", lambda path=None: reloaded)

    result = await gateway._dashboard_update_config({
        "providers": {
            "primary": "anthropic",
            "anthropic": {"base_url": "https://api.anthropic.com"},
        },
        "provider_secrets": {"anthropic": "sk-live"},
    })

    assert result["ok"] is True
    assert result["restart_required"] is False
    assert saved_updates["providers"]["primary"] == "anthropic"
    assert ("anthropic", "sk-live") in saved_secrets


@pytest.mark.asyncio
async def test_dashboard_update_config_persists_dashboard_secret_and_host(monkeypatch):
    gateway = _make_gateway()
    saved_updates = {}
    saved_dashboard_tokens = []

    reloaded = _make_gateway()._config
    reloaded.dashboard_host = "0.0.0.0"
    reloaded._raw["dashboard_host"] = "0.0.0.0"

    monkeypatch.setattr("neuralclaw.gateway.update_config", lambda updates, path=None: saved_updates.update(updates))
    monkeypatch.setattr("neuralclaw.gateway.set_dashboard_auth_token", lambda token: saved_dashboard_tokens.append(token))
    monkeypatch.setattr("neuralclaw.gateway.load_config", lambda path=None: reloaded)
    monkeypatch.setattr("neuralclaw.gateway.get_dashboard_auth_token", lambda: "dash-secret")

    result = await gateway._dashboard_update_config({
        "dashboard_host": "0.0.0.0",
        "dashboard_secret": "dash-secret",
    })

    assert result["ok"] is True
    assert result["restart_required"] is True
    assert saved_updates["dashboard_host"] == "0.0.0.0"
    assert saved_dashboard_tokens == ["dash-secret"]
    assert result["config"]["dashboard_auth_configured"] is True


@pytest.mark.asyncio
async def test_dashboard_update_config_marks_desktop_security_changes_for_restart(monkeypatch):
    gateway = _make_gateway()
    saved_updates = {}

    reloaded = _make_gateway()._config
    reloaded._raw["desktop"]["enabled"] = True
    reloaded._raw["security"]["allow_shell_execution"] = True

    monkeypatch.setattr("neuralclaw.gateway.update_config", lambda updates, path=None: saved_updates.update(updates))
    monkeypatch.setattr("neuralclaw.gateway.load_config", lambda path=None: reloaded)

    result = await gateway._dashboard_update_config({
        "desktop": {"enabled": True},
        "security": {"allow_shell_execution": True},
    })

    assert result["ok"] is True
    assert result["restart_required"] is True
    assert saved_updates["desktop"]["enabled"] is True
    assert saved_updates["security"]["allow_shell_execution"] is True


@pytest.mark.asyncio
async def test_dashboard_create_definition_uses_provider_default_model_when_blank():
    gateway = _make_gateway()
    gateway._agent_store = _FakeAgentStore()

    result = await gateway._dashboard_create_definition({
        "name": "artist",
        "provider": "local",
        "model": "",
    })

    assert result["ok"] is True
    assert gateway._agent_store.created.model == "qwen3.5:35b"
    assert gateway._agent_store.created.base_url == "http://localhost:11434/v1"


@pytest.mark.asyncio
async def test_dashboard_create_definition_rejects_duplicate_names():
    gateway = _make_gateway()
    gateway._agent_store = _FakeAgentStore(existing_name="artist")

    result = await gateway._dashboard_create_definition({
        "name": "artist",
        "provider": "local",
        "model": "qwen3.5:35b",
    })

    assert result == {"ok": False, "error": "Agent 'artist' already exists"}


@pytest.mark.asyncio
async def test_dashboard_create_definition_defaults_blank_provider_to_primary_route():
    gateway = _make_cloud_gateway()
    gateway._agent_store = _FakeAgentStore()

    result = await gateway._dashboard_create_definition({
        "name": "planner",
        "model": "gpt-5.4",
    })

    assert result["ok"] is True
    assert gateway._agent_store.created.provider == "openai"
    assert gateway._agent_store.created.base_url == "https://api.openai.com/v1"


@pytest.mark.asyncio
async def test_dashboard_workflow_handlers_bridge_engine_calls():
    gateway = _make_gateway()
    gateway._workflow_engine = _FakeWorkflowEngine()

    listed = await gateway._dashboard_list_workflows()
    created = await gateway._dashboard_create_workflow({
        "name": "sync",
        "steps": [{"id": "s1", "name": "fetch", "action": "search"}],
        "description": "nightly sync",
        "variables": {"region": "us"},
    })
    started = await gateway._dashboard_run_workflow("wf-1")
    paused = await gateway._dashboard_pause_workflow("wf-1")
    deleted = await gateway._dashboard_delete_workflow("wf-1")

    assert listed == [{"id": "wf-1", "name": "sync", "status": "idle"}]
    assert created["ok"] is True
    assert created["workflow"]["id"] == "wf-1"
    assert gateway._workflow_engine.created == {
        "name": "sync",
        "steps": [{"id": "s1", "name": "fetch", "action": "search"}],
        "description": "nightly sync",
        "variables": {"region": "us"},
    }
    assert started == {"ok": True, "success": True, "workflow_id": "wf-1", "status": "running"}
    assert paused == {"ok": True, "success": True, "workflow_id": "wf-1", "status": "paused"}
    assert deleted == {"ok": True, "workflow_id": "wf-1"}


@pytest.mark.asyncio
async def test_dashboard_create_workflow_validates_required_name():
    gateway = _make_gateway()
    gateway._workflow_engine = _FakeWorkflowEngine()

    result = await gateway._dashboard_create_workflow({"steps": []})

    assert result == {"ok": False, "error": "Workflow name is required"}


@pytest.mark.asyncio
async def test_dashboard_pair_channel_returns_whatsapp_qr(tmp_path):
    gateway = _make_gateway()
    gateway._build_whatsapp_channel = lambda cfg, on_qr=None, on_pairing_code=None, phone_number="": _FakeWhatsAppAdapter(on_qr=on_qr)  # type: ignore[method-assign]

    result = await gateway._dashboard_pair_channel(
        "whatsapp",
        {"extra": {"auth_dir": str(tmp_path / "wa-auth")}},
    )

    assert result["ok"] is True
    assert result["paired"] is False
    assert result["auth_dir"].endswith("wa-auth")
    assert result["qr_data"] == "whatsapp://pair-me"
    assert result["qr_data_url"].startswith("data:image/svg+xml;base64,")


def test_health_payload_exposes_backend_version():
    gateway = _make_gateway()

    payload = gateway._get_health_payload()

    assert payload["version"]


@pytest.mark.asyncio
async def test_dashboard_send_message_to_agent_uses_mesh_not_delegation():
    gateway = _make_gateway()
    gateway._mesh = AgentMesh()
    gateway._agent_store = None

    async def handler(msg):
        return msg.reply("research reply", payload={"model": "qwen3.5:35b"})

    gateway._mesh.register(
        name="research",
        description="Research agent",
        capabilities=["research"],
        handler=handler,
    )

    async def fail_delegate(_payload):
        raise AssertionError("delegation path should not be used for agent chat")

    gateway._dashboard_delegate_task = fail_delegate  # type: ignore[method-assign]

    result = await gateway._dashboard_send_message({
        "content": "introduce yourself",
        "target_agent": "research",
        "session_id": "session-1",
    })

    assert result["ok"] is True
    assert result["response"] == "research reply"
    assert result["routed_to"] == "research"


@pytest.mark.asyncio
async def test_dashboard_send_message_preserves_attachments_and_provider_override(monkeypatch):
    gateway = _make_gateway()
    captured = {}

    async def fake_process_dashboard_message_with_override(**kwargs):
        captured.update(kwargs)
        return {
            "response": "processed",
            "effective_model": "venice-large",
            "fallback_reason": None,
            "memory_provenance": [],
            "memory_scopes": [],
        }

    monkeypatch.setattr(
        gateway,
        "_process_dashboard_message_with_override",
        fake_process_dashboard_message_with_override,
    )

    result = await gateway._dashboard_send_message({
        "content": "Review these",
        "provider": "venice",
        "model": "venice-large",
        "base_url": "https://api.venice.ai/api/v1",
        "documents": [{"name": "brief.md", "content": "# Notes\nShip it"}],
        "media": [{"type": "image", "content": "data:image/png;base64,ZmFrZQ==", "mime_type": "image/png"}],
    })

    assert result["ok"] is True
    assert result["effective_model"] == "venice-large"
    assert captured["provider_name"] == "venice"
    assert captured["model_name"] == "venice-large"
    assert captured["media"][0]["content"].startswith("data:image/png;base64,")
    assert "## Attached Documents" in captured["content"]
    assert "brief.md" in captured["content"]


@pytest.mark.asyncio
async def test_dashboard_message_override_swaps_in_cloud_provider_and_restores_state(monkeypatch):
    gateway = _make_gateway()
    original_provider = gateway._provider
    fake_provider = object()
    seen = {}

    async def fake_build_dashboard_override_provider(provider_name: str, model_name: str = "", base_url: str = ""):
        return fake_provider, "venice-large", "https://api.venice.ai/api/v1", None

    async def fake_process_message(**kwargs):
        seen["provider_during_call"] = gateway._provider
        seen["media"] = kwargs.get("media")
        return {"response": "ok"}

    monkeypatch.setattr(gateway, "_build_dashboard_override_provider", fake_build_dashboard_override_provider)
    monkeypatch.setattr(gateway, "process_message", fake_process_message)
    monkeypatch.setattr(gateway._deliberate, "set_provider", lambda provider: None)
    monkeypatch.setattr(gateway._deliberate, "set_role_router", lambda router: None)
    monkeypatch.setattr(gateway._classifier, "set_role_router", lambda router: None)

    result = await gateway._process_dashboard_message_with_override(
        content="hello",
        media=[{"type": "image", "content": "data:image/png;base64,ZmFrZQ=="}],
        metadata={"platform": "web"},
        provider_name="venice",
        model_name="venice-large",
        base_url="https://api.venice.ai/api/v1",
    )

    assert result["response"] == "ok"
    assert seen["provider_during_call"] is fake_provider
    assert seen["media"][0]["content"].startswith("data:image/png;base64,")
    assert gateway._provider is original_provider


@pytest.mark.asyncio
async def test_adaptive_control_plane_builds_operator_snapshot(tmp_path):
    plane = AdaptiveControlPlane(tmp_path / "adaptive.db", workspace_root=tmp_path)
    await plane.initialize()
    (tmp_path / "AGENTS.md").write_text("# Demo\n\nOperator notes for the current workspace.\n", encoding="utf-8")

    snapshot = await plane.sync_snapshot(
        tasks=[{
            "task_id": "task-1",
            "title": "Review deploy",
            "status": "awaiting_approval",
            "provider": "local",
            "effective_model": "qwen3.5:35b",
            "metadata": {
                "execution_log": [{"event": "queued", "detail": "prepared"}],
                "brief": {"integration_targets": ["github"]},
            },
            "updated_at": 123.0,
        }],
        audit_events=[{"tool_name": "github_search"}, {"tool_name": "github_search"}],
        integrations=[{"id": "github", "label": "GitHub", "connected": True}],
        kb_docs=[],
        running_agents=[{"name": "research"}],
        evolution_initiatives=[{
            "fingerprint": "abc123",
            "query": "fix provider routing",
            "strategy": "forge",
            "state": "probation",
            "failure_count": 3,
        }],
        workspace_root=tmp_path,
    )

    assert snapshot["adaptive_suggestions"]
    assert snapshot["project_brief"]["title"] == tmp_path.name
    assert snapshot["project_brief"]["preferred_provider"] == "local"
    assert snapshot["learning_diffs"][0]["probation_status"] == "probation"
    assert snapshot["recent_receipts"][0]["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_resolve_agent_execution_profile_uses_cloud_primary_defaults():
    gateway = _make_cloud_gateway()
    gateway._agent_store = SimpleNamespace(
        get_by_name=lambda _name: None,
    )

    class _Store:
        async def get_by_name(self, _name):
            return SimpleNamespace(
                provider="",
                model="",
                base_url="",
                name="planner",
                agent_id="agent-1",
            )

    gateway._agent_store = _Store()
    gateway._spawner = None

    result = await gateway._resolve_agent_execution_profile("planner")

    assert result["provider"] == "openai"
    assert result["requested_model"] == "gpt-5.4"
    assert result["base_url"] == "https://api.openai.com/v1"


@pytest.mark.asyncio
async def test_dashboard_send_message_passes_adaptive_session_metadata(monkeypatch):
    gateway = _make_gateway()
    captured = {}

    async def fake_process_dashboard_message_with_override(**kwargs):
        captured.update(kwargs)
        return {
            "response": "processed",
            "effective_model": "qwen3.5:35b",
            "confidence_contract": {"confidence": 0.81, "source": "tool_verified"},
            "memory_provenance": [],
            "memory_scopes": [],
        }

    monkeypatch.setattr(
        gateway,
        "_process_dashboard_message_with_override",
        fake_process_dashboard_message_with_override,
    )

    result = await gateway._dashboard_send_message({
        "content": "Do the thing",
        "teaching_mode": True,
        "autonomy_mode": "suggest-first",
        "project_context_id": "project-123",
        "channel_style_profile": {"tone": "brief"},
    })

    assert result["ok"] is True
    assert result["confidence_contract"]["confidence"] == 0.81
    assert captured["metadata"]["teaching_mode"] is True
    assert captured["metadata"]["autonomy_mode"] == "suggest-first"
    assert captured["metadata"]["project_context_id"] == "project-123"


@pytest.mark.asyncio
async def test_dashboard_send_message_defaults_to_desktop_autonomous_mode(monkeypatch):
    gateway = _make_gateway()
    gateway._config.desktop.autonomous_execution = True
    captured = {}

    async def fake_process_dashboard_message_with_override(**kwargs):
        captured.update(kwargs)
        return {
            "response": "processed",
            "effective_model": "qwen3.5:35b",
            "confidence_contract": {"confidence": 0.9, "source": "tool_verified"},
            "memory_provenance": [],
            "memory_scopes": [],
        }

    monkeypatch.setattr(
        gateway,
        "_process_dashboard_message_with_override",
        fake_process_dashboard_message_with_override,
    )

    result = await gateway._dashboard_send_message({
        "content": "Open the desktop app and fix settings",
    })

    assert result["ok"] is True
    assert captured["metadata"]["autonomy_mode"] == "policy-driven-autonomous"


def test_task_change_receipt_reports_partial_rollback_coverage():
    gateway = _make_gateway()
    metadata = {
        "brief": {"integration_targets": ["github", "slack"]},
        "memory_provenance": [{"memory_type": "episodic"}],
        "memory_scopes": ["identity:user-1"],
        "artifacts": [
            {"label": "file", "value": "C:/workspace/app.py"},
            {"label": "database", "value": "C:/workspace/state.db"},
            {"label": "message", "value": "slack:#ops"},
        ],
    }

    receipt = gateway._task_change_receipt(
        task_id="task-coverage",
        metadata=metadata,
        operations=["updated_files", "sent_notifications"],
    )

    assert receipt["rollback_coverage"]["status"] == "partial"
    assert any(item["resource_type"] == "file" for item in receipt["resource_entries"])
    assert any(item["resource_type"] == "memory" for item in receipt["resource_entries"])
    assert any(item["resource_type"] == "integration" for item in receipt["resource_entries"])
    assert any(item["resource_type"] == "database" for item in receipt["resource_entries"])


@pytest.mark.asyncio
async def test_dashboard_delegate_task_dry_run_does_not_execute():
    gateway = _make_gateway()
    gateway._delegation = object()

    result = await gateway._dashboard_delegate_task({
        "task": "Review this task",
        "agent_names": ["research"],
        "dry_run": True,
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["mode"] == "delegation"
    assert result["target_agents"] == ["research"]


@pytest.mark.asyncio
async def test_pipeline_and_consensus_dry_run_preview():
    gateway = _make_gateway()
    gateway._delegation = object()
    gateway._consensus = object()

    pipeline = await gateway._dashboard_pipeline_task({
        "task": "Build a release plan",
        "agent_names": ["planner", "reviewer"],
        "dry_run": True,
    })
    consensus = await gateway._dashboard_seek_consensus({
        "task": "Pick the best answer",
        "agent_names": ["alpha", "beta"],
        "strategy": "weighted_confidence",
        "dry_run": True,
    })

    assert pipeline["dry_run"] is True
    assert pipeline["mode"] == "pipeline"
    assert pipeline["agent_order"] == ["planner", "reviewer"]
    assert consensus["dry_run"] is True
    assert consensus["mode"] == "consensus"
    assert consensus["strategy"] == "weighted_confidence"


@pytest.mark.asyncio
async def test_adaptive_control_plane_review_and_project_activation(tmp_path):
    plane = AdaptiveControlPlane(tmp_path / "adaptive.db", workspace_root=tmp_path)
    await plane.initialize()
    (tmp_path / "AGENTS.md").write_text("# Demo\n\nWorkspace summary.\n", encoding="utf-8")
    await plane.sync_snapshot(
        tasks=[],
        audit_events=[],
        integrations=[],
        kb_docs=[],
        running_agents=[],
        evolution_initiatives=[{
            "fingerprint": "cycle123",
            "query": "improve retries",
            "strategy": "forge",
            "state": "observed",
            "failure_count": 3,
        }],
        workspace_root=tmp_path,
    )
    profiles = await plane.list_project_profiles()
    project_id = profiles[0]["project_id"]
    activation = await plane.activate_project(project_id, memory_snapshot={"open_tasks": []}, skill_snapshot=["search"])
    review = await plane.review_learning_diff("learning-cycle123", "approve", reviewer="tester", reason="looks safe")

    assert activation["ok"] is True
    assert activation["project_id"] == project_id
    assert review["ok"] is True
    assert review["approval_status"] == "approved"


@pytest.mark.asyncio
async def test_adaptive_snapshot_restores_file_contents(tmp_path):
    plane = AdaptiveControlPlane(tmp_path / "adaptive.db", workspace_root=tmp_path)
    await plane.initialize()
    target = tmp_path / "notes.txt"
    target.write_text("before\n", encoding="utf-8")

    snapshot_id = await plane.create_snapshot("task-restore", "manual", {
        "file_paths": [str(target)],
        "metadata": {"reason": "test"},
    })
    target.write_text("after\n", encoding="utf-8")

    result = await plane.rollback_snapshot(snapshot_id)

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert target.read_text(encoding="utf-8") == "before\n"
    assert str(target) in result["restored_paths"]


@pytest.mark.asyncio
async def test_adaptive_snapshot_removes_file_created_after_snapshot(tmp_path):
    plane = AdaptiveControlPlane(tmp_path / "adaptive.db", workspace_root=tmp_path)
    await plane.initialize()
    target = tmp_path / "generated.txt"

    snapshot_id = await plane.create_snapshot("task-delete", "manual", {
        "file_paths": [str(target)],
        "metadata": {"reason": "test"},
    })
    target.write_text("created later\n", encoding="utf-8")

    result = await plane.rollback_snapshot(snapshot_id)

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert not target.exists()
    assert str(target) in result["deleted_paths"]


@pytest.mark.asyncio
async def test_dashboard_delegate_task_orders_agents_and_passes_previous_results():
    gateway = _make_gateway()

    class _FakeDelegation:
        def __init__(self) -> None:
            self.calls = []

        async def delegate(self, agent_name, ctx):
            self.calls.append((agent_name, list(ctx.parent_memories)))
            if agent_name == "quotor":
                return DelegationResult(
                    delegation_id="",
                    status=DelegationStatus.COMPLETED,
                    result="quote-output",
                    confidence=0.9,
                )
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.COMPLETED,
                result=f"analysis:{ctx.parent_memories}",
                confidence=0.8,
            )

    gateway._delegation = _FakeDelegation()  # type: ignore[assignment]
    gateway._mesh = None
    gateway._task_store = None

    async def fake_profile(agent_name: str):
        return {
            "provider": "local",
            "requested_model": "qwen3.5:35b",
            "effective_model": "qwen3.5:35b",
            "base_url": "http://localhost:11434/v1",
            "fallback_reason": None,
        }

    gateway._resolve_agent_execution_profile = fake_profile  # type: ignore[method-assign]

    result = await gateway._dashboard_delegate_task({
        "task": "quotor will give 2 motivational quotes and research will analyse them",
        "agent_names": ["research", "quotor"],
    })

    assert result["ok"] is True
    assert [entry["agent"] for entry in result["results"]] == ["quotor", "research"]
    assert gateway._delegation.calls[0][0] == "quotor"
    assert gateway._delegation.calls[1][0] == "research"
    assert gateway._delegation.calls[1][1][0]["agent"] == "quotor"
    assert gateway._delegation.calls[1][1][0]["result"] == "quote-output"


@pytest.mark.asyncio
async def test_dashboard_memory_counts_include_vector_and_identity():
    gateway = _make_gateway()

    class _Counter:
        def __init__(self, value: int) -> None:
            self.value = value

        async def count(self) -> int:
            return self.value

    gateway._episodic = _Counter(12)  # type: ignore[assignment]
    gateway._semantic = _Counter(4)  # type: ignore[assignment]
    gateway._procedural = _Counter(3)  # type: ignore[assignment]
    gateway._vector_memory = _Counter(11)  # type: ignore[assignment]
    gateway._identity = _Counter(2)  # type: ignore[assignment]

    result = await gateway._get_dashboard_memory()

    assert result["episodic_count"] == 12
    assert result["semantic_count"] == 4
    assert result["procedural_count"] == 3
    assert result["vector_count"] == 11
    assert result["identity_count"] == 2


@pytest.mark.asyncio
async def test_dashboard_clear_memory_can_target_selected_stores():
    gateway = _make_gateway()

    class _Clearable:
        def __init__(self, value: int) -> None:
            self.value = value
            self.cleared = False

        async def clear(self) -> int:
            self.cleared = True
            return self.value

    episodic = _Clearable(10)
    semantic = _Clearable(4)
    procedural = _Clearable(2)
    vector = _Clearable(9)
    identity = _Clearable(1)
    gateway._episodic = episodic  # type: ignore[assignment]
    gateway._semantic = semantic  # type: ignore[assignment]
    gateway._procedural = procedural  # type: ignore[assignment]
    gateway._vector_memory = vector  # type: ignore[assignment]
    gateway._identity = identity  # type: ignore[assignment]
    gateway._history = ["keep-me"]  # type: ignore[assignment]

    result = await gateway._dashboard_clear_memory({"stores": ["vector", "identity"], "clear_history": False})

    assert episodic.cleared is False
    assert semantic.cleared is False
    assert procedural.cleared is False
    assert vector.cleared is True
    assert identity.cleared is True
    assert result["vector_deleted"] == 9
    assert result["identity_deleted"] == 1
    assert gateway._history == ["keep-me"]


def test_dashboard_features_include_vector_and_identity_memory():
    gateway = _make_gateway()

    result = gateway._dashboard_get_features()

    assert "vector_memory" in result
    assert "identity" in result


@pytest.mark.asyncio
async def test_dashboard_run_memory_retention_prunes_all_layers():
    gateway = _make_gateway()

    class _Prunable:
        def __init__(self, deleted: int) -> None:
            self.deleted = deleted
            self.keep_days = None

        async def prune(self, keep_days: int) -> int:
            self.keep_days = keep_days
            return self.deleted

    episodic = _Prunable(3)
    semantic = _Prunable(2)
    procedural = _Prunable(1)
    vector = _Prunable(4)
    identity = _Prunable(5)
    gateway._episodic = episodic  # type: ignore[assignment]
    gateway._semantic = semantic  # type: ignore[assignment]
    gateway._procedural = procedural  # type: ignore[assignment]
    gateway._vector_memory = vector  # type: ignore[assignment]
    gateway._identity = identity  # type: ignore[assignment]

    result = await gateway._dashboard_run_memory_retention()

    assert result["ok"] is True
    assert result["deleted"] == {
        "episodic": 3,
        "semantic": 2,
        "procedural": 1,
        "vector": 4,
        "identity": 5,
    }
    assert episodic.keep_days == gateway._config.memory.episodic_retention_days
    assert semantic.keep_days == gateway._config.memory.semantic_retention_days
    assert procedural.keep_days == gateway._config.memory.procedural_retention_days
    assert vector.keep_days == gateway._config.memory.vector_retention_days
    assert identity.keep_days == gateway._config.memory.identity_retention_days


@pytest.mark.asyncio
async def test_dashboard_export_memory_can_encrypt_backup():
    gateway = _make_gateway()

    class _RecentEpisodes:
        async def get_recent(self, limit: int = 100):
            return [
                SimpleNamespace(
                    id="ep-1",
                    timestamp=123.0,
                    source="conversation",
                    author="user",
                    content="Remember this fact",
                    importance=0.8,
                    emotional_valence=0.1,
                    tags=["scope:global"],
                )
            ]

    gateway._episodic = _RecentEpisodes()  # type: ignore[assignment]
    gateway._semantic = None  # type: ignore[assignment]
    gateway._procedural = None  # type: ignore[assignment]
    gateway._vector_memory = None  # type: ignore[assignment]
    gateway._identity = None  # type: ignore[assignment]

    result = await gateway._dashboard_export_memory({
        "stores": ["episodic"],
        "passphrase": "top-secret",
    })

    assert result["ok"] is True
    assert result["encrypted"] is True
    assert result["payload"]
    assert result["salt"]
    assert result["digest"]


@pytest.mark.asyncio
async def test_dashboard_import_memory_restores_supported_layers():
    gateway = _make_gateway()

    class _FakeEpisodic:
        def __init__(self) -> None:
            self.saved = []

        async def store(self, **kwargs):
            self.saved.append(kwargs)

    class _FakeSemantic:
        def __init__(self) -> None:
            self.saved = []

        async def upsert_entity(self, name: str, entity_type: str, attributes: dict):
            self.saved.append((name, entity_type, attributes))

    class _FakeProcedural:
        def __init__(self) -> None:
            self.saved = []

        async def store_procedure(self, **kwargs):
            self.saved.append(kwargs)

    class _FakeVector:
        def __init__(self) -> None:
            self.saved = []

        async def embed_and_store(self, content_preview: str, ref_id: str, source: str):
            self.saved.append((content_preview, ref_id, source))

    class _FakeIdentity:
        def __init__(self) -> None:
            self.created = []
            self.updated = []

        async def get(self, user_id: str):
            return None

        async def get_or_create(self, platform: str, platform_user_id: str, display_name: str):
            self.created.append((platform, platform_user_id, display_name))
            return SimpleNamespace(user_id=platform_user_id)

        async def update(self, user_id: str, payload: dict):
            self.updated.append((user_id, payload))

    episodic = _FakeEpisodic()
    semantic = _FakeSemantic()
    procedural = _FakeProcedural()
    vector = _FakeVector()
    identity = _FakeIdentity()
    gateway._episodic = episodic  # type: ignore[assignment]
    gateway._semantic = semantic  # type: ignore[assignment]
    gateway._procedural = procedural  # type: ignore[assignment]
    gateway._vector_memory = vector  # type: ignore[assignment]
    gateway._identity = identity  # type: ignore[assignment]

    backup = {
        "version": 1,
        "stores": {
            "episodic": [{
                "content": "Imported episode",
                "source": "conversation",
                "author": "user",
                "importance": 0.7,
                "emotional_valence": 0.2,
                "tags": ["scope:session:test"],
            }],
            "semantic": [{
                "name": "NeuralClaw",
                "entity_type": "product",
                "attributes": {"tier": "desktop"},
            }],
            "procedural": [{
                "name": "handoff",
                "description": "Pass work to another agent",
                "trigger_patterns": ["delegate"],
                "steps": [{
                    "action": "delegate",
                    "description": "Send task to agent",
                    "parameters": {"target": "research"},
                    "expected_output": "completed task",
                }],
            }],
            "vector": [{
                "content_preview": "Embedded knowledge chunk",
                "ref_id": "kb-1",
                "source": "knowledge_base",
            }],
            "identity": [{
                "user_id": "user-123",
                "display_name": "Lenovo",
                "platform_aliases": {"desktop": "user-123"},
                "communication_style": {"tone": "direct"},
                "active_projects": ["NeuralClaw Desktop"],
                "expertise_domains": ["product"],
                "language": "en",
                "timezone": "Asia/Karachi",
                "preferences": {"reply_style": "concise"},
                "last_seen": 1.0,
                "first_seen": 1.0,
                "session_count": 2,
                "message_count": 6,
                "notes": "Imported identity",
            }],
        },
    }
    payload = base64.b64encode(json.dumps(backup).encode("utf-8")).decode("utf-8")

    result = await gateway._dashboard_import_memory({"payload": payload})

    assert result == {
        "ok": True,
        "imported": {
            "episodic": 1,
            "semantic": 1,
            "procedural": 1,
            "vector": 1,
            "identity": 1,
        },
    }
    assert episodic.saved[0]["content"] == "Imported episode"
    assert semantic.saved[0][0] == "NeuralClaw"
    assert procedural.saved[0]["name"] == "handoff"
    assert vector.saved[0] == ("Embedded knowledge chunk", "kb-1", "knowledge_base")
    assert identity.created[0][0] == "desktop"
    assert identity.updated[0][0] == "user-123"
