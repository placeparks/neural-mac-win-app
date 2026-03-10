"""
OpenClaw Migration Tool — Import OpenClaw configs and memories into NeuralClaw.

Reads:
  - ~/.openclaw/ or ~/clawd/ config and memory directories
  - OpenClaw memory markdown files → NeuralClaw episodic memory
  - OpenClaw config.json → NeuralClaw config.toml
  - Channel tokens → NeuralClaw keychain
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MigrationReport:
    """Summary of what was migrated."""
    memories_imported: int = 0
    config_migrated: bool = False
    channels_migrated: list[str] = None
    api_keys_migrated: list[str] = None
    warnings: list[str] = None
    errors: list[str] = None

    def __post_init__(self):
        self.channels_migrated = self.channels_migrated or []
        self.api_keys_migrated = self.api_keys_migrated or []
        self.warnings = self.warnings or []
        self.errors = self.errors or []


class OpenClawMigrator:
    """Migrate from OpenClaw / Clawdbot / Moltbot to NeuralClaw."""

    # Known OpenClaw config directory names (in priority order)
    OPENCLAW_DIRS = [
        "~/.openclaw",
        "~/clawd",
        "~/.clawdbot",
        "~/.moltbot",
    ]

    def __init__(self, source_dir: str | None = None):
        self._source = self._find_source(source_dir)
        self._report = MigrationReport()

    def _find_source(self, explicit: str | None = None) -> Path | None:
        """Find the OpenClaw installation directory."""
        if explicit:
            p = Path(explicit).expanduser()
            if p.exists():
                return p
            return None

        for d in self.OPENCLAW_DIRS:
            p = Path(d).expanduser()
            if p.exists():
                return p
        return None

    @property
    def found(self) -> bool:
        return self._source is not None

    @property
    def source_path(self) -> str:
        return str(self._source) if self._source else "not found"

    def scan(self) -> dict[str, Any]:
        """Scan the OpenClaw installation without modifying anything."""
        if not self._source:
            return {"found": False}

        result: dict[str, Any] = {
            "found": True,
            "path": str(self._source),
            "config_exists": False,
            "memory_files": 0,
            "channels": [],
            "providers": [],
        }

        # Check for config
        for config_name in ["config.json", "config.yaml", "config.toml"]:
            if (self._source / config_name).exists():
                result["config_exists"] = True
                try:
                    config = self._read_config()
                    result["channels"] = list(config.get("channels", {}).keys())
                    result["providers"] = list(config.get("providers", {}).keys())
                except Exception as e:
                    result["config_error"] = str(e)
                break

        # Count memory files
        memory_dir = self._source / "memory"
        if memory_dir.exists():
            md_files = list(memory_dir.glob("*.md"))
            result["memory_files"] = len(md_files)

        return result

    def _read_config(self) -> dict[str, Any]:
        """Read OpenClaw config file."""
        if not self._source:
            return {}
        config_path = self._source / "config.json"
        if config_path.exists():
            return json.loads(config_path.read_text())
        return {}

    def migrate_config(self, output_path: str = "~/.neuralclaw/config.toml") -> bool:
        """Convert OpenClaw config.json to NeuralClaw config.toml."""
        if not self._source:
            self._report.errors.append("No OpenClaw installation found")
            return False

        try:
            oc_config = self._read_config()
        except Exception as e:
            self._report.errors.append(f"Failed to read OpenClaw config: {e}")
            return False

        if not oc_config:
            self._report.warnings.append("OpenClaw config is empty")
            return False

        # Build NeuralClaw TOML config
        nc_config_lines = [
            '# NeuralClaw configuration — migrated from OpenClaw',
            f'# Source: {self._source}',
            '',
            '[agent]',
            f'name = "NeuralClaw"',
        ]

        # Migrate provider
        providers = oc_config.get("providers", {})
        agents = oc_config.get("agents", {})
        defaults = agents.get("defaults", {})
        model = defaults.get("model", "")

        if "openrouter" in providers:
            nc_config_lines.extend([
                '',
                '[provider]',
                'name = "openrouter"',
                f'model = "{model}"' if model else 'model = "anthropic/claude-sonnet-4-20250514"',
            ])
            api_key = providers["openrouter"].get("apiKey", "")
            if api_key:
                self._report.api_keys_migrated.append("openrouter")
                nc_config_lines.append(f'# API key: store via `neuralclaw init` (keychain)')
        elif "anthropic" in providers:
            nc_config_lines.extend([
                '',
                '[provider]',
                'name = "anthropic"',
                'model = "claude-sonnet-4-20250514"',
            ])
            if providers["anthropic"].get("apiKey"):
                self._report.api_keys_migrated.append("anthropic")

        # Migrate channels
        channels = oc_config.get("channels", {})
        for ch_name, ch_config in channels.items():
            if not ch_config.get("enabled", False):
                continue
            nc_config_lines.extend([
                '',
                f'[channels.{ch_name}]',
                'enabled = true',
            ])
            if ch_config.get("token"):
                nc_config_lines.append(f'# Token: store via `neuralclaw channels setup`')
                self._report.channels_migrated.append(ch_name)
            if ch_config.get("allowFrom"):
                allow = ch_config["allowFrom"]
                if isinstance(allow, list):
                    nc_config_lines.append(f'allow_from = {json.dumps(allow)}')

        # Write config
        output = Path(output_path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(nc_config_lines) + "\n")
        self._report.config_migrated = True
        return True

    def migrate_memories(self, db_path: str = "~/.neuralclaw/memory.db") -> int:
        """Import OpenClaw memory markdown files into NeuralClaw episodic memory."""
        if not self._source:
            self._report.errors.append("No OpenClaw installation found")
            return 0

        memory_dir = self._source / "memory"
        if not memory_dir.exists():
            self._report.warnings.append("No memory directory found")
            return 0

        md_files = sorted(memory_dir.glob("*.md"))
        if not md_files:
            self._report.warnings.append("No markdown memory files found")
            return 0

        # Parse markdown memories into structured episodes
        episodes = []
        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
                date_match = re.match(r"(\d{4})-(\d{2})-(\d{2})", md_file.stem)
                file_date = None
                if date_match:
                    import datetime
                    file_date = datetime.datetime(
                        int(date_match.group(1)),
                        int(date_match.group(2)),
                        int(date_match.group(3)),
                    ).timestamp()

                # Split by sections/entries
                sections = re.split(r"\n## |\n### |\n- ", content)
                for section in sections:
                    section = section.strip()
                    if not section or len(section) < 10:
                        continue
                    # Truncate very long sections
                    if len(section) > 2000:
                        section = section[:2000] + "..."
                    episodes.append({
                        "content": section,
                        "timestamp": file_date or time.time(),
                        "source": f"openclaw_migration:{md_file.name}",
                    })
            except Exception as e:
                self._report.warnings.append(f"Failed to parse {md_file.name}: {e}")

        # Write to NeuralClaw database
        if episodes:
            db = Path(db_path).expanduser()
            db.parent.mkdir(parents=True, exist_ok=True)
            self._write_episodes_to_db(str(db), episodes)

        self._report.memories_imported = len(episodes)
        return len(episodes)

    def _write_episodes_to_db(self, db_path: str, episodes: list[dict]) -> None:
        """Write episodes directly to SQLite (sync, for migration use)."""
        import sqlite3
        import uuid

        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                timestamp REAL NOT NULL,
                source TEXT NOT NULL DEFAULT 'unknown',
                author TEXT NOT NULL DEFAULT 'unknown',
                content TEXT NOT NULL,
                importance REAL NOT NULL DEFAULT 0.5,
                emotional_valence REAL NOT NULL DEFAULT 0.0,
                tags TEXT NOT NULL DEFAULT '[]',
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed REAL NOT NULL DEFAULT 0.0
            )
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts
            USING fts5(content, content='episodes', content_rowid='rowid')
        """)

        for ep in episodes:
            eid = uuid.uuid4().hex[:16]
            conn.execute(
                "INSERT INTO episodes (id, timestamp, source, author, content, importance) VALUES (?, ?, ?, ?, ?, ?)",
                (eid, ep["timestamp"], ep["source"], "openclaw_migration", ep["content"], 0.5),
            )

        # Rebuild FTS index
        conn.execute("INSERT INTO episodes_fts(episodes_fts) VALUES ('rebuild')")
        conn.commit()
        conn.close()

    def get_report(self) -> MigrationReport:
        return self._report

    def run_full_migration(
        self,
        config_output: str = "~/.neuralclaw/config.toml",
        db_output: str = "~/.neuralclaw/memory.db",
    ) -> MigrationReport:
        """Run complete migration: config + memories."""
        self.migrate_config(config_output)
        self.migrate_memories(db_output)
        return self._report
