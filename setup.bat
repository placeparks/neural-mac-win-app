@echo off
setlocal enabledelayedexpansion
title NeuralClaw Setup
color 0B

echo.
echo  ============================================
echo    NeuralClaw — One-Click Setup
echo  ============================================
echo.

:: -------------------------------------------------------------------
:: 1. Check Python
:: -------------------------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed.
    echo         Download from https://python.org/downloads
    echo         Make sure to check "Add to PATH" during install!
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python !PYVER!

:: -------------------------------------------------------------------
:: 2. Install NeuralClaw
:: -------------------------------------------------------------------
echo [..] Installing NeuralClaw (this may take a minute)...
pip install -e ".[all,dev]" --quiet --disable-pip-version-check 2>nul
if errorlevel 1 (
    echo [..] Retrying with base install...
    pip install -e ".[dev]" --quiet --disable-pip-version-check
)
echo [OK] NeuralClaw installed

:: -------------------------------------------------------------------
:: 3. Verify it works
:: -------------------------------------------------------------------
neuralclaw --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] "neuralclaw" command not found in PATH.
    echo        Close this window, open a new terminal, and try again.
    echo        Or run: python -m neuralclaw --help
    pause
    exit /b 1
)
echo [OK] "neuralclaw" command works

:: -------------------------------------------------------------------
:: 4. Install Playwright browsers (optional, silent)
:: -------------------------------------------------------------------
echo [..] Setting up browser engine...
python -m playwright install chromium >nul 2>&1
if not errorlevel 1 echo [OK] Browser engine ready

:: -------------------------------------------------------------------
:: 5. Run setup wizard if no config
:: -------------------------------------------------------------------
if not exist "%USERPROFILE%\.neuralclaw\config.toml" (
    echo.
    neuralclaw init
) else (
    echo [OK] Config found
)

:: -------------------------------------------------------------------
:: 6. Install auto-start on login
:: -------------------------------------------------------------------
echo.
set /p AUTOSTART="Start NeuralClaw automatically on login? (Y/n): "
if /i "!AUTOSTART!" NEQ "n" (
    neuralclaw startup install
    echo [OK] Will auto-start on login
)

:: -------------------------------------------------------------------
:: Done
:: -------------------------------------------------------------------
echo.
echo  ============================================
echo    Setup complete!
echo  ============================================
echo.
echo  Commands:
echo.
echo    neuralclaw run            Start gateway (auto-restarts)
echo    neuralclaw daemon         Run in background
echo    neuralclaw stop           Stop background gateway
echo    neuralclaw restart        Restart background gateway
echo    neuralclaw alive          Check if running
echo    neuralclaw logs           View logs
echo    neuralclaw tray           System tray icon
echo.
echo    neuralclaw chat           Chat in terminal
echo    neuralclaw doctor         Diagnose issues
echo    neuralclaw test           Run tests
echo.
echo  Starting gateway now...
echo.

neuralclaw daemon
pause
