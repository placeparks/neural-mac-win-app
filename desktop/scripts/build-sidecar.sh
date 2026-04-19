#!/bin/bash
# NeuralClaw Desktop — Build Python Sidecar (macOS / Linux)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
NEURALCLAW_ROOT="$(dirname "$PROJECT_ROOT")"

# Determine platform suffix for Tauri sidecar naming.
# Prefer an explicit target from CI/build orchestration so sidecar naming stays
# aligned with the Tauri bundle target, then fall back to the host platform.
TARGET_TRIPLE="${TARGET_TRIPLE:-${TAURI_TARGET_TRIPLE:-${CARGO_BUILD_TARGET:-}}}"

if [ -n "$TARGET_TRIPLE" ]; then
    SUFFIX="$TARGET_TRIPLE"
else
    case "$(uname -s)-$(uname -m)" in
        Darwin-arm64)  SUFFIX="aarch64-apple-darwin" ;;
        Darwin-x86_64) SUFFIX="x86_64-apple-darwin" ;;
        Linux-x86_64)  SUFFIX="x86_64-unknown-linux-gnu" ;;
        *)             SUFFIX="unknown" ;;
    esac
fi

echo "Building NeuralClaw sidecar for: ${SUFFIX}"

cd "$NEURALCLAW_ROOT"

python -m PyInstaller \
    --name "neuralclaw-sidecar-${SUFFIX}" \
    --onefile \
    --noconfirm \
    --clean \
    --hidden-import=neuralclaw \
    --hidden-import=aiohttp \
    --hidden-import=aiosqlite \
    --collect-all neuralclaw \
    neuralclaw/__main__.py

# Create sidecar directory if needed
mkdir -p "$PROJECT_ROOT/src-tauri/sidecar/"

# Copy to Tauri sidecar directory
cp "dist/neuralclaw-sidecar-${SUFFIX}" \
   "$PROJECT_ROOT/src-tauri/sidecar/"

echo "✅ Sidecar built: neuralclaw-sidecar-${SUFFIX}"
