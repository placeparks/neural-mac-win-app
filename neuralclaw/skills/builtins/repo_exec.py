"""
Built-in Skill: Repo Execution — Run scripts and commands from cloned repos.

Executes code from cloned repositories through the Sandbox with proper
dependency resolution (Python venvs, Node.js node_modules, etc.).

Security:
- All execution goes through ``Sandbox.execute_command()`` with timeout
- Command allowlist blocks dangerous executables (rm, sudo, curl, etc.)
- Working directory constrained to ``~/.neuralclaw/workspace/repos/``
- Output capped at 10 000 characters
"""

from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.cortex.action.sandbox import Sandbox
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPOS_DIR = Path.home() / ".neuralclaw" / "workspace" / "repos"

# Desktop sidecar: running as frozen binary means the user owns the machine.
_IS_DESKTOP = getattr(sys, "frozen", False)

# Commands that are allowed as the first token in run_repo_command
ALLOWED_COMMANDS: set[str] = {
    "python", "python3", "node", "npm", "npx",
    "cargo", "go", "bash", "sh",
    "pip", "pip3", "pytest", "make",
    "maturin", "poetry", "rustup", "uv",
}

# Substrings that immediately block a command
BLOCKED_PATTERNS: list[str] = [
    "rm -rf", "rm -r", "sudo ", "chmod ", "chown ",
    "curl ", "wget ", "nc ", "ncat ", "netcat ",
    "ssh ", "scp ", "rsync ",
    "dd ", "mkfs", "fdisk",
    "> /dev/", "| sh", "| bash",
]

# Max output length returned to the LLM
OUTPUT_CAP = 10_000

# Module-level timeout cap
_max_exec_timeout: int = 300


def set_workspace_config(config: Any) -> None:
    """Configure workspace settings from ``WorkspaceConfig``."""
    global REPOS_DIR, _max_exec_timeout
    if hasattr(config, "repos_dir") and config.repos_dir:
        REPOS_DIR = Path(str(config.repos_dir)).expanduser()
    if hasattr(config, "max_exec_timeout_seconds"):
        _max_exec_timeout = config.max_exec_timeout_seconds


def set_max_exec_timeout(seconds: int) -> None:
    """Set the maximum execution timeout (from workspace config)."""
    global _max_exec_timeout
    _max_exec_timeout = seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_repo(repo_name: str) -> tuple[Path | None, dict[str, Any] | None]:
    """Resolve and validate a repo directory.  Returns ``(path, error)``."""
    repo_dir = REPOS_DIR / repo_name
    try:
        resolved = repo_dir.resolve()
        if not resolved.is_relative_to(REPOS_DIR.resolve()):
            return None, {"error": "Invalid repo name (path traversal blocked)"}
    except (ValueError, TypeError):
        return None, {"error": "Invalid repo name"}
    if not resolved.exists():
        return None, {"error": f"Repository '{repo_name}' not found in {REPOS_DIR}"}
    return resolved, None


def _build_repo_env(repo_dir: Path, env_type: str) -> dict[str, str]:
    """Build extra environment variables for a repo's runtime."""
    extra: dict[str, str] = {}

    if env_type == "python":
        venv_dir = repo_dir / ".venv"
        if venv_dir.exists():
            if sys.platform == "win32":
                bin_dir = str(venv_dir / "Scripts")
            else:
                bin_dir = str(venv_dir / "bin")
            import os
            existing_path = os.environ.get("PATH", "")
            extra["PATH"] = f"{bin_dir}{os.pathsep}{existing_path}"
            extra["VIRTUAL_ENV"] = str(venv_dir)

    elif env_type == "node":
        node_modules = repo_dir / "node_modules"
        if node_modules.exists():
            extra["NODE_PATH"] = str(node_modules)

    return extra


def _resolve_python_command(repo_dir: Path, tokens: list[str]) -> list[str]:
    """Bind python-family commands to the repo venv when one exists."""
    if not tokens:
        return tokens

    exe = Path(tokens[0]).name.lower().replace(".exe", "")
    if exe not in {"python", "python3", "pip", "pip3", "pytest"}:
        return tokens

    venv_dir = repo_dir / ".venv"
    if not venv_dir.exists():
        return tokens

    if sys.platform == "win32":
        bin_dir = venv_dir / "Scripts"
        python_bin = bin_dir / "python.exe"
        pip_bin = bin_dir / "pip.exe"
        pytest_bin = bin_dir / "pytest.exe"
    else:
        bin_dir = venv_dir / "bin"
        python_bin = bin_dir / "python"
        pip_bin = bin_dir / "pip"
        pytest_bin = bin_dir / "pytest"

    if exe in {"python", "python3"} and python_bin.exists():
        return [str(python_bin), *tokens[1:]]
    if exe in {"pip", "pip3"} and pip_bin.exists():
        return [str(pip_bin), *tokens[1:]]
    if exe == "pytest":
        if pytest_bin.exists():
            return [str(pytest_bin), *tokens[1:]]
        if python_bin.exists():
            return [str(python_bin), "-m", "pytest", *tokens[1:]]
    return tokens


def _detect_env_type(script_path: str) -> str:
    """Detect runtime type from file extension."""
    ext = Path(script_path).suffix.lower()
    if ext in (".py", ".pyw"):
        return "python"
    if ext in (".js", ".mjs", ".cjs"):
        return "node"
    if ext in (".ts", ".tsx"):
        return "typescript"
    if ext == ".sh":
        return "shell"
    if ext == ".rs":
        return "rust"
    if ext == ".go":
        return "go"
    return "generic"


def _build_script_command(
    repo_dir: Path,
    script_path: str,
    args: str,
    env_type: str,
) -> list[str]:
    """Build the command list to execute a script."""
    full_path = str(repo_dir / script_path)

    if env_type == "python":
        venv_dir = repo_dir / ".venv"
        if venv_dir.exists():
            if sys.platform == "win32":
                python_bin = str(venv_dir / "Scripts" / "python")
            else:
                python_bin = str(venv_dir / "bin" / "python")
        else:
            python_bin = sys.executable
        cmd = [python_bin, full_path]

    elif env_type == "node":
        cmd = ["node", full_path]

    elif env_type == "typescript":
        npx_bin = shutil.which("npx")
        if npx_bin:
            cmd = [npx_bin, "tsx", full_path]
        else:
            cmd = ["node", full_path]

    elif env_type == "shell":
        bash_bin = shutil.which("bash") or "bash"
        cmd = [bash_bin, full_path]

    else:
        # Try to run directly
        cmd = [full_path]

    if args:
        cmd.extend(shlex.split(args))

    return cmd


def _validate_command(raw_command: str) -> tuple[list[str] | None, str]:
    """Validate and split a raw command string.  Returns ``(tokens, error)``."""
    # Check for blocked patterns first
    lower = raw_command.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in lower:
            return None, f"Blocked dangerous command pattern: '{pattern}'"

    try:
        tokens = shlex.split(raw_command)
    except ValueError as e:
        return None, f"Invalid command syntax: {e}"

    if not tokens:
        return None, "Empty command"

    # Validate the first token (the executable)
    exe = Path(tokens[0]).name.lower()  # strip path, e.g. /usr/bin/python → python
    # Remove .exe suffix on Windows
    if exe.endswith(".exe"):
        exe = exe[:-4]

    if exe not in ALLOWED_COMMANDS:
        return None, (
            f"Command '{exe}' not in allowed list. "
            f"Allowed: {sorted(ALLOWED_COMMANDS)}"
        )

    return tokens, ""


def _sandbox_allowed_dirs() -> list[str]:
    """Return sandbox allowed directories, expanded for desktop mode."""
    dirs = [str(REPOS_DIR)]
    if _IS_DESKTOP:
        home = str(Path.home())
        dirs.extend([
            home,
            str(Path.home() / "Desktop"),
            str(Path.home() / "Documents"),
            str(Path.home() / "Downloads"),
            str(Path.home() / "Projects"),
            str(Path.home() / ".neuralclaw"),
        ])
    return dirs


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def run_repo_script(
    repo_name: str,
    script_path: str,
    args: str = "",
    timeout_seconds: int = 60,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run a script from a cloned repository."""
    repo_dir, err = _resolve_repo(repo_name)
    if err:
        return err

    # Validate script exists
    script_file = repo_dir / script_path
    try:
        resolved_script = script_file.resolve()
        if not resolved_script.is_relative_to(repo_dir.resolve()):
            return {"error": "Script path traversal blocked"}
    except (ValueError, TypeError):
        return {"error": "Invalid script path"}

    if not resolved_script.exists():
        return {"error": f"Script not found: {script_path}"}
    if not resolved_script.is_file():
        return {"error": f"Not a file: {script_path}"}

    env_type = _detect_env_type(script_path)
    extra_env = _build_repo_env(repo_dir, env_type)
    cmd = _build_script_command(repo_dir, script_path, args, env_type)

    timeout = min(max(timeout_seconds, 5), _max_exec_timeout)
    sandbox = Sandbox(
        timeout_seconds=timeout,
        allowed_dirs=_sandbox_allowed_dirs(),
        allowed_executables=sorted(ALLOWED_COMMANDS),
    )

    result = await sandbox.execute_command(
        cmd,
        working_dir=str(repo_dir),
        extra_env=extra_env,
    )

    return {
        "success": result.success,
        "output": (result.output or "")[:OUTPUT_CAP],
        "error": result.error,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "execution_time_ms": result.execution_time_ms,
    }


async def run_repo_command(
    repo_name: str,
    command: str,
    subdir: str = "",
    timeout_seconds: int = 60,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run a command within a repo's environment."""
    repo_dir, err = _resolve_repo(repo_name)
    if err:
        return err

    tokens, validate_err = _validate_command(command)
    if validate_err:
        return {"error": validate_err}

    # Resolve working directory (repo root or subdirectory)
    working_dir = repo_dir
    if subdir:
        working_dir = repo_dir / subdir
        try:
            resolved_wd = working_dir.resolve()
            if not resolved_wd.is_relative_to(repo_dir.resolve()):
                return {"error": "Subdirectory path traversal blocked"}
        except (ValueError, TypeError):
            return {"error": "Invalid subdirectory path"}
        if not resolved_wd.exists():
            return {"error": f"Subdirectory not found: {subdir}"}
        if not resolved_wd.is_dir():
            return {"error": f"Not a directory: {subdir}"}

    # Detect env type from the first token
    exe = Path(tokens[0]).name.lower().replace(".exe", "")
    if exe in ("python", "python3", "pip", "pip3", "pytest"):
        env_type = "python"
    elif exe in ("node", "npm", "npx"):
        env_type = "node"
    else:
        env_type = "generic"

    extra_env = _build_repo_env(repo_dir, env_type)
    if env_type == "python":
        tokens = _resolve_python_command(repo_dir, tokens)

    timeout = min(max(timeout_seconds, 5), _max_exec_timeout)
    sandbox = Sandbox(
        timeout_seconds=timeout,
        allowed_dirs=_sandbox_allowed_dirs(),
        allowed_executables=sorted(ALLOWED_COMMANDS),
    )

    result = await sandbox.execute_command(
        tokens,
        working_dir=str(working_dir),
        extra_env=extra_env,
    )

    return {
        "success": result.success,
        "output": (result.output or "")[:OUTPUT_CAP],
        "error": result.error,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "execution_time_ms": result.execution_time_ms,
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="repo_exec",
        description="Execute scripts and commands from cloned repositories",
        capabilities=[Capability.SHELL_EXECUTE, Capability.FILESYSTEM_READ],
        tools=[
            ToolDefinition(
                name="run_repo_script",
                description=(
                    "Run a script from a cloned repository. "
                    "Automatically detects the runtime (Python, Node.js, Bash) "
                    "and uses the repo's installed dependencies (venv, node_modules)."
                ),
                parameters=[
                    ToolParameter(
                        name="repo_name", type="string",
                        description="Name of the cloned repository",
                    ),
                    ToolParameter(
                        name="script_path", type="string",
                        description="Relative path to the script within the repo (e.g. main.py, src/index.js)",
                    ),
                    ToolParameter(
                        name="args", type="string",
                        description="Command-line arguments to pass to the script",
                        required=False,
                    ),
                    ToolParameter(
                        name="timeout_seconds", type="integer",
                        description="Maximum execution time in seconds (default 60, max 300)",
                        required=False, default=60,
                    ),
                ],
                handler=run_repo_script,
            ),
            ToolDefinition(
                name="run_repo_command",
                description=(
                    "Run an arbitrary command within a repo's environment. "
                    "Use 'subdir' to run from a subdirectory instead of cd. "
                    "Allowed commands: python, node, npm, npx, cargo, go, bash, "
                    "pip, pytest, make, maturin, poetry, uv. Dangerous commands are blocked."
                ),
                parameters=[
                    ToolParameter(
                        name="repo_name", type="string",
                        description="Name of the cloned repository",
                    ),
                    ToolParameter(
                        name="command", type="string",
                        description="Command to run (e.g. 'python -m pytest', 'npm test', 'maturin develop')",
                    ),
                    ToolParameter(
                        name="subdir", type="string",
                        description="Subdirectory within the repo to run the command from (e.g. 'bindings/python'). Defaults to repo root.",
                        required=False,
                    ),
                    ToolParameter(
                        name="timeout_seconds", type="integer",
                        description="Maximum execution time in seconds (default 60, max 300)",
                        required=False, default=60,
                    ),
                ],
                handler=run_repo_command,
            ),
        ],
    )
