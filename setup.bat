@echo off
setlocal enabledelayedexpansion
title NeuralClaw Setup
color 0B

set PROFILE=standard
if /i "%1"=="--profile" (
    set PROFILE=%2
)

echo.
echo  ============================================
echo    NeuralClaw - One-Click Setup
echo  ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python !PYVER!
echo [OK] Install profile: !PROFILE!

if /i "!PROFILE!"=="lite" (
    set EXTRAS=dev
) else (
    set EXTRAS=all,dev
)

echo [..] Installing NeuralClaw...
pip install -e ".[!EXTRAS!]" --quiet --disable-pip-version-check 2>nul
if errorlevel 1 (
    echo [..] Retrying with base install...
    pip install -e ".[dev]" --quiet --disable-pip-version-check
)
echo [OK] NeuralClaw installed

python -m playwright install chromium >nul 2>&1

if not exist "%USERPROFILE%\.neuralclaw\config.toml" (
    echo.
    neuralclaw init
) else (
    echo [OK] Config found
)

echo [..] Running doctor...
neuralclaw doctor

echo.
echo  ============================================
echo    Setup complete!
echo  ============================================
echo.
echo  Commands:
echo.
echo    neuralclaw doctor
echo    neuralclaw chat --dev
echo    neuralclaw gateway --watchdog
echo    docker compose up --build
echo.
pause
