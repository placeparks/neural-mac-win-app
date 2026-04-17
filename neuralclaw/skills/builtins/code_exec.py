"""
Built-in Skill: Code Execution — Run Python code in sandbox.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.cortex.action.sandbox import Sandbox
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter


def _build_sandbox() -> Sandbox:
    """Create a sandbox with appropriate allowed directories.

    When running as a desktop sidecar (PyInstaller frozen binary) the user
    owns the machine, so the sandbox is given broad filesystem access.
    Otherwise it falls back to the restrictive default (temp-only).
    """
    allowed: list[str] = []
    if getattr(sys, "frozen", False):
        home = str(Path.home())
        allowed = [
            home,
            str(Path.home() / "Desktop"),
            str(Path.home() / "Documents"),
            str(Path.home() / "Downloads"),
            str(Path.home() / "Projects"),
            str(Path.home() / ".neuralclaw"),
            str(Path.home() / ".neuralclaw" / "workspace" / "repos"),
        ]
    return Sandbox(timeout_seconds=30, allowed_dirs=allowed)


_sandbox = _build_sandbox()


async def execute_python(code: str, working_dir: str | None = None, **kwargs: Any) -> dict[str, Any]:
    """Execute Python code in a sandboxed environment."""
    result = await _sandbox.execute_python(code, working_dir=working_dir)
    return {
        "success": result.success,
        "output": result.output[:5000],  # Cap output
        "error": result.error,
        "execution_time_ms": result.execution_time_ms,
        "timed_out": result.timed_out,
    }


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="code_exec",
        description="Execute Python code in a sandboxed environment",
        capabilities=[Capability.SHELL_EXECUTE],
        tools=[
            ToolDefinition(
                name="execute_python",
                description="Execute Python code and return the output. Code runs in an isolated sandbox with a 30-second timeout.",
                parameters=[
                    ToolParameter(name="code", type="string", description="Python code to execute"),
                ],
                handler=execute_python,
            ),
        ],
    )
