"""Tests for the app_builder builtin skill."""

from __future__ import annotations

import json

import pytest

from neuralclaw.skills.builtins import app_builder


class TestBuildApp:
    @pytest.mark.asyncio
    async def test_build_app_creates_project_under_apps_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_builder, "APPS_DIR", tmp_path / "apps")

        result = await app_builder.build_app(
            project_name="Demo Portal",
            template="web",
            description="Internal dashboard",
        )

        project_dir = tmp_path / "apps" / "demo-portal"
        assert result["success"] is True
        assert result["project_path"] == str(project_dir)
        assert project_dir.exists()
        assert (project_dir / "index.html").exists()
        assert (project_dir / "styles.css").exists()
        assert (project_dir / "app.js").exists()

        metadata = json.loads((project_dir / ".neuralclaw-app.json").read_text(encoding="utf-8"))
        assert metadata["template"] == "web"
        assert metadata["workspace_root"] == str((tmp_path / "apps").resolve())

    @pytest.mark.asyncio
    async def test_build_app_returns_existing_workspace_without_rewriting_scaffold(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_builder, "APPS_DIR", tmp_path / "apps")

        first = await app_builder.build_app("Billing Console", template="python")
        project_dir = tmp_path / "apps" / "billing-console"
        original = (project_dir / "README.md").read_text(encoding="utf-8")

        second = await app_builder.build_app("Billing Console", template="node")

        assert first["already_existed"] is False
        assert second["already_existed"] is True
        assert (project_dir / "README.md").read_text(encoding="utf-8") == original
        assert not (project_dir / "package.json").exists()

    @pytest.mark.asyncio
    async def test_build_app_rejects_invalid_template(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app_builder, "APPS_DIR", tmp_path / "apps")

        result = await app_builder.build_app("Demo", template="rails")

        assert "error" in result
        assert "Unsupported template" in result["error"]

    def test_workspace_config_overrides_apps_dir(self, tmp_path):
        original = app_builder.APPS_DIR
        try:
            config = type("Workspace", (), {"apps_dir": str(tmp_path / "custom-apps")})()
            app_builder.set_workspace_config(config)
            assert app_builder.APPS_DIR == (tmp_path / "custom-apps")
        finally:
            app_builder.APPS_DIR = original
