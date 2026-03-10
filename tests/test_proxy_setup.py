"""Tests for proxy setup flow and update_config() helper."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import toml

from neuralclaw.config import (
    _deep_merge,
    update_config,
    load_config,
    set_api_key,
    get_api_key,
)


class TestUpdateConfig:
    """Tests for the update_config() helper."""

    def setup_method(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="neuralclaw_test_")
        self._config_path = Path(self._tmpdir) / "config.toml"

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_creates_config_if_missing(self) -> None:
        assert not self._config_path.exists()
        update_config({"providers": {"proxy": {"base_url": "http://localhost:3040/v1"}}}, path=self._config_path)
        assert self._config_path.exists()

        data = toml.load(self._config_path)
        assert data["providers"]["proxy"]["base_url"] == "http://localhost:3040/v1"

    def test_merges_without_clobbering(self) -> None:
        # Write initial config
        initial = {
            "general": {"name": "TestBot"},
            "providers": {
                "primary": "openai",
                "openai": {"model": "gpt-4o"},
                "proxy": {"model": "gpt-4", "base_url": ""},
            },
        }
        with open(self._config_path, "w") as f:
            toml.dump(initial, f)

        # Update just the proxy base_url
        update_config(
            {"providers": {"proxy": {"base_url": "http://myproxy:8000/v1"}}},
            path=self._config_path,
        )

        data = toml.load(self._config_path)
        # Proxy updated
        assert data["providers"]["proxy"]["base_url"] == "http://myproxy:8000/v1"
        # Proxy model preserved
        assert data["providers"]["proxy"]["model"] == "gpt-4"
        # Other providers preserved
        assert data["providers"]["openai"]["model"] == "gpt-4o"
        assert data["providers"]["primary"] == "openai"
        # General preserved
        assert data["general"]["name"] == "TestBot"

    def test_update_primary_provider(self) -> None:
        initial = {"providers": {"primary": "openai"}}
        with open(self._config_path, "w") as f:
            toml.dump(initial, f)

        update_config({"providers": {"primary": "proxy"}}, path=self._config_path)

        data = toml.load(self._config_path)
        assert data["providers"]["primary"] == "proxy"

    def test_returns_config_path(self) -> None:
        result = update_config({"general": {"name": "Foo"}}, path=self._config_path)
        assert result == self._config_path

    def test_update_channel_enabled(self) -> None:
        initial = {"channels": {"telegram": {"enabled": False}}}
        with open(self._config_path, "w") as f:
            toml.dump(initial, f)

        update_config({"channels": {"whatsapp": {"enabled": True}}}, path=self._config_path)

        data = toml.load(self._config_path)
        # WhatsApp added
        assert data["channels"]["whatsapp"]["enabled"] is True
        # Telegram preserved
        assert data["channels"]["telegram"]["enabled"] is False
