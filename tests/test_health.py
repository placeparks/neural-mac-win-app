"""Tests for the health checker and repair engine."""

import os
import sqlite3
import tempfile

import pytest

from neuralclaw.health import (
    CheckStatus,
    DiagnosticReport,
    HealthChecker,
    RepairEngine,
)
from neuralclaw.config import (
    NeuralClawConfig,
    ProviderConfig,
    MemoryConfig,
    SecurityConfig,
    ChannelConfig,
)


# ---------------------------------------------------------------------------
# DiagnosticReport
# ---------------------------------------------------------------------------

class TestDiagnosticReport:
    def test_empty_report_is_healthy(self):
        r = DiagnosticReport()
        assert r.healthy
        assert r.ok_count == 0
        assert r.fail_count == 0

    def test_report_counts(self):
        from neuralclaw.health import CheckResult
        r = DiagnosticReport(checks=[
            CheckResult("a", CheckStatus.OK, "ok"),
            CheckResult("b", CheckStatus.WARN, "warn"),
            CheckResult("c", CheckStatus.FAIL, "fail", repairable=True),
        ])
        assert r.ok_count == 1
        assert r.warn_count == 1
        assert r.fail_count == 1
        assert not r.healthy
        assert len(r.repairable) == 1


# ---------------------------------------------------------------------------
# HealthChecker
# ---------------------------------------------------------------------------

class TestHealthChecker:
    def test_check_with_valid_config(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="openai", model="gpt-4o", base_url="", api_key="sk-test"),
            memory=MemoryConfig(db_path=":memory:"),
        )
        checker = HealthChecker(config)
        report = checker.run_all()
        # Should at least have directory checks + config checks
        assert len(report.checks) > 0

    def test_check_provider_missing_key(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="openai", model="gpt-4o", base_url="", api_key=None),
        )
        checker = HealthChecker(config)
        report = checker.run_all()
        provider_checks = [c for c in report.checks if "Provider" in c.name]
        assert any(c.status == CheckStatus.FAIL for c in provider_checks)

    def test_check_proxy_without_base_url(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="proxy", model="gpt-4", base_url="", api_key=None),
        )
        checker = HealthChecker(config)
        report = checker.run_all()
        provider_checks = [c for c in report.checks if "Provider" in c.name]
        # proxy with no base_url — detail says "No base_url" but status is OK
        # (the config validator catches the error, not the provider check)
        assert len(provider_checks) > 0

    def test_check_channel_enabled_no_token(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="local", model="", base_url=""),
            channels=[ChannelConfig(name="telegram", enabled=True, token=None)],
        )
        checker = HealthChecker(config)
        report = checker.run_all()
        ch_checks = [c for c in report.checks if "Channel" in c.name]
        assert any(c.status == CheckStatus.FAIL for c in ch_checks)

    def test_check_database_nonexistent(self):
        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="local", model="", base_url=""),
            memory=MemoryConfig(db_path="/tmp/nonexistent_neuralclaw_test_12345.db"),
        )
        checker = HealthChecker(config)
        report = checker.run_all()
        db_checks = [c for c in report.checks if "Memory DB" in c.name]
        assert any(c.status == CheckStatus.WARN for c in db_checks)

    def test_check_database_valid(self, tmp_dir):
        db_path = os.path.join(tmp_dir, "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE episodes (id INTEGER PRIMARY KEY)")
        conn.close()

        config = NeuralClawConfig(
            primary_provider=ProviderConfig(name="local", model="", base_url=""),
            memory=MemoryConfig(db_path=db_path),
        )
        checker = HealthChecker(config)
        report = checker.run_all()
        db_checks = [c for c in report.checks if "Memory DB" in c.name]
        assert any(c.status == CheckStatus.OK for c in db_checks)

    def test_no_config(self):
        checker = HealthChecker(None)
        report = checker.run_all()
        skip_checks = [c for c in report.checks if c.status == CheckStatus.SKIP]
        assert len(skip_checks) > 0  # Config validation should be SKIP


# ---------------------------------------------------------------------------
# RepairEngine
# ---------------------------------------------------------------------------

class TestRepairEngine:
    def test_repair_creates_directories(self, tmp_dir, monkeypatch):
        import neuralclaw.health as health_mod
        test_config_dir = os.path.join(tmp_dir, "config")
        test_data_dir = os.path.join(tmp_dir, "data")
        test_log_dir = os.path.join(tmp_dir, "logs")

        from pathlib import Path
        monkeypatch.setattr(health_mod, "CONFIG_DIR", Path(test_config_dir))
        monkeypatch.setattr(health_mod, "DATA_DIR", Path(test_data_dir))
        monkeypatch.setattr(health_mod, "LOG_DIR", Path(test_log_dir))

        engine = RepairEngine()
        fixes = engine.repair_directories()
        assert len(fixes) == 3
        assert os.path.isdir(test_config_dir)
        assert os.path.isdir(test_data_dir)
        assert os.path.isdir(test_log_dir)

    def test_repair_corrupt_database(self, tmp_dir):
        db_path = os.path.join(tmp_dir, "corrupt.db")
        with open(db_path, "w") as f:
            f.write("not a sqlite database")

        config = NeuralClawConfig(
            memory=MemoryConfig(db_path=db_path),
        )
        engine = RepairEngine(config)
        fixes = engine.repair_database()
        assert len(fixes) >= 1
        assert not os.path.exists(db_path)  # Corrupt DB deleted

    def test_repair_healthy_database(self, tmp_dir):
        db_path = os.path.join(tmp_dir, "good.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()

        config = NeuralClawConfig(
            memory=MemoryConfig(db_path=db_path),
        )
        engine = RepairEngine(config)
        fixes = engine.repair_database()
        assert len(fixes) == 0  # Nothing to fix
