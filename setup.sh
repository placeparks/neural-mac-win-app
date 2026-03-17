#!/usr/bin/env bash
set -euo pipefail

echo ""
echo "  ============================================"
echo "    NeuralClaw — One-Click Setup (Linux/Mac)"
echo "  ============================================"
echo ""

# -------------------------------------------------------------------
# 1. Check Python 3.12+
# -------------------------------------------------------------------
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 not found. Install python3.12+"
    exit 1
fi

PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYMAJOR=$(echo "$PYVER" | cut -d. -f1)
PYMINOR=$(echo "$PYVER" | cut -d. -f2)

if [ "$PYMAJOR" -lt 3 ] || { [ "$PYMAJOR" -eq 3 ] && [ "$PYMINOR" -lt 12 ]; }; then
    echo "[ERROR] Python 3.12+ required, found $PYVER"
    exit 1
fi
echo "[OK] Python $PYVER detected"

# -------------------------------------------------------------------
# 2. Create venv
# -------------------------------------------------------------------
if [ ! -f ".venv/bin/python" ]; then
    echo "[..] Creating virtual environment..."
    python3 -m venv .venv
    echo "[OK] Virtual environment created"
else
    echo "[OK] Virtual environment already exists"
fi

# -------------------------------------------------------------------
# 3. Install
# -------------------------------------------------------------------
echo "[..] Installing NeuralClaw with all extras..."
.venv/bin/pip install -e ".[all,dev]" --quiet --disable-pip-version-check 2>/dev/null || {
    echo "[WARN] Full install failed, trying base install..."
    .venv/bin/pip install -e ".[dev]" --quiet --disable-pip-version-check
}
echo "[OK] Dependencies installed"

# -------------------------------------------------------------------
# 4. Playwright
# -------------------------------------------------------------------
echo "[..] Installing Playwright Chromium..."
.venv/bin/python -m playwright install chromium &>/dev/null && \
    echo "[OK] Playwright Chromium installed" || \
    echo "[WARN] Playwright browser install skipped (optional)"

# -------------------------------------------------------------------
# 5. Add to PATH
# -------------------------------------------------------------------
VENV_BIN="$(cd .venv/bin && pwd)"
SHELL_RC=""

if [ -n "${ZSH_VERSION:-}" ] || [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
elif [ -f "$HOME/.bash_profile" ]; then
    SHELL_RC="$HOME/.bash_profile"
fi

if echo "$PATH" | grep -q "$VENV_BIN"; then
    echo "[OK] Already in PATH"
else
    export PATH="$VENV_BIN:$PATH"
    if [ -n "$SHELL_RC" ]; then
        echo "" >> "$SHELL_RC"
        echo "# NeuralClaw" >> "$SHELL_RC"
        echo "export PATH=\"$VENV_BIN:\$PATH\"" >> "$SHELL_RC"
        echo "[OK] Added to PATH in $SHELL_RC"
        echo "     Run: source $SHELL_RC   (or open a new terminal)"
    else
        echo "[WARN] Could not detect shell RC file."
        echo "       Add this to your shell profile:"
        echo "       export PATH=\"$VENV_BIN:\$PATH\""
    fi
fi

# -------------------------------------------------------------------
# 6. Init config if needed
# -------------------------------------------------------------------
CONFIG_PATH="${HOME}/.neuralclaw/config.toml"
if [ ! -f "$CONFIG_PATH" ]; then
    echo ""
    echo "  No config found — launching setup wizard..."
    echo ""
    .venv/bin/neuralclaw init
else
    echo "[OK] Config already exists at $CONFIG_PATH"
fi

# -------------------------------------------------------------------
# 7. Smoke test
# -------------------------------------------------------------------
echo ""
echo "[..] Running import smoke test..."
.venv/bin/python -c "from neuralclaw.config import load_config; print('[OK] All core modules load successfully')" 2>/dev/null || {
    echo "[WARN] Smoke test had issues — run 'neuralclaw doctor'"
}

# -------------------------------------------------------------------
# Done
# -------------------------------------------------------------------
echo ""
echo "  ============================================"
echo "    Setup complete!"
echo "  ============================================"
echo ""
echo "  Commands (open a new terminal, or 'source $SHELL_RC'):"
echo ""
echo "    neuralclaw init                 Setup wizard"
echo "    neuralclaw doctor               Check system health"
echo "    neuralclaw status               Show config"
echo "    neuralclaw chat                 Interactive chat"
echo "    neuralclaw gateway              Start all channels"
echo "    neuralclaw gateway --watchdog   Auto-restart mode"
echo "    neuralclaw run                  Init + gateway + watchdog (one step)"
echo "    neuralclaw test                 Run all tests"
echo "    neuralclaw test vector          Test a specific feature"
echo ""
