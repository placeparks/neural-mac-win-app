import plistlib

import neuralclaw.service as service_mod


def test_render_launch_agent_plist_contains_supervised_gateway(monkeypatch, tmp_path):
    monkeypatch.setattr(service_mod.sys, "executable", "/usr/local/bin/python3")
    monkeypatch.setattr(service_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(service_mod, "LOG_FILE", tmp_path / "gateway.log")

    payload = plistlib.loads(service_mod.render_launch_agent_plist().encode("utf-8"))

    assert payload["Label"] == service_mod.LAUNCH_AGENT_LABEL
    assert payload["ProgramArguments"] == [
        "/usr/local/bin/python3",
        "-m",
        "neuralclaw.service",
        "--supervised",
    ]
    assert payload["RunAtLoad"] is True
    assert payload["EnvironmentVariables"]["NEURALCLAW_HOME"] == str(tmp_path)


def test_install_startup_routes_to_launch_agent_on_macos(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(service_mod.sys, "platform", "darwin")
    monkeypatch.setattr(
        service_mod,
        "install_service",
        lambda: (calls.append("install_service") or True, "Installed LaunchAgent."),
    )

    assert service_mod.install_startup() is True
    assert calls == ["install_service"]


def test_install_startup_writes_xdg_autostart_when_systemd_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(service_mod.sys, "platform", "linux")
    monkeypatch.setattr(service_mod.sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(service_mod, "_systemctl_available", lambda: False)
    monkeypatch.setattr(service_mod, "XDG_AUTOSTART_DIR", tmp_path)
    monkeypatch.setattr(service_mod, "XDG_AUTOSTART_FILE", tmp_path / "neuralclaw.desktop")
    monkeypatch.setattr(service_mod, "DATA_DIR", tmp_path / ".neuralclaw")

    assert service_mod.install_startup() is True
    entry = (tmp_path / "neuralclaw.desktop").read_text(encoding="utf-8")
    assert "Exec=/usr/bin/python3 -m neuralclaw.service --daemon" in entry
    assert "X-GNOME-Autostart-enabled=true" in entry


def test_uninstall_startup_removes_xdg_autostart(monkeypatch, tmp_path):
    entry = tmp_path / "neuralclaw.desktop"
    entry.write_text("test", encoding="utf-8")
    monkeypatch.setattr(service_mod.sys, "platform", "linux")
    monkeypatch.setattr(service_mod, "_systemctl_available", lambda: False)
    monkeypatch.setattr(service_mod, "XDG_AUTOSTART_FILE", entry)

    assert service_mod.uninstall_startup() is True
    assert not entry.exists()


def test_service_status_reports_launch_agent_installed_without_runtime(monkeypatch, tmp_path):
    launch_agent = tmp_path / "dev.cardify.neuralclaw.plist"
    launch_agent.write_text("plist", encoding="utf-8")
    monkeypatch.setattr(service_mod.sys, "platform", "darwin")
    monkeypatch.setattr(service_mod, "_launchctl_available", lambda: False)
    monkeypatch.setattr(service_mod, "LAUNCH_AGENT_FILE", launch_agent)
    monkeypatch.setattr(service_mod, "_read_pid", lambda: None)

    assert service_mod.service_status() == "installed"
