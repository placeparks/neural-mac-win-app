"""Tests for the github_repos builtin skill."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from neuralclaw.skills.builtins.github_repos import (
    REPOS_DIR,
    _build_python_install_command,
    _detect_deps,
    _preferred_python_extras,
    _safe_repo_name,
    _validate_git_url,
    clone_repo,
    install_repo_deps,
    list_repos,
    remove_repo,
    set_workspace_config,
)


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


class TestValidateGitUrl:
    def test_github_https_allowed(self):
        ok, reason = _validate_git_url("https://github.com/owner/repo")
        assert ok is True
        assert reason == ""

    def test_github_https_with_git_suffix(self):
        ok, _ = _validate_git_url("https://github.com/owner/repo.git")
        assert ok is True

    def test_gitlab_allowed(self):
        ok, _ = _validate_git_url("https://gitlab.com/group/project")
        assert ok is True

    def test_bitbucket_allowed(self):
        ok, _ = _validate_git_url("https://bitbucket.org/team/repo")
        assert ok is True

    def test_unknown_host_blocked(self):
        ok, reason = _validate_git_url("https://evil.com/owner/repo")
        assert ok is False
        assert "not in allowed list" in reason

    def test_ssh_scheme_blocked(self):
        ok, reason = _validate_git_url("ssh://git@github.com/owner/repo")
        assert ok is False
        assert "HTTPS" in reason

    def test_git_scheme_blocked(self):
        ok, reason = _validate_git_url("git://github.com/owner/repo")
        assert ok is False

    def test_file_scheme_blocked(self):
        ok, reason = _validate_git_url("file:///etc/passwd")
        assert ok is False

    def test_no_scheme_blocked(self):
        ok, reason = _validate_git_url("github.com/owner/repo")
        assert ok is False

    def test_embedded_credentials_blocked(self):
        ok, reason = _validate_git_url("https://user:pass@github.com/owner/repo")
        assert ok is False
        assert "credentials" in reason

    def test_invalid_path_blocked(self):
        ok, reason = _validate_git_url("https://github.com/")
        assert ok is False
        assert "owner/repo" in reason

    def test_single_path_segment_blocked(self):
        ok, reason = _validate_git_url("https://github.com/owner")
        assert ok is False


# ---------------------------------------------------------------------------
# Repo name sanitisation
# ---------------------------------------------------------------------------


class TestSafeRepoName:
    def test_basic(self):
        assert _safe_repo_name("https://github.com/owner/repo") == "owner_repo"

    def test_git_suffix_stripped(self):
        assert _safe_repo_name("https://github.com/owner/repo.git") == "owner_repo"

    def test_special_chars(self):
        name = _safe_repo_name("https://github.com/my-org/cool.project")
        assert "/" not in name
        assert "." not in name


# ---------------------------------------------------------------------------
# Dependency detection
# ---------------------------------------------------------------------------


class TestDetectDeps:
    def test_python_deps(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("requests\n")
        deps = _detect_deps(tmp_path)
        assert len(deps) == 1
        assert deps[0]["type"] == "python"
        assert deps[0]["file"] == "requirements.txt"

    def test_node_deps(self, tmp_path):
        (tmp_path / "package.json").write_text("{}\n")
        deps = _detect_deps(tmp_path)
        assert len(deps) == 1
        assert deps[0]["type"] == "node"

    def test_multiple_deps(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask\n")
        (tmp_path / "package.json").write_text("{}\n")
        deps = _detect_deps(tmp_path)
        types = {d["type"] for d in deps}
        assert "python" in types
        assert "node" in types

    def test_no_deps(self, tmp_path):
        deps = _detect_deps(tmp_path)
        assert deps == []

    def test_cargo_deps(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("[package]\n")
        deps = _detect_deps(tmp_path)
        assert deps[0]["type"] == "rust"

    def test_go_deps(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/foo\n")
        deps = _detect_deps(tmp_path)
        assert deps[0]["type"] == "go"


class TestPythonInstallPlanning:
    def test_detects_preferred_pyproject_extras(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            """
[project]
name = "demo"

[project.optional-dependencies]
dev = ["pytest"]
test = ["coverage"]
docs = ["mkdocs"]
""".strip()
        )

        extras = _preferred_python_extras(tmp_path)

        assert extras == ["test", "dev"]

    def test_builds_editable_install_with_test_extras(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            """
[project]
name = "demo"

[project.optional-dependencies]
test = ["pytest"]
""".strip()
        )

        cmd = _build_python_install_command(tmp_path, "pip", "pyproject.toml")

        assert cmd == ["pip", "install", "-e", ".[test]", "--no-input"]


# ---------------------------------------------------------------------------
# clone_repo (mocked)
# ---------------------------------------------------------------------------


class TestCloneRepo:
    @pytest.mark.asyncio
    async def test_rejects_invalid_url(self):
        result = await clone_repo("git://evil.com/foo/bar")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_private_host(self):
        result = await clone_repo("https://internal.corp/foo/bar")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_returns_existing_if_already_cloned(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.github_repos.REPOS_DIR", tmp_path)
        repo_dir = tmp_path / "owner_repo"
        repo_dir.mkdir()
        (repo_dir / "requirements.txt").write_text("flask\n")

        result = await clone_repo("https://github.com/owner/repo")
        assert result["success"] is True
        assert result["already_existed"] is True
        assert len(result["detected_deps"]) == 1

    def test_workspace_config_overrides_repo_dir(self, tmp_path):
        config = type("Workspace", (), {
            "repos_dir": str(tmp_path / "custom"),
            "max_repo_size_mb": 50,
            "max_clone_timeout_seconds": 99,
            "max_install_timeout_seconds": 123,
            "allowed_git_hosts": ["github.com"],
        })()
        original = REPOS_DIR
        try:
            set_workspace_config(config)
            from neuralclaw.skills.builtins import github_repos as mod

            assert mod.REPOS_DIR == (tmp_path / "custom")
        finally:
            from neuralclaw.skills.builtins import github_repos as mod

            mod.REPOS_DIR = original


# ---------------------------------------------------------------------------
# list_repos
# ---------------------------------------------------------------------------


class TestListRepos:
    @pytest.mark.asyncio
    async def test_empty_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.github_repos.REPOS_DIR", tmp_path)
        result = await list_repos()
        assert result["repos"] == []

    @pytest.mark.asyncio
    async def test_with_entries(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.github_repos.REPOS_DIR", tmp_path)
        (tmp_path / "my_repo").mkdir()
        (tmp_path / "my_repo" / "requirements.txt").write_text("flask\n")

        result = await list_repos()
        assert len(result["repos"]) == 1
        assert result["repos"][0]["name"] == "my_repo"

    @pytest.mark.asyncio
    async def test_nonexistent_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.github_repos.REPOS_DIR", tmp_path / "nope")
        result = await list_repos()
        assert result["repos"] == []


# ---------------------------------------------------------------------------
# remove_repo
# ---------------------------------------------------------------------------


class TestRemoveRepo:
    @pytest.mark.asyncio
    async def test_removes_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.github_repos.REPOS_DIR", tmp_path)
        repo = tmp_path / "my_repo"
        repo.mkdir()
        (repo / "file.txt").write_text("data")

        result = await remove_repo("my_repo")
        assert result["success"] is True
        assert not repo.exists()

    @pytest.mark.asyncio
    async def test_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.github_repos.REPOS_DIR", tmp_path)
        result = await remove_repo("nonexistent")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.github_repos.REPOS_DIR", tmp_path)
        result = await remove_repo("../../etc")
        assert "error" in result
        assert "traversal" in result["error"].lower()


class TestInstallRepoDeps:
    @pytest.mark.asyncio
    async def test_node_install_uses_ci_when_lockfile_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.github_repos.REPOS_DIR", tmp_path)
        repo = tmp_path / "my_repo"
        repo.mkdir()
        (repo / "package.json").write_text("{}")
        (repo / "package-lock.json").write_text("{}")
        monkeypatch.setattr(shutil, "which", lambda name: "npm" if name == "npm" else None)

        commands = []

        class FakeSandbox:
            def __init__(self, *args, **kwargs):
                pass

            async def execute_command(self, cmd, working_dir=None):
                commands.append(cmd)
                return type("Result", (), {
                    "success": True,
                    "output": "",
                    "error": None,
                    "execution_time_ms": 1.0,
                })()

        monkeypatch.setattr("neuralclaw.skills.builtins.github_repos.Sandbox", FakeSandbox)

        result = await install_repo_deps("my_repo")

        assert result["success"] is True
        assert commands[0][:2] == ["npm", "ci"]

    @pytest.mark.asyncio
    async def test_node_install_includes_dev_dependencies(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.github_repos.REPOS_DIR", tmp_path)
        repo = tmp_path / "my_repo"
        repo.mkdir()
        (repo / "package.json").write_text("{}")
        monkeypatch.setattr(shutil, "which", lambda name: "npm" if name == "npm" else None)

        commands = []

        class FakeSandbox:
            def __init__(self, *args, **kwargs):
                pass

            async def execute_command(self, cmd, working_dir=None):
                commands.append(cmd)
                return type("Result", (), {
                    "success": True,
                    "output": "",
                    "error": None,
                    "execution_time_ms": 1.0,
                })()

        monkeypatch.setattr("neuralclaw.skills.builtins.github_repos.Sandbox", FakeSandbox)

        result = await install_repo_deps("my_repo")

        assert result["success"] is True
        assert commands[0][0:2] == ["npm", "install"]
        assert "--production" not in commands[0]
