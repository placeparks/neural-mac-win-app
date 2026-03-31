"""
Built-in Skill: Package Installer — Install Python packages via pip.

Allows the agent to install Python dependencies on demand when the user
requests functionality that requires a missing package (e.g. pyautogui,
pandas, requests).
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

# Packages that must never be installed (security)
_BLOCKED_PACKAGES = frozenset({
    "os", "sys", "subprocess", "shutil",  # not real packages, common confusion
    "eval", "exec",  # not packages
})

# Max packages per single call
_MAX_PACKAGES = 10


async def pip_install(packages: str, upgrade: bool = False, **kwargs: Any) -> dict[str, Any]:
    """Install one or more Python packages via pip.

    Args:
        packages: Space or comma separated package names (e.g. "pyautogui pillow").
        upgrade: If true, upgrade packages to latest version.
    """
    # Parse package list
    names = [
        p.strip()
        for p in packages.replace(",", " ").split()
        if p.strip()
    ]

    if not names:
        return {"success": False, "error": "No package names provided."}

    if len(names) > _MAX_PACKAGES:
        return {
            "success": False,
            "error": f"Too many packages ({len(names)}). Max {_MAX_PACKAGES} per call.",
        }

    # Security check
    blocked = [n for n in names if n.lower().split("==")[0].split(">=")[0].split("<=")[0] in _BLOCKED_PACKAGES]
    if blocked:
        return {
            "success": False,
            "error": f"Blocked packages: {', '.join(blocked)}",
        }

    cmd = [sys.executable, "-m", "pip", "install"]
    if upgrade:
        cmd.append("--upgrade")
    cmd.extend(names)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=120,
        )

        output = stdout.decode(errors="replace").strip()
        err_output = stderr.decode(errors="replace").strip()

        if proc.returncode == 0:
            return {
                "success": True,
                "packages": names,
                "output": output[-2000:] if len(output) > 2000 else output,
            }
        else:
            return {
                "success": False,
                "packages": names,
                "error": err_output[-2000:] if len(err_output) > 2000 else err_output,
                "return_code": proc.returncode,
            }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": "pip install timed out after 120 seconds.",
            "packages": names,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "packages": names,
        }


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="pip_install",
        description="Install Python packages via pip so the agent can use new libraries",
        tools=[
            ToolDefinition(
                name="pip_install",
                description=(
                    "Install Python packages via pip. Use this when the user asks you to "
                    "install a package, or when you need a library that isn't available. "
                    "Example: pip_install(packages='pyautogui pillow')"
                ),
                parameters=[
                    ToolParameter(
                        name="packages",
                        type="string",
                        description="Space or comma separated package names (e.g. 'pyautogui pillow pandas')",
                    ),
                    ToolParameter(
                        name="upgrade",
                        type="boolean",
                        description="Upgrade packages to latest version",
                        required=False,
                    ),
                ],
                handler=pip_install,
            ),
        ],
    )
