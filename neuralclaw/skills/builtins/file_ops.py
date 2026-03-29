"""
Built-in Skill: File Operations — Read, write, and list files.

All operations validate paths against the PolicyEngine's filesystem
allowlist before any I/O. Unauthorized paths are rejected.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.cortex.action.policy import resolve_and_validate_path
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter


# Module-level policy config (updated by gateway on init)
_allowed_roots: list[Path] = []


def set_allowed_roots(roots: list[Path]) -> None:
    """Set the allowed filesystem roots for file operations."""
    global _allowed_roots
    _allowed_roots = roots


def _validate_path(path: str) -> tuple[Path | None, dict[str, Any] | None]:
    """Validate a path against allowed roots. Returns (resolved, error_dict)."""
    if not _allowed_roots:
        return None, {"error": "Filesystem roots not configured. Refusing file access by default."}

    resolved, result = resolve_and_validate_path(path, _allowed_roots)
    if not result.allowed:
        return None, {
            "error": f"Access denied: path '{path}' is outside allowed directories. "
                     f"Allowed: {[str(r) for r in _allowed_roots]}"
        }
    return resolved, None


async def read_file(path: str, **kwargs: Any) -> dict[str, Any]:
    """Read the contents of a file."""
    try:
        p, err = _validate_path(path)
        if err:
            return err

        if not p.exists():
            return {"error": f"File not found: {path}"}
        if not p.is_file():
            return {"error": f"Not a file: {path}"}
        if p.stat().st_size > 1_000_000:  # 1MB limit
            return {"error": "File too large (>1MB)"}

        content = p.read_text(encoding="utf-8", errors="replace")
        return {"path": str(p), "content": content, "size": len(content)}
    except Exception as e:
        return {"error": str(e)}


async def write_file(path: str, content: str, idempotency_key: str | None = None, **kwargs: Any) -> dict[str, Any]:
    """Write content to a file."""
    try:
        p, err = _validate_path(path)
        if err:
            return err

        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"path": str(p), "size": len(content), "success": True, "idempotency_key": idempotency_key}
    except Exception as e:
        return {"error": str(e)}


async def list_directory(path: str = ".", **kwargs: Any) -> dict[str, Any]:
    """List files and directories in a path."""
    try:
        p, err = _validate_path(path)
        if err:
            return err

        if not p.exists():
            return {"error": f"Directory not found: {path}"}
        if not p.is_dir():
            return {"error": f"Not a directory: {path}"}

        entries = []
        for item in sorted(p.iterdir()):
            entry = {
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
            }
            if item.is_file():
                entry["size"] = item.stat().st_size
            entries.append(entry)

        return {"path": str(p), "entries": entries[:100]}
    except Exception as e:
        return {"error": str(e)}


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="file_ops",
        description="Read, write, and list files on the filesystem",
        capabilities=[Capability.FILESYSTEM_READ, Capability.FILESYSTEM_WRITE],
        tools=[
            ToolDefinition(
                name="read_file",
                description="Read the contents of a text file",
                parameters=[
                    ToolParameter(name="path", type="string", description="Path to the file"),
                ],
                handler=read_file,
            ),
            ToolDefinition(
                name="write_file",
                description="Write content to a file (creates parent directories if needed)",
                parameters=[
                    ToolParameter(name="path", type="string", description="Path to write to"),
                    ToolParameter(name="content", type="string", description="Content to write"),
                    ToolParameter(
                        name="idempotency_key",
                        type="string",
                        description="Optional idempotency key to prevent duplicate writes on retries",
                        required=False,
                        default=None,
                    ),
                ],
                handler=write_file,
            ),
            ToolDefinition(
                name="list_directory",
                description="List files and directories in a path",
                parameters=[
                    ToolParameter(name="path", type="string", description="Directory path", required=False, default="."),
                ],
                handler=list_directory,
            ),
        ],
    )
