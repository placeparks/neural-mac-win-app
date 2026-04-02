import copy

import pytest

from neuralclaw.config import DEFAULT_CONFIG, ChannelConfig, NeuralClawConfig, ProviderConfig
from neuralclaw.gateway import NeuralClawGateway


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
    assert result["restart_required"] is True
    assert saved_updates["providers"]["primary"] == "anthropic"
    assert ("anthropic", "sk-live") in saved_secrets


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
async def test_dashboard_create_definition_requires_model():
    gateway = _make_gateway()
    gateway._agent_store = _FakeAgentStore()

    result = await gateway._dashboard_create_definition({
        "name": "artist",
        "provider": "local",
        "model": "",
    })

    assert result == {"ok": False, "error": "Model is required"}


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
async def test_dashboard_pair_channel_returns_whatsapp_qr(tmp_path):
    gateway = _make_gateway()
    gateway._build_whatsapp_channel = lambda cfg, on_qr=None: _FakeWhatsAppAdapter(on_qr=on_qr)  # type: ignore[method-assign]

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
