"""Tests for the repo_exec builtin skill."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from neuralclaw.skills.builtins.repo_exec import (
    ALLOWED_COMMANDS,
    BLOCKED_PATTERNS,
    REPOS_DIR,
    _build_repo_env,
    _build_script_command,
    _detect_env_type,
    _resolve_python_command,
    _validate_command,
    run_repo_command,
    run_repo_script,
    set_workspace_config,
)


# ---------------------------------------------------------------------------
# Environment type detection
# ---------------------------------------------------------------------------


class TestDetectEnvType:
    def test_python(self):
        assert _detect_env_type("main.py") == "python"
        assert _detect_env_type("src/app.pyw") == "python"

    def test_node(self):
        assert _detect_env_type("index.js") == "node"
        assert _detect_env_type("server.mjs") == "node"
        assert _detect_env_type("lib.cjs") == "node"

    def test_typescript(self):
        assert _detect_env_type("app.ts") == "typescript"

    def test_shell(self):
        assert _detect_env_type("run.sh") == "shell"

    def test_generic(self):
        assert _detect_env_type("README.md") == "generic"


# ---------------------------------------------------------------------------
# Command validation
# ---------------------------------------------------------------------------


class TestValidateCommand:
    def test_python_allowed(self):
        tokens, err = _validate_command("python -m pytest")
        assert err == ""
        assert tokens == ["python", "-m", "pytest"]

    def test_node_allowed(self):
        tokens, err = _validate_command("node index.js")
        assert err == ""
        assert tokens[0] == "node"

    def test_npm_allowed(self):
        tokens, err = _validate_command("npm test")
        assert err == ""

    def test_make_allowed(self):
        tokens, err = _validate_command("make build")
        assert err == ""

    def test_rm_blocked(self):
        _, err = _validate_command("rm -rf /")
        assert err != ""
        assert "Blocked" in err or "not in allowed" in err

    def test_sudo_blocked(self):
        _, err = _validate_command("sudo apt install foo")
        assert err != ""

    def test_curl_blocked(self):
        _, err = _validate_command("curl http://evil.com")
        assert err != ""

    def test_wget_blocked(self):
        _, err = _validate_command("wget http://evil.com")
        assert err != ""

    def test_nc_blocked(self):
        _, err = _validate_command("nc -l 4444")
        assert err != ""

    def test_ssh_blocked(self):
        _, err = _validate_command("ssh user@host")
        assert err != ""

    def test_unknown_command_blocked(self):
        _, err = _validate_command("evil_binary --flag")
        assert "not in allowed list" in err

    def test_empty_command(self):
        _, err = _validate_command("")
        assert err != ""

    def test_pipe_to_sh_blocked(self):
        _, err = _validate_command("python script.py | sh")
        assert err != ""


# ---------------------------------------------------------------------------
# Repo environment building
# ---------------------------------------------------------------------------


class TestBuildRepoEnv:
    def test_python_with_venv(self, tmp_path):
        venv_dir = tmp_path / ".venv"
        if sys.platform == "win32":
            (venv_dir / "Scripts").mkdir(parents=True)
        else:
            (venv_dir / "bin").mkdir(parents=True)

        env = _build_repo_env(tmp_path, "python")
        assert "VIRTUAL_ENV" in env
        assert "PATH" in env

    def test_python_without_venv(self, tmp_path):
        env = _build_repo_env(tmp_path, "python")
        assert env == {}

    def test_node_with_modules(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        env = _build_repo_env(tmp_path, "node")
        assert "NODE_PATH" in env
        assert "node_modules" in env["NODE_PATH"]

    def test_node_without_modules(self, tmp_path):
        env = _build_repo_env(tmp_path, "node")
        assert env == {}

    def test_generic(self, tmp_path):
        env = _build_repo_env(tmp_path, "generic")
        assert env == {}

    def test_workspace_config_overrides_repo_dir(self, tmp_path):
        config = type("Workspace", (), {
            "repos_dir": str(tmp_path / "custom"),
            "max_exec_timeout_seconds": 42,
        })()
        original = REPOS_DIR
        try:
            set_workspace_config(config)
            from neuralclaw.skills.builtins import repo_exec as mod

            assert mod.REPOS_DIR == (tmp_path / "custom")
        finally:
            from neuralclaw.skills.builtins import repo_exec as mod

            mod.REPOS_DIR = original


class TestResolvePythonCommand:
    def test_rewrites_python_to_repo_venv(self, tmp_path):
        venv_dir = tmp_path / ".venv"
        if sys.platform == "win32":
            scripts = venv_dir / "Scripts"
            scripts.mkdir(parents=True)
            (scripts / "python.exe").write_text("")
        else:
            bin_dir = venv_dir / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "python").write_text("")

        cmd = _resolve_python_command(tmp_path, ["python", "-m", "pytest", "-q"])

        assert ".venv" in cmd[0]
        assert cmd[1:] == ["-m", "pytest", "-q"]

    def test_rewrites_pytest_to_python_module_when_pytest_bin_missing(self, tmp_path):
        venv_dir = tmp_path / ".venv"
        if sys.platform == "win32":
            scripts = venv_dir / "Scripts"
            scripts.mkdir(parents=True)
            (scripts / "python.exe").write_text("")
        else:
            bin_dir = venv_dir / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "python").write_text("")

        cmd = _resolve_python_command(tmp_path, ["pytest", "-q"])

        assert ".venv" in cmd[0]
        assert cmd[1:] == ["-m", "pytest", "-q"]


# ---------------------------------------------------------------------------
# Script command building
# ---------------------------------------------------------------------------


class TestBuildScriptCommand:
    def test_python_with_venv(self, tmp_path):
        venv_dir = tmp_path / ".venv"
        if sys.platform == "win32":
            (venv_dir / "Scripts").mkdir(parents=True)
        else:
            (venv_dir / "bin").mkdir(parents=True)

        cmd = _build_script_command(tmp_path, "main.py", "", "python")
        assert "python" in cmd[0].lower() or "venv" in cmd[0].lower()
        assert cmd[-1].endswith("main.py")

    def test_node_script(self, tmp_path):
        cmd = _build_script_command(tmp_path, "index.js", "", "node")
        assert cmd[0] == "node"

    def test_with_args(self, tmp_path):
        cmd = _build_script_command(tmp_path, "main.py", "--verbose --count 5", "python")
        assert "--verbose" in cmd
        assert "--count" in cmd
        assert "5" in cmd


# ---------------------------------------------------------------------------
# run_repo_script (integration-level with mocked sandbox)
# ---------------------------------------------------------------------------


class TestRunRepoScript:
    @pytest.mark.asyncio
    async def test_repo_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.repo_exec.REPOS_DIR", tmp_path)
        result = await run_repo_script("nonexistent", "main.py")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_script_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.repo_exec.REPOS_DIR", tmp_path)
        repo = tmp_path / "my_repo"
        repo.mkdir()

        result = await run_repo_script("my_repo", "nonexistent.py")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.repo_exec.REPOS_DIR", tmp_path)
        result = await run_repo_script("../../etc", "passwd")
        assert "error" in result


# ---------------------------------------------------------------------------
# run_repo_command
# ---------------------------------------------------------------------------


class TestRunRepoCommand:
    @pytest.mark.asyncio
    async def test_repo_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.repo_exec.REPOS_DIR", tmp_path)
        result = await run_repo_command("nonexistent", "python -m pytest")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_blocked_command(self, tmp_path, monkeypatch):
        monkeypatch.setattr("neuralclaw.skills.builtins.repo_exec.REPOS_DIR", tmp_path)
        repo = tmp_path / "my_repo"
        repo.mkdir()

        result = await run_repo_command("my_repo", "rm -rf /")
        assert "error" in result
