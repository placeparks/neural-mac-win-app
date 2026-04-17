# NeuralClaw Desktop - Build Python Sidecar (Windows)
# Run from: desktop/ directory

$ErrorActionPreference = "Stop"
$suffix = "x86_64-pc-windows-msvc"
$specPath = "neuralclaw-sidecar-$suffix.spec"
$sidecarDir = "desktop/src-tauri/sidecar"
$builtSidecar = "dist/neuralclaw-sidecar-$suffix.exe"
$bundledSidecar = Join-Path $sidecarDir "neuralclaw-sidecar-$suffix.exe"

Write-Host "Building NeuralClaw sidecar for: $suffix" -ForegroundColor Cyan

Push-Location ..

python -m PyInstaller `
    --noconfirm `
    --clean `
    $specPath

New-Item -ItemType Directory -Force -Path $sidecarDir | Out-Null

if (Test-Path $bundledSidecar) {
    Remove-Item -LiteralPath $bundledSidecar -Force
}

Copy-Item -LiteralPath $builtSidecar -Destination $bundledSidecar -Force

Pop-Location

Write-Host "Built sidecar: neuralclaw-sidecar-$suffix.exe" -ForegroundColor Green
