"""
Built-in Skill: GitHub Repos — Clone repositories and install dependencies.

Allows agents to clone GitHub/GitLab/Bitbucket repos, detect and install
their dependencies, list managed repos, and clean up.  All repos live
under ``~/.neuralclaw/workspace/repos/``.

Security:
- HTTPS only, host allowlist, no embedded credentials
- Shallow clones (``--depth 1``) by default
- Dependencies installed in isolated venvs / node_modules
- All subprocess work runs through the Sandbox with timeout enforcement
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.cortex.action.sandbox import Sandbox
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPOS_DIR = Path.home() / ".neuralclaw" / "workspace" / "repos"

ALLOWED_GIT_HOSTS: set[str] = {"github.com", "gitlab.com", "bitbucket.org"}

# Map dependency files to install metadata
DEPENDENCY_HANDLERS: dict[str, dict[str, Any]] = {
    "requirements.txt": {"type": "python", "label": "pip (requirements.txt)"},
    "setup.py":         {"type": "python", "label": "pip (setup.py)"},
    "pyproject.toml":   {"type": "python", "label": "pip (pyproject.toml)"},
    "package.json":     {"type": "node",   "label": "npm (package.json)"},
    "Cargo.toml":       {"type": "rust",   "label": "cargo (Cargo.toml)"},
    "go.mod":           {"type": "go",     "label": "go (go.mod)"},
}

# Module-level workspace config — set by gateway on init
_max_clone_timeout: int = 120
_max_install_timeout: int = 300
_max_repo_size_mb: int = 500
_allowed_git_hosts: set[str] = set(ALLOWED_GIT_HOSTS)


def set_workspace_config(config: Any) -> None:
    """Configure workspace settings from ``WorkspaceConfig``."""
    global REPOS_DIR, _max_clone_timeout, _max_install_timeout, _max_repo_size_mb, _allowed_git_hosts
    if hasattr(config, "repos_dir") and config.repos_dir:
        REPOS_DIR = Path(str(config.repos_dir)).expanduser()
    if hasattr(config, "max_clone_timeout_seconds"):
        _max_clone_timeout = config.max_clone_timeout_seconds
    if hasattr(config, "max_install_timeout_seconds"):
        _max_install_timeout = config.max_install_timeout_seconds
    if hasattr(config, "max_repo_size_mb"):
        _max_repo_size_mb = config.max_repo_size_mb
    if hasattr(config, "allowed_git_hosts"):
        _allowed_git_hosts = set(config.allowed_git_hosts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_git_url(url: str) -> tuple[bool, str]:
    """Validate a git clone URL.  Returns ``(allowed, reason)``."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False, f"Only HTTPS git URLs allowed, got: {parsed.scheme or 'none'}"
    hostname = (parsed.hostname or "").lower()
    if hostname not in _allowed_git_hosts:
        return False, f"Git host '{hostname}' not in allowed list: {sorted(_allowed_git_hosts)}"
    if parsed.username or parsed.password:
        return False, "Git URLs with embedded credentials are not allowed"
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(path_parts) < 2:
        return False, "Invalid repo path: expected /owner/repo"
    return True, ""


def _safe_repo_name(url: str) -> str:
    """Derive a filesystem-safe directory name from a git URL."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    # owner/repo → owner_repo
    name = re.sub(r"[^a-zA-Z0-9_\-]", "_", path)
    return name


def _detect_deps(repo_dir: Path) -> list[dict[str, str]]:
    """Detect dependency files in a repo directory."""
    found: list[dict[str, str]] = []
    for filename, meta in DEPENDENCY_HANDLERS.items():
        if (repo_dir / filename).exists():
            found.append({"file": filename, "type": meta["type"], "label": meta["label"]})
    return found


def _repo_size_mb(repo_dir: Path) -> float:
    """Compute a repository's on-disk size."""
    size_bytes = sum(f.stat().st_size for f in repo_dir.rglob("*") if f.is_file())
    return round(size_bytes / (1024 * 1024), 1)


def _preferred_python_extras(repo_dir: Path) -> list[str]:
    """Detect common dev/test extras from ``pyproject.toml``."""
    pyproject = repo_dir / "pyproject.toml"
    if tomllib is None or not pyproject.exists():
        return []
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        return []

    optional = (
        data.get("project", {}).get("optional-dependencies", {})
        if isinstance(data, dict)
        else {}
    )
    if not isinstance(optional, dict):
        return []

    preferred: list[str] = []
    for name in ("test", "tests", "testing", "dev"):
        if name in optional and name not in preferred:
            preferred.append(name)
    return preferred


def _build_python_install_command(repo_dir: Path, pip_bin: str, dep_file: str) -> list[str]:
    """Build the best-effort Python install command for a repo."""
    if dep_file == "requirements.txt":
        return [pip_bin, "install", "-r", "requirements.txt", "--no-input"]

    extras = _preferred_python_extras(repo_dir) if dep_file == "pyproject.toml" else []
    editable_target = "."
    if extras:
        editable_target = f".[{','.join(extras)}]"
    return [pip_bin, "install", "-e", editable_target, "--no-input"]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def clone_repo(url: str, branch: str | None = None, **_kwargs: Any) -> dict[str, Any]:
    """Clone a GitHub / GitLab / Bitbucket repository."""
    allowed, reason = _validate_git_url(url)
    if not allowed:
        return {"error": reason}

    repo_name = _safe_repo_name(url)
    target = REPOS_DIR / repo_name

    if target.exists():
        deps = _detect_deps(target)
        return {
            "success": True,
            "repo_name": repo_name,
            "repo_path": str(target),
            "already_existed": True,
            "detected_deps": deps,
        }

    REPOS_DIR.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [url, str(target)]

    git_bin = shutil.which("git")
    if not git_bin:
        return {"error": "git is not installed or not on PATH"}

    sandbox = Sandbox(
        timeout_seconds=_max_clone_timeout,
        allowed_dirs=[str(REPOS_DIR)],
    )
    result = await sandbox.execute_command(cmd, working_dir=str(REPOS_DIR))

    if not result.success:
        # Clean up partial clone
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        return {
            "error": f"git clone failed: {result.error or result.output}",
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
        }

    if _max_repo_size_mb > 0:
        size_mb = _repo_size_mb(target)
        if size_mb > _max_repo_size_mb:
            shutil.rmtree(target, ignore_errors=True)
            return {
                "error": (
                    f"Repository exceeds configured size limit: {size_mb} MB > "
                    f"{_max_repo_size_mb} MB"
                ),
                "repo_name": repo_name,
            }

    deps = _detect_deps(target)
    return {
        "success": True,
        "repo_name": repo_name,
        "repo_path": str(target),
        "already_existed": False,
        "detected_deps": deps,
        "size_mb": _repo_size_mb(target),
        "clone_time_ms": result.execution_time_ms,
    }


async def install_repo_deps(repo_name: str, **_kwargs: Any) -> dict[str, Any]:
    """Install dependencies for a cloned repository."""
    repo_dir = REPOS_DIR / repo_name
    if not repo_dir.exists():
        return {"error": f"Repository '{repo_name}' not found in {REPOS_DIR}"}
    # Verify no path traversal
    try:
        resolved = repo_dir.resolve()
        if not resolved.is_relative_to(REPOS_DIR.resolve()):
            return {"error": "Invalid repo name (path traversal blocked)"}
    except (ValueError, TypeError):
        return {"error": "Invalid repo name"}

    deps = _detect_deps(repo_dir)
    if not deps:
        return {"success": True, "repo_name": repo_name, "installed": [], "message": "No dependency files found"}

    installed: list[dict[str, Any]] = []
    errors: list[str] = []

    sandbox = Sandbox(
        timeout_seconds=_max_install_timeout,
        allowed_dirs=[str(REPOS_DIR)],
    )

    for dep in deps:
        dep_type = dep["type"]
        dep_file = dep["file"]

        if dep_type == "python":
            # Create venv if needed
            venv_dir = repo_dir / ".venv"
            if not venv_dir.exists():
                venv_result = await sandbox.execute_command(
                    [sys.executable, "-m", "venv", str(venv_dir)],
                    working_dir=str(repo_dir),
                )
                if not venv_result.success:
                    errors.append(f"venv creation failed: {venv_result.error}")
                    continue

            # Determine pip path
            if sys.platform == "win32":
                pip_bin = str(venv_dir / "Scripts" / "pip")
            else:
                pip_bin = str(venv_dir / "bin" / "pip")

            cmd = _build_python_install_command(repo_dir, pip_bin, dep_file)

            result = await sandbox.execute_command(cmd, working_dir=str(repo_dir))
            installed.append({
                "type": dep_type,
                "file": dep_file,
                "success": result.success,
                "output": (result.output or "")[:2000],
                "error": result.error,
                "time_ms": result.execution_time_ms,
            })
            if not result.success:
                errors.append(f"{dep_file}: {result.error or 'install failed'}")

        elif dep_type == "node":
            npm_bin = shutil.which("npm")
            if not npm_bin:
                errors.append("npm is not installed or not on PATH")
                continue
            lockfile = next(
                (
                    name for name in ("package-lock.json", "npm-shrinkwrap.json")
                    if (repo_dir / name).exists()
                ),
                "",
            )
            cmd = [npm_bin, "ci" if lockfile else "install", "--no-audit", "--no-fund"]
            result = await sandbox.execute_command(cmd, working_dir=str(repo_dir))
            installed.append({
                "type": dep_type,
                "file": dep_file,
                "success": result.success,
                "output": (result.output or "")[:2000],
                "error": result.error,
                "time_ms": result.execution_time_ms,
            })
            if not result.success:
                errors.append(f"{dep_file}: {result.error or 'npm install failed'}")

        elif dep_type == "rust":
            cargo_bin = shutil.which("cargo")
            if not cargo_bin:
                errors.append("cargo (Rust) is not installed or not on PATH")
                continue
            result = await sandbox.execute_command(
                [cargo_bin, "build", "--release"],
                working_dir=str(repo_dir),
            )
            installed.append({
                "type": dep_type,
                "file": dep_file,
                "success": result.success,
                "output": (result.output or "")[:2000],
                "error": result.error,
                "time_ms": result.execution_time_ms,
            })

        elif dep_type == "go":
            go_bin = shutil.which("go")
            if not go_bin:
                errors.append("go is not installed or not on PATH")
                continue
            result = await sandbox.execute_command(
                [go_bin, "build", "./..."],
                working_dir=str(repo_dir),
            )
            installed.append({
                "type": dep_type,
                "file": dep_file,
                "success": result.success,
                "output": (result.output or "")[:2000],
                "error": result.error,
                "time_ms": result.execution_time_ms,
            })

    return {
        "success": len(errors) == 0,
        "repo_name": repo_name,
        "installed": installed,
        "errors": errors,
    }


async def list_repos() -> dict[str, Any]:
    """List all cloned repositories."""
    if not REPOS_DIR.exists():
        return {"repos": []}

    repos: list[dict[str, Any]] = []
    for item in sorted(REPOS_DIR.iterdir()):
        if item.is_dir() and not item.name.startswith("."):
            deps = _detect_deps(item)
            # Check if deps are installed
            venv_exists = (item / ".venv").exists()
            node_modules_exists = (item / "node_modules").exists()
            deps_installed = venv_exists or node_modules_exists

            # Calculate size
            try:
                size_bytes = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                size_mb = round(size_bytes / (1024 * 1024), 1)
            except Exception:
                size_mb = 0.0

            repos.append({
                "name": item.name,
                "path": str(item),
                "detected_deps": deps,
                "deps_installed": deps_installed,
                "size_mb": size_mb,
            })

    return {"repos": repos}


async def remove_repo(repo_name: str, **_kwargs: Any) -> dict[str, Any]:
    """Remove a cloned repository."""
    repo_dir = REPOS_DIR / repo_name
    # Validate no path traversal
    try:
        resolved = repo_dir.resolve()
        if not resolved.is_relative_to(REPOS_DIR.resolve()):
            return {"error": "Invalid repo name (path traversal blocked)"}
    except (ValueError, TypeError):
        return {"error": "Invalid repo name"}

    if not repo_dir.exists():
        return {"error": f"Repository '{repo_name}' not found"}

    try:
        shutil.rmtree(repo_dir)
        return {"success": True, "removed": repo_name}
    except Exception as e:
        return {"error": f"Failed to remove repository: {e}"}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="github_repos",
        description="Clone GitHub repositories and install their dependencies",
        capabilities=[
            Capability.GITHUB_CLONE,
            Capability.NETWORK_HTTP,
            Capability.FILESYSTEM_WRITE,
            Capability.SHELL_EXECUTE,
        ],
        tools=[
            ToolDefinition(
                name="clone_repo",
                description=(
                    "Clone a GitHub/GitLab/Bitbucket repository. "
                    "Uses shallow clone (--depth 1) for speed. "
                    "Repos are stored in ~/.neuralclaw/workspace/repos/."
                ),
                parameters=[
                    ToolParameter(
                        name="url", type="string",
                        description="HTTPS URL of the git repository (e.g. https://github.com/owner/repo)",
                    ),
                    ToolParameter(
                        name="branch", type="string",
                        description="Branch to clone (default: repo default branch)",
                        required=False,
                    ),
                ],
                handler=clone_repo,
            ),
            ToolDefinition(
                name="install_repo_deps",
                description=(
                    "Install dependencies for a cloned repository. "
                    "Automatically detects requirements.txt, package.json, "
                    "Cargo.toml, go.mod and installs in isolated environments."
                ),
                parameters=[
                    ToolParameter(
                        name="repo_name", type="string",
                        description="Name of the cloned repository (from clone_repo or list_repos)",
                    ),
                ],
                handler=install_repo_deps,
            ),
            ToolDefinition(
                name="list_repos",
                description="List all cloned repositories with their dependency status",
                parameters=[],
                handler=list_repos,
            ),
            ToolDefinition(
                name="remove_repo",
                description="Remove a cloned repository and all its files",
                parameters=[
                    ToolParameter(
                        name="repo_name", type="string",
                        description="Name of the repository to remove",
                    ),
                ],
                handler=remove_repo,
            ),
        ],
    )
