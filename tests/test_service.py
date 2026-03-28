import json
import importlib

from neuralclaw import config
from neuralclaw import service


def test_write_status_allows_explicit_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DATA_DIR", tmp_path)
    monkeypatch.setattr(service, "STATUS_FILE", tmp_path / "gateway.status")

    service._write_status("stopped", pid=12345, reason="daemon_stop")

    payload = json.loads((tmp_path / "gateway.status").read_text(encoding="utf-8"))
    assert payload["status"] == "stopped"
    assert payload["pid"] == 12345
    assert payload["reason"] == "daemon_stop"


def test_stop_daemon_writes_stopped_status_with_gateway_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DATA_DIR", tmp_path)
    monkeypatch.setattr(service, "STATUS_FILE", tmp_path / "gateway.status")
    monkeypatch.setattr(service, "PID_FILE", tmp_path / "gateway.pid")

    (tmp_path / "gateway.pid").write_text("4242", encoding="utf-8")

    monkeypatch.setattr(service, "_is_running", lambda pid=None: True)
    monkeypatch.setattr(service, "subprocess", type("SubprocessStub", (), {
        "run": staticmethod(lambda *args, **kwargs: None),
        "TimeoutExpired": TimeoutError,
    }))

    assert service.stop_daemon() is True

    payload = json.loads((tmp_path / "gateway.status").read_text(encoding="utf-8"))
    assert payload["status"] == "stopped"
    assert payload["pid"] == 4242
    assert payload["reason"] == "daemon_stop"


def test_parse_nssm_environment_reads_home_override():
    parsed = service._parse_nssm_environment("NEURALCLAW_HOME=C:\\Users\\sshuser\\.neuralclaw\nFOO=bar\n")
    assert parsed["NEURALCLAW_HOME"] == "C:\\Users\\sshuser\\.neuralclaw"
    assert parsed["FOO"] == "bar"


def test_get_windows_service_data_dir_prefers_nssm_env(monkeypatch):
    monkeypatch.delenv("NEURALCLAW_HOME", raising=False)
    monkeypatch.delenv("NEURALCLAW_CONFIG_DIR", raising=False)
    monkeypatch.setattr(service, "_get_nssm_setting", lambda name: "NEURALCLAW_HOME=C:\\ProgramData\\NeuralClaw" if name == "AppEnvironmentExtra" else None)
    path = service.get_windows_service_data_dir()
    assert str(path) == "C:\\ProgramData\\NeuralClaw"


def test_install_windows_service_sets_neuralclaw_home(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int = 0):
            self.returncode = returncode
            self.stdout = ""
            self.stderr = ""

    def fake_run(cmd, capture_output=True, text=True):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr(service.sys, "platform", "win32")
    monkeypatch.setattr(service, "_find_nssm", lambda: "nssm")
    monkeypatch.setattr(service, "DATA_DIR", tmp_path)
    monkeypatch.setattr(service, "LOG_FILE", tmp_path / "gateway.log")
    monkeypatch.setattr(service, "subprocess", type("SubprocessStub", (), {"run": staticmethod(fake_run)}))

    assert service.install_windows_service() is True
    assert any(cmd[:4] == ["nssm", "set", "NeuralClaw", "AppEnvironmentExtra"] for cmd in calls)
    assert any(str(tmp_path.resolve()) in " ".join(cmd) for cmd in calls)


def test_config_dir_honors_neuralclaw_home_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NEURALCLAW_HOME", str(tmp_path))
    reloaded = importlib.reload(config)
    try:
        assert reloaded.CONFIG_DIR == tmp_path
        assert reloaded.CONFIG_FILE == tmp_path / "config.toml"
    finally:
        importlib.reload(config)
