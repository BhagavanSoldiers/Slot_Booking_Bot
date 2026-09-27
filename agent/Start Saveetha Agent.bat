@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Saveetha Booking Assistant - Local Agent

echo ================================================
echo      Saveetha Booking Assistant - Local Agent
echo ================================================
echo.

set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"
set "SETUP_MARKER=%VENV%\.saveetha_setup_complete"

REM ------------------------------------------------
REM First-run setup only
REM ------------------------------------------------
if not exist "%PY%" (
    echo First-time setup: creating Python environment...
    py -m venv "%VENV%" 2>nul
    if errorlevel 1 python -m venv "%VENV%"
    if errorlevel 1 (
        echo.
        echo ERROR: Python 3.11+ is required.
        echo Install Python from https://www.python.org/downloads/ and run this again.
        pause
        exit /b 1
    )
    set "FIRST_SETUP=1"
)

REM If the marker is missing, make sure dependencies/browser are installed.
if not exist "%SETUP_MARKER%" set "FIRST_SETUP=1"

if defined FIRST_SETUP (
    echo.
    echo [1/3] Installing Python packages (first run only)...
    "%PY%" -m pip install --upgrade pip
    if errorlevel 1 goto :setup_failed
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 goto :setup_failed

    echo.
    echo [2/3] Checking Playwright Chromium...
    "%PY%" -c "from playwright.sync_api import sync_playwright; import os; p=sync_playwright().start(); ok=os.path.exists(p.chromium.executable_path); p.stop(); raise SystemExit(0 if ok else 1)" >nul 2>&1
    if errorlevel 1 (
        echo Chromium is not installed. Installing it now...
        "%PY%" -m playwright install chromium
        if errorlevel 1 goto :setup_failed
    ) else (
        echo Chromium is already installed. Skipping download.
    )

    echo.
    echo [3/3] Saving setup status...
    >"%SETUP_MARKER%" echo setup-complete
    echo First-time setup complete.
) else (
    echo Existing local environment found.
    echo Skipping Python package and Chromium downloads.
)

echo.
echo Starting local agent...
echo Keep this window open while using the website.
echo.
"%PY%" main.py

if errorlevel 1 (
    echo.
    echo The local agent stopped because of an error.
    pause
)
exit /b 0

:setup_failed
echo.
echo ERROR: First-time setup failed.
echo Fix the error above and run this file again.
pause
exit /b 1
