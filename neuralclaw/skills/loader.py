"""Helpers for loading and validating user skill modules."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

from neuralclaw.skills.manifest import SkillManifest


def load_skill_manifest(path: str | Path, module_prefix: str) -> SkillManifest:
    """Load a skill module from disk and return a validated manifest."""
    skill_path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location(f"{module_prefix}_{skill_path.stem}", skill_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"invalid module spec for {skill_path.name}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "get_manifest"):
        raise ValueError("missing get_manifest()")

    manifest = module.get_manifest()
    if inspect.iscoroutine(manifest):
        manifest.close()
        raise TypeError("get_manifest() must be synchronous and return SkillManifest")
    if not isinstance(manifest, SkillManifest):
        raise TypeError(
            f"get_manifest() returned {type(manifest).__name__}, expected SkillManifest"
        )

    for tool in manifest.tools:
        if not callable(tool.handler):
            raise TypeError(
                f"tool '{tool.name}' handler is {type(tool.handler).__name__}, expected callable"
            )

    return manifest
