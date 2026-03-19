#!/usr/bin/env bash
set -euo pipefail

PROFILE="standard"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            PROFILE="${2:-standard}"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

echo ""
echo "  ============================================"
echo "    NeuralClaw - One-Click Setup (Linux/Mac)"
echo "  ============================================"
echo ""

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

case "$PROFILE" in
    lite) EXTRAS="dev" ;;
    standard) EXTRAS="all,dev" ;;
    full) EXTRAS="all,dev" ;;
    *) echo "[ERROR] Unknown profile '$PROFILE' (expected lite|standard|full)"; exit 1 ;;
esac
echo "[OK] Install profile: $PROFILE"

if [ ! -f ".venv/bin/python" ]; then
    echo "[..] Creating virtual environment..."
    python3 -m venv .venv
    echo "[OK] Virtual environment created"
else
    echo "[OK] Virtual environment already exists"
fi

echo "[..] Installing NeuralClaw..."
.venv/bin/pip install -e ".[${EXTRAS}]" --quiet --disable-pip-version-check 2>/dev/null || {
    echo "[WARN] Full install failed, trying base install..."
    .venv/bin/pip install -e ".[dev]" --quiet --disable-pip-version-check
}
echo "[OK] Dependencies installed"

echo "[..] Installing Playwright Chromium..."
.venv/bin/python -m playwright install chromium &>/dev/null && \
    echo "[OK] Playwright Chromium installed" || \
    echo "[WARN] Playwright browser install skipped (optional)"

CONFIG_PATH="${HOME}/.neuralclaw/config.toml"
if [ ! -f "$CONFIG_PATH" ]; then
    echo ""
    echo "  No config found - launching setup wizard..."
    echo ""
    .venv/bin/neuralclaw init
else
    echo "[OK] Config already exists at $CONFIG_PATH"
fi

echo ""
echo "[..] Running import smoke test..."
.venv/bin/python -c "from neuralclaw.config import load_config; print('[OK] Core modules load successfully')" 2>/dev/null || {
    echo "[WARN] Smoke test had issues - run 'neuralclaw doctor'"
}

echo "[..] Running doctor check..."
.venv/bin/neuralclaw doctor || echo "[WARN] Doctor reported issues - review output above"

echo ""
echo "  ============================================"
echo "    Setup complete!"
echo "  ============================================"
echo ""
echo "  Commands:"
echo ""
echo "    neuralclaw doctor"
echo "    neuralclaw chat --dev"
echo "    neuralclaw gateway --watchdog"
echo "    docker compose up --build"
echo ""
