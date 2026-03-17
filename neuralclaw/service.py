"""
NeuralClaw Windows Service + System Tray — keeps the gateway running forever.

Usage (admin PowerShell):
    neuralclaw service install      Install as Windows service
    neuralclaw service uninstall    Remove Windows service
    neuralclaw service start        Start the service
    neuralclaw service stop         Stop the service
    neuralclaw service status       Check if running

Usage (no admin needed):
    neuralclaw tray                 Launch system tray icon

For non-Windows or non-admin:
    neuralclaw daemon               Run as background daemon (foreground process)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

log = logging.getLogger("neuralclaw.service")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path.home() / ".neuralclaw"
PID_FILE = DATA_DIR / "gateway.pid"
LOG_FILE = DATA_DIR / "gateway.log"
STATUS_FILE = DATA_DIR / "gateway.status"


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# PID management
# ---------------------------------------------------------------------------

def _write_pid() -> None:
    _ensure_data_dir()
    PID_FILE.write_text(str(os.getpid()))


def _read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _clear_pid() -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _is_running(pid: int | None = None) -> bool:
    """Check if the gateway process is alive."""
    if pid is None:
        pid = _read_pid()
    if pid is None:
        return False
    try:
        if sys.platform == "win32":
            # Windows: use tasklist
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        else:
            os.kill(pid, 0)
            return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _write_status(status: str, **extra: str) -> None:
    """Write status JSON for tray/dashboard to read."""
    _ensure_data_dir()
    data = {
        "status": status,
        "pid": os.getpid(),
        "timestamp": time.time(),
        **extra,
    }
    STATUS_FILE.write_text(json.dumps(data))


def _read_status() -> dict:
    try:
        return json.loads(STATUS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "stopped", "pid": None}


# ---------------------------------------------------------------------------
# Gateway runner (core loop used by service, daemon, and tray)
# ---------------------------------------------------------------------------

def run_gateway_blocking(watchdog: bool = True, max_restarts: int = 0) -> None:
    """Run the gateway in the current process, blocking. Optionally with watchdog."""

    _write_pid()
    _write_status("starting")

    restart_count = 0
    consecutive_fast = 0
    FAST_THRESHOLD = 10
    MAX_FAST = 5
    BASE_DELAY = 5

    try:
        while True:
            start_time = time.time()
            restart_count += 1
            _write_status("running", restarts=str(restart_count - 1))

            try:
                asyncio.run(_run_gateway_async())
                # Clean exit
                _write_status("stopped", reason="clean")
                break

            except KeyboardInterrupt:
                _write_status("stopped", reason="interrupted")
                break

            except SystemExit:
                _write_status("stopped", reason="exit")
                break

            except Exception as exc:
                elapsed = time.time() - start_time
                log.error("Gateway crashed after %.0fs: %s", elapsed, exc)
                log.debug(traceback.format_exc())

                if not watchdog:
                    _write_status("crashed", error=str(exc))
                    break

                if elapsed < FAST_THRESHOLD:
                    consecutive_fast += 1
                else:
                    consecutive_fast = 0

                if consecutive_fast >= MAX_FAST:
                    _write_status("crashed", error="crash_loop", reason="too many fast crashes")
                    log.error("Too many fast crashes, stopping. Run 'neuralclaw doctor'.")
                    break

                if max_restarts > 0 and restart_count >= max_restarts:
                    _write_status("crashed", error=str(exc), reason="max_restarts")
                    break

                delay = BASE_DELAY * (2 ** min(consecutive_fast, 4))
                _write_status("restarting", delay=str(delay), error=str(exc))
                log.info("Restarting in %ds...", delay)

                try:
                    time.sleep(delay)
                except KeyboardInterrupt:
                    _write_status("stopped", reason="interrupted")
                    break
    finally:
        _clear_pid()


async def _run_gateway_async() -> None:
    """Single gateway run."""
    from neuralclaw.config import load_config
    from neuralclaw.gateway import NeuralClawGateway

    config = load_config()
    gw = NeuralClawGateway(config)
    gw.build_channels(web_port=config._raw.get("web", {}).get("port", 8081))

    try:
        await gw.run_forever()
    except KeyboardInterrupt:
        await gw.stop()


# ---------------------------------------------------------------------------
# Daemon mode (cross-platform, runs as detached process)
# ---------------------------------------------------------------------------

def start_daemon() -> int:
    """Start the gateway as a detached background process. Returns PID."""
    _ensure_data_dir()

    existing_pid = _read_pid()
    if existing_pid and _is_running(existing_pid):
        return existing_pid  # already running

    # Clean up stale PID file from a previous crashed process
    if existing_pid and not _is_running(existing_pid):
        _clear_pid()
        _write_status("stopped", reason="stale_pid_cleanup")

    python = sys.executable
    daemon_script = Path(__file__).resolve()

    if sys.platform == "win32":
        # Windows: use pythonw or START /B to detach
        pythonw = Path(python).parent / "pythonw.exe"
        if not pythonw.exists():
            pythonw = python

        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008

        proc = subprocess.Popen(
            [str(pythonw), str(daemon_script), "--daemon"],
            stdout=open(str(LOG_FILE), "a"),
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            close_fds=True,
        )
    else:
        # Unix: fork and detach
        proc = subprocess.Popen(
            [python, str(daemon_script), "--daemon"],
            stdout=open(str(LOG_FILE), "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )

    # Wait briefly to make sure it started
    time.sleep(1)
    return proc.pid


def stop_daemon() -> bool:
    """Stop the background gateway process. Returns True if stopped."""
    pid = _read_pid()
    if not pid:
        return True

    if not _is_running(pid):
        _clear_pid()
        return True

    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10)
        else:
            os.kill(pid, signal.SIGTERM)
            # Wait up to 10s for clean shutdown
            for _ in range(20):
                if not _is_running(pid):
                    break
                time.sleep(0.5)
            else:
                os.kill(pid, signal.SIGKILL)
    except Exception:
        pass

    _clear_pid()
    _write_status("stopped", reason="daemon_stop")
    return True


# ---------------------------------------------------------------------------
# System tray (Windows + Linux with pystray fallback)
# ---------------------------------------------------------------------------

def run_tray() -> None:
    """System tray icon to control the gateway."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print("System tray requires: pip install pystray pillow")
        print("Falling back to daemon mode...")
        run_gateway_blocking(watchdog=True)
        return

    def _create_icon_image(color: str = "green") -> Image.Image:
        """Create a simple colored circle icon."""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        colors = {
            "green": (0, 200, 80),
            "red": (200, 50, 50),
            "yellow": (220, 180, 0),
            "gray": (128, 128, 128),
        }
        c = colors.get(color, colors["gray"])
        draw.ellipse([8, 8, 56, 56], fill=c)
        # "NC" text
        try:
            draw.text((18, 18), "NC", fill=(255, 255, 255))
        except Exception:
            pass
        return img

    def _get_status_color() -> str:
        status = _read_status()
        s = status.get("status", "stopped")
        if s == "running":
            return "green"
        elif s in ("starting", "restarting"):
            return "yellow"
        elif s == "crashed":
            return "red"
        return "gray"

    gateway_pid: list[int | None] = [None]

    def on_start(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        pid = start_daemon()
        gateway_pid[0] = pid
        icon.icon = _create_icon_image("green")
        icon.notify("NeuralClaw gateway started", "NeuralClaw")

    def on_stop(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        stop_daemon()
        gateway_pid[0] = None
        icon.icon = _create_icon_image("gray")
        icon.notify("NeuralClaw gateway stopped", "NeuralClaw")

    def on_restart(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        stop_daemon()
        time.sleep(2)
        pid = start_daemon()
        gateway_pid[0] = pid
        icon.icon = _create_icon_image("green")
        icon.notify("NeuralClaw gateway restarted", "NeuralClaw")

    def on_status(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        status = _read_status()
        pid = _read_pid()
        running = _is_running(pid)
        msg = f"Status: {'running' if running else 'stopped'}"
        if pid and running:
            msg += f"\nPID: {pid}"
        restarts = status.get("restarts", "0")
        if restarts != "0":
            msg += f"\nRestarts: {restarts}"
        icon.notify(msg, "NeuralClaw Status")

    def on_logs(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if LOG_FILE.exists():
            if sys.platform == "win32":
                os.startfile(str(LOG_FILE))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(LOG_FILE)])
            else:
                subprocess.Popen(["xdg-open", str(LOG_FILE)])

    def on_quit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        stop_daemon()
        icon.stop()

    def is_running_check(item: pystray.MenuItem) -> bool:
        return _is_running()

    menu = pystray.Menu(
        pystray.MenuItem("Start Gateway", on_start, enabled=lambda item: not _is_running()),
        pystray.MenuItem("Stop Gateway", on_stop, enabled=lambda item: _is_running()),
        pystray.MenuItem("Restart Gateway", on_restart, enabled=lambda item: _is_running()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Status", on_status),
        pystray.MenuItem("View Logs", on_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon(
        "NeuralClaw",
        _create_icon_image(_get_status_color()),
        "NeuralClaw Agent",
        menu,
    )

    # Auto-start gateway
    pid = start_daemon()
    gateway_pid[0] = pid

    icon.run()


# ---------------------------------------------------------------------------
# Windows Service (via pywin32)
# ---------------------------------------------------------------------------

def install_windows_service() -> bool:
    """Install NeuralClaw as a Windows service."""
    if sys.platform != "win32":
        print("Windows services are only available on Windows.")
        return False

    python = sys.executable
    script = Path(__file__).resolve()

    # Use NSSM if available (more reliable), otherwise sc.exe
    nssm = _find_nssm()
    if nssm:
        cmd = [
            nssm, "install", "NeuralClaw",
            python, str(script), "--service",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            # Configure service
            subprocess.run([nssm, "set", "NeuralClaw", "DisplayName", "NeuralClaw Agent Gateway"], capture_output=True)
            subprocess.run([nssm, "set", "NeuralClaw", "Description", "NeuralClaw AI Agent - keeps the gateway running"], capture_output=True)
            subprocess.run([nssm, "set", "NeuralClaw", "Start", "SERVICE_AUTO_START"], capture_output=True)
            subprocess.run([nssm, "set", "NeuralClaw", "AppStdout", str(LOG_FILE)], capture_output=True)
            subprocess.run([nssm, "set", "NeuralClaw", "AppStderr", str(LOG_FILE)], capture_output=True)
            subprocess.run([nssm, "set", "NeuralClaw", "AppRestartDelay", "5000"], capture_output=True)
            print("Service installed successfully (via NSSM).")
            print("  Start:  neuralclaw service start")
            print("  It will auto-start on boot.")
            return True

    # Fallback: sc.exe (basic, less reliable for Python)
    cmd = [
        "sc", "create", "NeuralClaw",
        f"binPath={python} {script} --service",
        "DisplayName=NeuralClaw Agent Gateway",
        "start=auto",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print("Service installed successfully.")
        print("  Start:  neuralclaw service start")
        return True

    if "Access is denied" in result.stderr or "Access is denied" in result.stdout:
        print("ERROR: Run this command as Administrator.")
        print("  Right-click PowerShell → 'Run as Administrator'")
    else:
        print(f"ERROR: {result.stderr or result.stdout}")
    return False


def uninstall_windows_service() -> bool:
    """Remove the Windows service."""
    stop_windows_service()

    nssm = _find_nssm()
    if nssm:
        result = subprocess.run([nssm, "remove", "NeuralClaw", "confirm"], capture_output=True, text=True)
    else:
        result = subprocess.run(["sc", "delete", "NeuralClaw"], capture_output=True, text=True)

    if result.returncode == 0:
        print("Service removed.")
        return True

    print(f"ERROR: {result.stderr or result.stdout}")
    return False


def start_windows_service() -> bool:
    result = subprocess.run(["sc", "start", "NeuralClaw"], capture_output=True, text=True)
    if result.returncode == 0:
        print("Service started.")
        return True
    print(f"ERROR: {result.stderr or result.stdout}")
    return False


def stop_windows_service() -> bool:
    result = subprocess.run(["sc", "stop", "NeuralClaw"], capture_output=True, text=True)
    if result.returncode == 0:
        print("Service stopped.")
        return True
    return False


def service_status() -> str:
    result = subprocess.run(["sc", "query", "NeuralClaw"], capture_output=True, text=True)
    if "RUNNING" in result.stdout:
        return "running"
    elif "STOPPED" in result.stdout:
        return "stopped"
    elif result.returncode != 0:
        return "not_installed"
    return "unknown"


def _find_nssm() -> str | None:
    """Find NSSM (Non-Sucking Service Manager) if installed."""
    try:
        result = subprocess.run(["nssm", "version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            return "nssm"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


# ---------------------------------------------------------------------------
# Startup entry (Task Scheduler — simplest always-on for non-admin users)
# ---------------------------------------------------------------------------

def install_startup() -> bool:
    """Add NeuralClaw to Windows startup via Task Scheduler (no admin needed)."""
    if sys.platform != "win32":
        print("Startup install is Windows-only.")
        return False

    python = sys.executable
    script = Path(__file__).resolve()

    # Method 1: Task Scheduler (works without admin for current user)
    task_xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>NeuralClaw AI Agent Gateway</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
  </Settings>
  <Actions>
    <Exec>
      <Command>{python}</Command>
      <Arguments>{script} --daemon</Arguments>
    </Exec>
  </Actions>
</Task>"""

    xml_path = DATA_DIR / "neuralclaw_task.xml"
    _ensure_data_dir()
    xml_path.write_text(task_xml, encoding="utf-16")

    result = subprocess.run(
        ["schtasks", "/Create", "/TN", "NeuralClaw", "/XML", str(xml_path), "/F"],
        capture_output=True, text=True,
    )

    xml_path.unlink(missing_ok=True)

    if result.returncode == 0:
        print("NeuralClaw will now start automatically on login.")
        print("  The gateway restarts on failure (up to 999 times).")
        print("  Remove with: neuralclaw startup uninstall")
        return True

    # Fallback: Startup folder shortcut
    return _install_startup_shortcut()


def _install_startup_shortcut() -> bool:
    """Fallback: create a .bat in the Startup folder."""
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    if not startup.exists():
        print("Could not find Startup folder.")
        return False

    python = sys.executable
    script = Path(__file__).resolve()

    bat_path = startup / "NeuralClaw.bat"
    bat_path.write_text(
        f'@echo off\nstart /B "" "{python}" "{script}" --daemon\n',
        encoding="utf-8",
    )

    print(f"Startup shortcut created at: {bat_path}")
    print("NeuralClaw will start automatically on login.")
    return True


def uninstall_startup() -> bool:
    """Remove NeuralClaw from startup."""
    removed = False

    # Remove Task Scheduler task
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", "NeuralClaw", "/F"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("Removed from Task Scheduler.")
        removed = True

    # Remove Startup folder shortcut
    startup = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    bat_path = startup / "NeuralClaw.bat"
    if bat_path.exists():
        bat_path.unlink()
        print("Removed startup shortcut.")
        removed = True

    if not removed:
        print("NeuralClaw was not in startup.")

    return removed


# ---------------------------------------------------------------------------
# Script entry point (when run directly as daemon/service)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NeuralClaw Service/Daemon")
    parser.add_argument("--daemon", action="store_true", help="Run as background daemon")
    parser.add_argument("--service", action="store_true", help="Run as Windows service")
    args = parser.parse_args()

    if args.daemon or args.service:
        # Set up file logging
        _ensure_data_dir()
        logging.basicConfig(
            filename=str(LOG_FILE),
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        log.info("NeuralClaw daemon starting (PID %d)", os.getpid())
        run_gateway_blocking(watchdog=True)
    else:
        print("Use 'neuralclaw tray' or 'neuralclaw daemon' instead.")
