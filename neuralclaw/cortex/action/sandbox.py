"""
Sandbox — Isolated execution environment for skills.

Runs skill code in subprocess with timeout enforcement, output capture,
and resource limits. This is the enforcement layer for NeuralClaw's
capability-based security model.

Security features:
- Directory allowlist with symlink resolution
- Timeout enforcement
- Clean environment (no secret leakage)
- Controlled working directory
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Sandbox errors
# ---------------------------------------------------------------------------

class SandboxPathDenied(PermissionError):
    """Raised when a path is outside the sandbox allowlist."""
    pass


# ---------------------------------------------------------------------------
# Sandbox result
# ---------------------------------------------------------------------------

@dataclass
class SandboxResult:
    """Result from sandboxed execution."""
    success: bool
    output: str
    error: str | None = None
    exit_code: int = 0
    timed_out: bool = False
    execution_time_ms: float = 0.0


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

def resolve_and_validate_path(
    path: str | Path,
    allowed_dirs: list[Path],
) -> Path:
    """
    Resolve a path and validate it is within an allowed directory.

    Resolves symlinks to prevent escape via symbolic links.
    Raises SandboxPathDenied if the path is outside all allowed dirs.
    """
    resolved = Path(path).resolve()

    if not allowed_dirs:
        raise SandboxPathDenied(
            f"SANDBOX_PATH_DENIED: No allowed directories configured. "
            f"Cannot access: {resolved}"
        )

    for allowed in allowed_dirs:
        allowed_resolved = allowed.resolve()
        try:
            if resolved.is_relative_to(allowed_resolved):
                return resolved
        except (ValueError, TypeError):
            continue

    raise SandboxPathDenied(
        f"SANDBOX_PATH_DENIED: Path '{resolved}' is outside allowed directories: "
        f"{[str(d) for d in allowed_dirs]}"
    )


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------

class Sandbox:
    """
    Subprocess-based isolated execution environment.

    Runs Python code in a clean subprocess with:
    - Directory allowlist enforcement (symlink-safe)
    - Timeout enforcement
    - stdout/stderr capture
    - Limited environment variables
    - Controlled working directory
    """

    def __init__(
        self,
        timeout_seconds: int = 30,
        allowed_dirs: list[str] | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._allowed_dirs = [Path(d) for d in (allowed_dirs or [])]
        # Create a dedicated temp dir under an allowed root if possible,
        # otherwise use system temp (which we add to allowed dirs)
        self._sandbox_temp = self._setup_sandbox_temp()

    def _setup_sandbox_temp(self) -> Path:
        """Create and register a dedicated sandbox temp directory."""
        sandbox_tmp = Path(tempfile.gettempdir()) / "neuralclaw_sandbox"
        sandbox_tmp.mkdir(parents=True, exist_ok=True)
        # Always allow the sandbox temp dir
        resolved_tmp = sandbox_tmp.resolve()
        if resolved_tmp not in [d.resolve() for d in self._allowed_dirs]:
            self._allowed_dirs.append(resolved_tmp)
        return resolved_tmp

    def _validate_working_dir(self, working_dir: str | None) -> str:
        """Validate and return a safe working directory."""
        if working_dir is None:
            return str(self._sandbox_temp)

        try:
            validated = resolve_and_validate_path(working_dir, self._allowed_dirs)
            return str(validated)
        except SandboxPathDenied:
            raise

    async def execute_python(
        self,
        code: str,
        working_dir: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Execute Python code in an isolated subprocess."""
        import time as _time

        # Validate working directory against allowlist
        try:
            cwd = self._validate_working_dir(working_dir)
        except SandboxPathDenied as e:
            return SandboxResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-2,
            )

        # Write code to a temporary file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            encoding="utf-8",
            dir=str(self._sandbox_temp),
        ) as f:
            f.write(code)
            script_path = f.name

        try:
            # Build clean environment
            clean_env = self._build_clean_env()
            if extra_env:
                clean_env.update(extra_env)

            start = _time.time()

            proc = await asyncio.create_subprocess_exec(
                sys.executable, script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=clean_env,
                cwd=cwd,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self._timeout,
                )
                elapsed = (_time.time() - start) * 1000

                return SandboxResult(
                    success=proc.returncode == 0,
                    output=stdout.decode("utf-8", errors="replace").strip(),
                    error=stderr.decode("utf-8", errors="replace").strip() or None,
                    exit_code=proc.returncode or 0,
                    execution_time_ms=round(elapsed, 1),
                )

            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                elapsed = (_time.time() - start) * 1000
                return SandboxResult(
                    success=False,
                    output="",
                    error=f"Execution timed out after {self._timeout}s",
                    exit_code=-1,
                    timed_out=True,
                    execution_time_ms=round(elapsed, 1),
                )

        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    async def execute_command(
        self,
        command: list[str],
        working_dir: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Execute a shell command in an isolated subprocess.

        Args:
            command:     Command tokens to execute.
            working_dir: Working directory (validated against allowlist).
            extra_env:   Additional environment variables to inject (e.g.
                         VIRTUAL_ENV, NODE_PATH). Merged on top of the
                         clean base environment.
        """
        import time as _time

        # Validate working directory against allowlist
        try:
            cwd = self._validate_working_dir(working_dir)
        except SandboxPathDenied as e:
            return SandboxResult(
                success=False,
                output="",
                error=str(e),
                exit_code=-2,
            )

        clean_env = self._build_clean_env()
        if extra_env:
            clean_env.update(extra_env)

        start = _time.time()

        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=clean_env,
            cwd=cwd,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout,
            )
            elapsed = (_time.time() - start) * 1000

            return SandboxResult(
                success=proc.returncode == 0,
                output=stdout.decode("utf-8", errors="replace").strip(),
                error=stderr.decode("utf-8", errors="replace").strip() or None,
                exit_code=proc.returncode or 0,
                execution_time_ms=round(elapsed, 1),
            )

        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            elapsed = (_time.time() - start) * 1000
            return SandboxResult(
                success=False,
                output="",
                error=f"Execution timed out after {self._timeout}s",
                exit_code=-1,
                timed_out=True,
                execution_time_ms=round(elapsed, 1),
            )

    def _build_clean_env(self) -> dict[str, str]:
        """Build a minimal, clean environment for subprocess execution."""
        env: dict[str, str] = {}

        # Keep only essential env vars
        for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USER", "LANG"):
            val = os.environ.get(key)
            if val:
                env[key] = val

        # Python-specific
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"

        return env
