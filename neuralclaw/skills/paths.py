"""Helpers for resolving skill storage paths."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import shutil
from typing import Any


def _resolve_neuralclaw_home() -> Path:
    """Resolve the effective NeuralClaw home directory."""
    raw = (
        os.environ.get("NEURALCLAW_HOME")
        or os.environ.get("NEURALCLAW_CONFIG_DIR")
        or ""
    )
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".neuralclaw").resolve()


def resolve_user_skills_dir(config_or_path: Any = None) -> Path:
    """Resolve the configured user skills directory."""
    raw = getattr(config_or_path, "user_skills_dir", config_or_path) or ""
    if raw:
        return Path(str(raw)).expanduser().resolve()
    return (_resolve_neuralclaw_home() / "skills").resolve()


def quarantine_skill_file(path: str | Path, reason: str = "invalid") -> Path:
    """Move a malformed skill file out of the active skill directory."""
    src = Path(path).resolve()
    quarantine_dir = (
        _resolve_neuralclaw_home()
        / "skills_quarantine"
        / reason
        / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    target = quarantine_dir / src.name
    counter = 1
    while target.exists():
        target = quarantine_dir / f"{src.stem}_{counter}{src.suffix}"
        counter += 1

    shutil.move(str(src), str(target))
    return target
