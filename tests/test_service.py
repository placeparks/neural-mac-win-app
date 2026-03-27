import json

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
