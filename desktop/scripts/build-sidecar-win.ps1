# NeuralClaw Desktop — Build Python Sidecar (Windows)
# Run from: desktop/ directory

$suffix = "x86_64-pc-windows-msvc"

Write-Host "Building NeuralClaw sidecar for: $suffix" -ForegroundColor Cyan

Push-Location ..

python -m PyInstaller `
    --name "neuralclaw-sidecar-$suffix" `
    --onefile `
    --noconfirm `
    --clean `
    --hidden-import=neuralclaw `
    --hidden-import=aiohttp `
    --hidden-import=aiosqlite `
    --collect-all neuralclaw `
    neuralclaw/__main__.py

# Create sidecar directory if needed
New-Item -ItemType Directory -Force -Path "desktop/src-tauri/sidecar/" | Out-Null

# Copy to Tauri sidecar directory
Copy-Item "dist/neuralclaw-sidecar-$suffix.exe" `
    -Destination "desktop/src-tauri/sidecar/"

Pop-Location

Write-Host "✅ Sidecar built: neuralclaw-sidecar-$suffix.exe" -ForegroundColor Green
