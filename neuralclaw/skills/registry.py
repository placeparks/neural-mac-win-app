"""
Skill Registry — Plugin discovery, loading, and registration.

Discovers skills from built-in and user directories, loads their manifests,
and registers their tools for the reasoning cortex.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Any

from neuralclaw.cortex.reasoning.deliberate import ToolDef
from neuralclaw.skills.loader import load_skill_manifest
from neuralclaw.skills.manifest import SkillManifest
from neuralclaw.skills.paths import quarantine_skill_file, resolve_user_skills_dir


# ---------------------------------------------------------------------------
# Skill Registry
# ---------------------------------------------------------------------------

class SkillRegistry:
    """
    Central registry for all skills (built-in and user-installed).

    Handles:
    - Discovery of built-in skills
    - Dynamic loading of skill modules
    - Registration of tool definitions
    - Lookup by name
    """

    def __init__(self) -> None:
        self._skills: dict[str, SkillManifest] = {}
        self._skill_sources: dict[str, str] = {}
        self._user_skills: set[str] = set()
        self._tool_defs: list[ToolDef] = []

    def _set_skill_source(self, name: str, source: str) -> None:
        self._skill_sources[name] = source
        if source == "user":
            self._user_skills.add(name)
        else:
            self._user_skills.discard(name)

    def register(self, manifest: SkillManifest, source: str = "builtin") -> None:
        """Register a skill from its manifest."""
        self._skills[manifest.name] = manifest
        self._set_skill_source(manifest.name, source)

        # Convert to ToolDefs for the reasoning cortex
        for tool in manifest.tools:
            self._tool_defs.append(ToolDef(
                name=tool.name,
                description=tool.description,
                parameters=tool.to_json_schema(),
                handler=tool.handler,
            ))

    def register_tool(
        self,
        name: str,
        description: str,
        function: Any,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """
        Convenience method to register a single async function as a tool
        without constructing a full SkillManifest.

        Args:
            name:        Tool name (must be unique).
            description: Human-readable description shown to the LLM.
            function:    Async callable that implements the tool.
            parameters:  JSON-Schema style parameter dict, e.g.
                         {"query": {"type": "string", "description": "..."}}.
        """
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {k: v for k, v in (parameters or {}).items()},
            "required": list((parameters or {}).keys()),
        }
        self._tool_defs.append(ToolDef(
            name=name,
            description=description,
            parameters=schema,
            handler=function,
        ))

    def load_builtins(self) -> None:
        """Discover and load all built-in skills."""
        import neuralclaw.skills.builtins as builtins_pkg

        for importer, modname, ispkg in pkgutil.iter_modules(builtins_pkg.__path__):
            try:
                module = importlib.import_module(f"neuralclaw.skills.builtins.{modname}")
                if hasattr(module, "get_manifest"):
                    manifest = module.get_manifest()
                    if isinstance(manifest, SkillManifest):
                        self.register(manifest)
            except Exception as e:
                # Log but don't crash on individual skill failures
                print(f"[SkillRegistry] Failed to load builtin skill '{modname}': {e}")

    def hot_register(self, manifest: SkillManifest, source: str | None = None) -> None:
        """
        Register or replace a skill at runtime.
        If a skill with the same name already exists, removes its old tools
        before registering the new ones. Enables live skill updates.
        """
        existing = self._skills.get(manifest.name)
        if existing:
            old_names = {t.name for t in existing.tools}
            self._tool_defs = [td for td in self._tool_defs if td.name not in old_names]

        self._skills[manifest.name] = manifest
        self._set_skill_source(
            manifest.name,
            source or self._skill_sources.get(manifest.name, "runtime"),
        )
        for tool in manifest.tools:
            self._tool_defs.append(ToolDef(
                name=tool.name,
                description=tool.description,
                parameters=tool.to_json_schema(),
                handler=tool.handler,
            ))

    def unregister_skill(self, name: str) -> None:
        """Remove a registered skill and all of its tool definitions."""
        existing = self._skills.pop(name, None)
        self._skill_sources.pop(name, None)
        self._user_skills.discard(name)
        if not existing:
            return

        old_names = {t.name for t in existing.tools}
        self._tool_defs = [td for td in self._tool_defs if td.name not in old_names]

    def load_user_skills(
        self,
        policy_config: Any = None,
        skills_dir: str | Path | None = None,
    ) -> None:
        """Load all skills from ~/.neuralclaw/skills/ on startup."""
        skills_dir = resolve_user_skills_dir(skills_dir)
        skills_dir.mkdir(parents=True, exist_ok=True)
        for path in skills_dir.glob("*.py"):
            try:
                manifest = load_skill_manifest(path, module_prefix="_user")
                self.hot_register(manifest, source="user")
                # Allowlist tools in policy
                if policy_config and hasattr(policy_config, "allowed_tools"):
                    for tool in manifest.tools:
                        if tool.name not in policy_config.allowed_tools:
                            policy_config.allowed_tools.append(tool.name)
            except Exception as e:
                quarantined = quarantine_skill_file(path, reason="invalid")
                print(
                    f"[SkillRegistry] Quarantined invalid user skill '{path.name}' "
                    f"to '{quarantined}': {e}"
                )

    def get_all_tools(self) -> list[ToolDef]:
        """Get all registered tool definitions."""
        return self._tool_defs.copy()

    # Alias used by MCP server and workflow engine
    get_all_tool_defs = get_all_tools

    def get_handler(self, tool_name: str) -> Any | None:
        """Look up a tool handler by name. Returns the async callable or None."""
        for td in self._tool_defs:
            if td.name == tool_name:
                return td.handler
        return None

    def get_skill(self, name: str) -> SkillManifest | None:
        """Look up a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[SkillManifest]:
        """List all registered skills."""
        return list(self._skills.values())

    def list_user_skills(self) -> list[SkillManifest]:
        """List live user-provided skills currently registered in the runtime."""
        return [
            self._skills[name]
            for name in sorted(self._user_skills)
            if name in self._skills
        ]

    @property
    def count(self) -> int:
        return len(self._skills)

    @property
    def tool_count(self) -> int:
        return len(self._tool_defs)

    @property
    def user_skill_count(self) -> int:
        return len(self.list_user_skills())
