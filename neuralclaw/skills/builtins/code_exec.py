"""
Built-in Skill: Code Execution — Run Python code in sandbox.
"""

from __future__ import annotations

from typing import Any

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.cortex.action.sandbox import Sandbox
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

_sandbox = Sandbox(timeout_seconds=30)


async def execute_python(code: str, **kwargs: Any) -> dict[str, Any]:
    """Execute Python code in a sandboxed environment."""
    result = await _sandbox.execute_python(code)
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
