@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Saveetha Booking Assistant - Single Window

echo ================================================
echo      Saveetha Booking Assistant - Single Window
echo ================================================
echo.

set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"
set "SETUP_MARKER=%VENV%\.saveetha_setup_complete"

if not exist "%PY%" goto first_setup
if not exist "%SETUP_MARKER%" goto first_setup
goto start_agent

:first_setup
echo First-time setup: creating Python environment...
if not exist "%PY%" py -m venv "%VENV%"
if not exist "%PY%" python -m venv "%VENV%"
if not exist "%PY%" goto setup_failed

echo.
echo [1/2] Installing Python packages (first run only)...
"%PY%" -m pip install --upgrade pip
if errorlevel 1 goto setup_failed
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto setup_failed

echo.
echo [2/2] Installing Playwright Chromium (first run only)...
"%PY%" -m playwright install chromium
if errorlevel 1 goto setup_failed

>"%SETUP_MARKER%" echo setup-complete

echo.
echo First-time setup complete.

goto start_agent

:start_agent
echo.
echo Starting single-window Saveetha Booking Assistant...
echo.
"%PY%" main.py

if errorlevel 1 (
    echo.
    echo The application stopped because of an error.
    pause
)
exit /b 0

:setup_failed
echo.
echo ERROR: First-time setup failed.
echo Fix the error above and run this file again.
pause
exit /b 1
