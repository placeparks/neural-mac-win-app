"""
SkillHotLoader — Watch ~/.neuralclaw/skills/ for new files.
When a new skill file appears, load it and register immediately.
No gateway restart required.

Uses asyncio polling (no watchdog dependency).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from neuralclaw.skills.loader import load_skill_manifest
from neuralclaw.skills.paths import quarantine_skill_file
from neuralclaw.skills.paths import resolve_user_skills_dir

logger = logging.getLogger("neuralclaw.hot_loader")

SKILLS_DIR = resolve_user_skills_dir()
POLL_INTERVAL = 3.0


class SkillHotLoader:
    def __init__(
        self,
        registry: Any,
        bus: Any = None,
        policy_config: Any = None,
        skills_dir: str | Path | None = None,
    ) -> None:
        self._registry = registry
        self._bus = bus
        self._policy_config = policy_config
        self._seen: set[str] = set()
        self._task: asyncio.Task | None = None
        self._skills_dir = resolve_user_skills_dir(skills_dir) if skills_dir else SKILLS_DIR
        self._skills_dir.mkdir(parents=True, exist_ok=True)

    async def start(self, load_existing: bool = True) -> None:
        if load_existing:
            for path in self._skills_dir.glob("*.py"):
                await self._load_skill_file(path, initial=True)
        else:
            for path in self._skills_dir.glob("*.py"):
                self._seen.add(f"{path.name}:{path.stat().st_mtime}")
        self._task = asyncio.create_task(self._watch_loop())
        logger.info("SkillHotLoader watching %s", self._skills_dir)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                for path in self._skills_dir.glob("*.py"):
                    key = f"{path.name}:{path.stat().st_mtime}"
                    if key not in self._seen:
                        await self._load_skill_file(path)
            except Exception:
                logger.exception("HotLoader watch error")

    async def _load_skill_file(self, path: Path, initial: bool = False) -> bool:
        key = f"{path.name}:{path.stat().st_mtime}"
        if key in self._seen:
            return False
        self._seen.add(key)

        try:
            manifest = load_skill_manifest(path, module_prefix="_user_skill")
            self._registry.hot_register(manifest)

            # Allowlist forged tools in policy so they can be invoked
            if self._policy_config and hasattr(self._policy_config, "allowed_tools"):
                for tool in manifest.tools:
                    if tool.name not in self._policy_config.allowed_tools:
                        self._policy_config.allowed_tools.append(tool.name)

            if not initial:
                logger.info("Hot-loaded skill: %s (%d tools)", manifest.name, len(manifest.tools))
                if self._bus:
                    from neuralclaw.bus.neural_bus import EventType
                    await self._bus.publish(
                        EventType.INFO,
                        {"event": "skill_hot_loaded", "skill": manifest.name, "file": str(path)},
                        source="hot_loader",
                    )
            return True

        except Exception as e:
            try:
                quarantined = quarantine_skill_file(path, reason="invalid")
                logger.error(
                    "Failed to hot-load skill %s: %s; quarantined to %s",
                    path.name,
                    e,
                    quarantined,
                )
            except Exception:
                logger.error("Failed to hot-load skill %s: %s", path.name, e)
            return False
