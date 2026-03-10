"""Tests for ToolCall.to_dict() JSON-string fix and BaileysWhatsAppAdapter."""

import io
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from neuralclaw.providers.router import ToolCall
from neuralclaw.channels.whatsapp_baileys import (
    BaileysWhatsAppAdapter,
    ensure_baileys_installed,
    render_qr_terminal,
)


# ---------------------------------------------------------------------------
# ToolCall.to_dict() — arguments must be a JSON string
# ---------------------------------------------------------------------------


class TestToolCallToDict:
    def test_arguments_is_json_string(self):
        tc = ToolCall(id="call_1", name="get_weather", arguments={"city": "Karachi"})
        result = tc.to_dict()
        args = result["function"]["arguments"]
        assert isinstance(args, str), f"Expected str, got {type(args)}"
        assert json.loads(args) == {"city": "Karachi"}

    def test_empty_arguments(self):
        tc = ToolCall(id="call_2", name="noop", arguments={})
        result = tc.to_dict()
        assert result["function"]["arguments"] == "{}"

    def test_nested_arguments_serialized(self):
        nested = {"filters": {"status": "active", "tags": ["a", "b"]}}
        tc = ToolCall(id="call_3", name="search", arguments=nested)
        result = tc.to_dict()
        assert json.loads(result["function"]["arguments"]) == nested

    def test_dict_structure(self):
        tc = ToolCall(id="call_4", name="fn", arguments={"x": 1})
        d = tc.to_dict()
        assert d["id"] == "call_4"
        assert d["type"] == "function"
        assert d["function"]["name"] == "fn"


# ---------------------------------------------------------------------------
# BaileysWhatsAppAdapter — basic unit tests (no subprocess)
# ---------------------------------------------------------------------------


class TestBaileysWhatsAppAdapter:
    def test_name(self):
        adapter = BaileysWhatsAppAdapter()
        assert adapter.name == "whatsapp-baileys"

    def test_custom_auth_dir(self):
        adapter = BaileysWhatsAppAdapter(auth_dir="/tmp/my_auth")
        assert adapter._auth_dir == "/tmp/my_auth"

    def test_bridge_script_contains_baileys(self):
        adapter = BaileysWhatsAppAdapter()
        script = adapter._get_bridge_script()
        assert "@whiskeysockets/baileys" in script
        assert "puppeteer" not in script.lower()

    def test_bridge_script_uses_auth_dir(self):
        adapter = BaileysWhatsAppAdapter(auth_dir="my_custom_auth")
        script = adapter._get_bridge_script()
        assert "my_custom_auth" in script

    def test_on_qr_callback_stored(self):
        cb = lambda qr: None
        adapter = BaileysWhatsAppAdapter(on_qr=cb)
        assert adapter._on_qr is cb

    @pytest.mark.asyncio
    async def test_send_raises_when_not_running(self):
        adapter = BaileysWhatsAppAdapter()
        with pytest.raises(RuntimeError, match="not running"):
            await adapter.send("123@s.whatsapp.net", "hello")

    def test_callbacks_inherited(self):
        adapter = BaileysWhatsAppAdapter()
        assert hasattr(adapter, "_callbacks")
        assert adapter._callbacks == []

    @pytest.mark.asyncio
    async def test_connection_no_auth_dir(self):
        adapter = BaileysWhatsAppAdapter(auth_dir="/nonexistent/path")
        ok, msg = await adapter.test_connection()
        assert ok is False
        assert "does not exist" in msg

    @pytest.mark.asyncio
    async def test_connection_with_creds(self):
        tmpdir = tempfile.mkdtemp(prefix="wa_test_")
        try:
            creds = Path(tmpdir) / "creds.json"
            creds.write_text("{}")
            adapter = BaileysWhatsAppAdapter(auth_dir=tmpdir)
            ok, msg = await adapter.test_connection()
            assert ok is True
            assert "auth files found" in msg
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_connection_empty_auth_dir(self):
        tmpdir = tempfile.mkdtemp(prefix="wa_test_")
        try:
            adapter = BaileysWhatsAppAdapter(auth_dir=tmpdir)
            ok, msg = await adapter.test_connection()
            assert ok is False
            assert "not paired" in msg
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# render_qr_terminal
# ---------------------------------------------------------------------------


class TestRenderQrTerminal:
    def test_renders_qr_in_panel(self):
        mock_console = MagicMock()
        render_qr_terminal("https://example.com", mock_console)
        mock_console.print.assert_called_once()
        # The argument should be a Rich Panel
        call_args = mock_console.print.call_args
        from rich.panel import Panel
        assert isinstance(call_args[0][0], Panel)

    def test_fallback_without_qrcode(self, monkeypatch):
        import neuralclaw.channels.whatsapp_baileys as mod
        # Simulate qrcode import failure
        import builtins
        real_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == "qrcode":
                raise ImportError("no qrcode")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", mock_import)
        mock_console = MagicMock()
        render_qr_terminal("test-data", mock_console)
        mock_console.print.assert_called_once()
        call_str = str(mock_console.print.call_args)
        assert "test-data" in call_str


# ---------------------------------------------------------------------------
# ensure_baileys_installed — auto-install logic
# ---------------------------------------------------------------------------


class TestEnsureBaileysInstalled:
    def test_raises_without_node(self, monkeypatch):
        """Should raise RuntimeError when Node.js is not in PATH."""
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        with pytest.raises(RuntimeError, match="Node.js not found"):
            ensure_baileys_installed()

    def test_skips_install_when_already_present(self, tmp_path, monkeypatch):
        """Should return immediately if baileys node_modules already exist."""
        import neuralclaw.channels.whatsapp_baileys as mod
        monkeypatch.setattr(mod, "BRIDGE_DIR", tmp_path)
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

        # Create the marker directory
        marker = tmp_path / "node_modules" / "@whiskeysockets" / "baileys"
        marker.mkdir(parents=True)

        result = ensure_baileys_installed()
        assert result == tmp_path

    def test_creates_package_json_and_runs_npm(self, tmp_path, monkeypatch):
        """Should create package.json and invoke npm install."""
        import neuralclaw.channels.whatsapp_baileys as mod
        monkeypatch.setattr(mod, "BRIDGE_DIR", tmp_path)
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

        # Mock subprocess.run to simulate successful npm install
        def fake_npm_install(*args, **kwargs):
            # Create the marker so subsequent calls see it
            marker = tmp_path / "node_modules" / "@whiskeysockets" / "baileys"
            marker.mkdir(parents=True, exist_ok=True)
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        import subprocess as sp_mod
        monkeypatch.setattr(sp_mod, "run", fake_npm_install)

        result = ensure_baileys_installed(quiet=True)
        assert result == tmp_path
        # Should have created package.json
        pkg = tmp_path / "package.json"
        assert pkg.exists()
        data = json.loads(pkg.read_text())
        assert "@whiskeysockets/baileys" in data["dependencies"]
        assert "@hapi/boom" in data["dependencies"]

    def test_raises_on_npm_failure(self, tmp_path, monkeypatch):
        """Should raise RuntimeError when npm install fails."""
        import neuralclaw.channels.whatsapp_baileys as mod
        monkeypatch.setattr(mod, "BRIDGE_DIR", tmp_path)
        monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

        def fake_npm_fail(*args, **kwargs):
            result = MagicMock()
            result.returncode = 1
            result.stderr = "ERR! code ENETWORK"
            return result

        import subprocess as sp_mod
        monkeypatch.setattr(sp_mod, "run", fake_npm_fail)

        with pytest.raises(RuntimeError, match="npm install failed"):
            ensure_baileys_installed(quiet=True)
