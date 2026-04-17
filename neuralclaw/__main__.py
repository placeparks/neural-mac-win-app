"""Allow running NeuralClaw as `python -m neuralclaw`."""

# ---------------------------------------------------------------------------
# PyInstaller / frozen-env guard: ensure a home directory is resolvable.
#
# When bundled as a PyInstaller one-file executable (the Tauri sidecar),
# HOME / USERPROFILE may not be inherited, which causes every call to
# ``pathlib.Path.home()`` (used heavily in config.py, gateway.py, etc.)
# to raise RuntimeError("Could not determine home directory").
#
# This block MUST run before any other neuralclaw import because
# ``config.py`` resolves ``CONFIG_DIR = Path.home() / …`` at import time.
# ---------------------------------------------------------------------------
import os as _os

if not _os.environ.get("HOME") and not _os.environ.get("USERPROFILE"):
    # Try the Windows %USERPROFILE% variable first (usually C:\Users\<name>)
    _fallback = _os.path.expandvars("%USERPROFILE%")
    if _fallback and "%" not in _fallback:
        _os.environ["USERPROFILE"] = _fallback
    else:
        # Last resort: synthesise from SystemDrive + USERNAME
        _os.environ["USERPROFILE"] = _os.path.join(
            _os.environ.get("SystemDrive", "C:"),
            "Users",
            _os.environ.get("USERNAME", "Default"),
        )
    # Also set HOME so libraries that check it (e.g. platformdirs) work.
    _os.environ.setdefault("HOME", _os.environ["USERPROFILE"])

from neuralclaw.cli import main

main()
