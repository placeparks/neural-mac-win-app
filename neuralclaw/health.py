"""
NeuralClaw Health — Diagnostic and repair subsystem.

Provides the engine behind ``neuralclaw doctor`` (diagnose) and
``neuralclaw repair`` (fix) CLI commands.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from neuralclaw.config import (
    CONFIG_DIR,
    CONFIG_FILE,
    DATA_DIR,
    LOG_DIR,
    MEMORY_DB,
    NeuralClawConfig,
    get_api_key,
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class CheckStatus(Enum):
    OK = auto()
    WARN = auto()
    FAIL = auto()
    SKIP = auto()


@dataclass
class CheckResult:
    """Result of a single diagnostic check."""
    name: str
    status: CheckStatus
    message: str
    repairable: bool = False
    repair_action: str = ""


@dataclass
class DiagnosticReport:
    """Full diagnostic report."""
    checks: list[CheckResult] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def ok_count(self) -> int:
        return sum(1 for c in self.checks if c.status == CheckStatus.OK)

    @property
    def warn_count(self) -> int:
        return sum(1 for c in self.checks if c.status == CheckStatus.WARN)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.status == CheckStatus.FAIL)

    @property
    def repairable(self) -> list[CheckResult]:
        return [c for c in self.checks if c.repairable and c.status == CheckStatus.FAIL]

    @property
    def healthy(self) -> bool:
        return self.fail_count == 0


# ---------------------------------------------------------------------------
# Health checker
# ---------------------------------------------------------------------------

class HealthChecker:
    """Run all diagnostic checks."""

    def __init__(self, config: NeuralClawConfig | None = None) -> None:
        self._config = config

    def run_all(self) -> DiagnosticReport:
        report = DiagnosticReport()
        report.checks.extend(self._check_directories())
        report.checks.append(self._check_config_file())
        report.checks.append(self._check_config_valid())
        report.checks.extend(self._check_providers())
        report.checks.extend(self._check_channels())
        report.checks.extend(self._check_databases())
        report.checks.append(self._check_log_dir())
        return report

    # -- Individual checks --------------------------------------------------

    def _check_directories(self) -> list[CheckResult]:
        results = []
        for name, path in [("Config dir", CONFIG_DIR), ("Data dir", DATA_DIR), ("Log dir", LOG_DIR)]:
            if path.exists():
                results.append(CheckResult(name, CheckStatus.OK, f"{path}"))
            else:
                results.append(CheckResult(
                    name, CheckStatus.FAIL, f"{path} missing",
                    repairable=True, repair_action=f"Create {path}",
                ))
        return results

    def _check_config_file(self) -> CheckResult:
        if not CONFIG_FILE.exists():
            return CheckResult(
                "Config file", CheckStatus.FAIL,
                f"{CONFIG_FILE} not found",
                repairable=True, repair_action="Run neuralclaw init",
            )
        try:
            import toml
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                toml.load(f)
            return CheckResult("Config file", CheckStatus.OK, "Valid TOML")
        except Exception as e:
            return CheckResult(
                "Config file", CheckStatus.FAIL,
                f"Invalid TOML: {e}",
                repairable=True, repair_action="Backup and restore default config",
            )

    def _check_config_valid(self) -> CheckResult:
        if not self._config:
            return CheckResult("Config validation", CheckStatus.SKIP, "No config loaded")
        from neuralclaw.config import validate_config
        result = validate_config(self._config)
        if result.valid and not result.warnings:
            return CheckResult("Config validation", CheckStatus.OK, "All checks passed")
        if result.errors:
            return CheckResult("Config validation", CheckStatus.FAIL, "; ".join(result.errors))
        return CheckResult("Config validation", CheckStatus.WARN, "; ".join(result.warnings))

    def _check_providers(self) -> list[CheckResult]:
        results = []
        if not self._config:
            return results
        p = self._config.primary_provider
        if not p:
            results.append(CheckResult("Provider", CheckStatus.FAIL, "No primary provider"))
            return results

        keyless = {"local", "proxy", "chatgpt_app", "claude_app", "chatgpt_token", "claude_token"}
        if p.name in keyless:
            if p.name in {"chatgpt_token", "claude_token"}:
                from neuralclaw.session.auth import AuthManager
                token_provider = "chatgpt" if "chatgpt" in p.name else "claude"
                health = AuthManager(token_provider).health_check()
                if health.get("has_token") and health.get("valid"):
                    ttl = health.get("ttl_seconds")
                    detail = f"token={health['token_type']}"
                    if ttl is not None and ttl < 86400 * 3:
                        detail += f" (expires in {int(ttl / 3600)}h)"
                        results.append(CheckResult(f"Provider: {p.name}", CheckStatus.WARN, detail))
                    else:
                        results.append(CheckResult(f"Provider: {p.name}", CheckStatus.OK, detail))
                elif health.get("has_token"):
                    results.append(CheckResult(
                        f"Provider: {p.name}", CheckStatus.FAIL,
                        "Token expired",
                        repairable=True,
                        repair_action=f"Run neuralclaw session auth {token_provider}",
                    ))
                else:
                    results.append(CheckResult(
                        f"Provider: {p.name}", CheckStatus.FAIL,
                        "No token configured",
                        repairable=True,
                        repair_action=f"Run neuralclaw session auth {token_provider}",
                    ))
            elif p.name in {"chatgpt_app", "claude_app"}:
                if p.profile_dir:
                    detail = f"profile={p.profile_dir}"
                    results.append(CheckResult(f"Provider: {p.name}", CheckStatus.OK, detail))
                else:
                    results.append(CheckResult(
                        f"Provider: {p.name}",
                        CheckStatus.FAIL,
                        "No profile_dir configured",
                        repairable=True,
                        repair_action=f"Run neuralclaw session setup {'chatgpt' if p.name == 'chatgpt_app' else 'claude'}",
                    ))
            else:
                detail = f"base_url={p.base_url}" if p.base_url else "No base_url"
                results.append(CheckResult(f"Provider: {p.name}", CheckStatus.OK, detail))
        elif p.api_key:
            results.append(CheckResult(f"Provider: {p.name}", CheckStatus.OK, "API key configured"))
        else:
            results.append(CheckResult(
                f"Provider: {p.name}", CheckStatus.FAIL,
                "No API key", repairable=True, repair_action="Run neuralclaw init",
            ))
        return results

    def _check_channels(self) -> list[CheckResult]:
        results = []
        if not self._config:
            return results
        for ch in self._config.channels:
            if ch.enabled and ch.token:
                results.append(CheckResult(f"Channel: {ch.name}", CheckStatus.OK, "Token present"))
            elif ch.enabled and not ch.token:
                results.append(CheckResult(
                    f"Channel: {ch.name}", CheckStatus.FAIL,
                    "Enabled but no token",
                    repairable=True, repair_action="Run neuralclaw channels setup",
                ))
        return results

    def _check_databases(self) -> list[CheckResult]:
        results = []
        db_path = Path(self._config.memory.db_path) if self._config else MEMORY_DB
        if not db_path.exists():
            results.append(CheckResult(
                "Memory DB", CheckStatus.WARN,
                f"{db_path} does not exist (created on first run)",
            ))
            return results

        try:
            conn = sqlite3.connect(str(db_path))
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            conn.close()

            if integrity and integrity[0] != "ok":
                results.append(CheckResult(
                    "Memory DB", CheckStatus.FAIL,
                    f"Integrity check: {integrity[0]}",
                    repairable=True, repair_action="Backup and re-create database",
                ))
            elif not tables:
                results.append(CheckResult(
                    "Memory DB", CheckStatus.WARN,
                    "Database exists but has no tables (created on first run)",
                ))
            else:
                results.append(CheckResult("Memory DB", CheckStatus.OK, f"Integrity OK, {len(tables)} tables"))
        except Exception as e:
            results.append(CheckResult(
                "Memory DB", CheckStatus.FAIL,
                f"Corrupt or inaccessible: {e}",
                repairable=True, repair_action="Backup and delete (re-created on next run)",
            ))
        return results

    def _check_log_dir(self) -> CheckResult:
        if not LOG_DIR.exists():
            return CheckResult("Logs", CheckStatus.OK, "No log directory yet")
        log_files = list(LOG_DIR.glob("*.log"))
        total_size = sum(f.stat().st_size for f in log_files)
        if total_size > 100 * 1024 * 1024:
            return CheckResult(
                "Logs", CheckStatus.WARN,
                f"{len(log_files)} files ({total_size // 1024 // 1024} MB) — consider cleanup",
                repairable=True, repair_action="Truncate old logs",
            )
        return CheckResult("Logs", CheckStatus.OK, f"{len(log_files)} log files")


# ---------------------------------------------------------------------------
# Repair engine
# ---------------------------------------------------------------------------

class RepairEngine:
    """Attempt to fix issues found by the health checker."""

    def __init__(self, config: NeuralClawConfig | None = None) -> None:
        self._config = config

    def run_all(self) -> list[str]:
        fixes: list[str] = []
        fixes.extend(self.repair_directories())
        fixes.extend(self.repair_config())
        fixes.extend(self.repair_database())
        fixes.extend(self.repair_logs())
        return fixes

    def repair_directories(self) -> list[str]:
        fixed = []
        for d in (CONFIG_DIR, DATA_DIR, LOG_DIR):
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                fixed.append(f"Created {d}")
        return fixed

    def repair_config(self) -> list[str]:
        fixed = []
        if not CONFIG_FILE.exists():
            from neuralclaw.config import save_default_config
            save_default_config()
            fixed.append(f"Created default config at {CONFIG_FILE}")
        else:
            try:
                import toml
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    toml.load(f)
            except Exception:
                backup = CONFIG_FILE.with_suffix(f".toml.bak.{int(time.time())}")
                shutil.copy2(CONFIG_FILE, backup)
                fixed.append(f"Backed up corrupt config to {backup}")
                from neuralclaw.config import save_default_config
                CONFIG_FILE.unlink()
                save_default_config()
                fixed.append(f"Restored default config at {CONFIG_FILE}")
        return fixed

    def repair_database(self) -> list[str]:
        fixed = []
        db_path = Path(self._config.memory.db_path) if self._config else MEMORY_DB
        if not db_path.exists():
            return fixed
        conn = None
        try:
            conn = sqlite3.connect(str(db_path))
            result = conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()
            conn = None
            if result and result[0] != "ok":
                raise ValueError(f"Integrity check failed: {result[0]}")
        except Exception:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            backup = db_path.with_suffix(f".db.bak.{int(time.time())}")
            shutil.copy2(db_path, backup)
            fixed.append(f"Backed up corrupt DB to {backup}")
            db_path.unlink()
            fixed.append("Removed corrupt DB (will be re-created on next run)")
        return fixed

    def repair_logs(self) -> list[str]:
        fixed = []
        if not LOG_DIR.exists():
            return fixed
        for log_file in LOG_DIR.glob("*.log"):
            if log_file.stat().st_size > 50 * 1024 * 1024:
                lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                log_file.write_text("\n".join(lines[-10000:]) + "\n", encoding="utf-8")
                fixed.append(f"Truncated {log_file.name}")
        return fixed
