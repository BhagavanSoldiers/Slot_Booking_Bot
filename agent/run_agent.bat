@echo off
setlocal
cd /d "%~dp0"

echo ================================================
echo      Saveetha Booking Assistant - Local Agent
echo ================================================
echo.

if not exist .venv (
  echo [1/3] Creating local Python environment...
  py -m venv .venv
  if errorlevel 1 python -m venv .venv
  if errorlevel 1 (
    echo.
    echo Python 3.11+ is required.
    echo Install Python from python.org and run this file again.
    pause
    exit /b 1
  )
  call .venv\Scripts\activate.bat
  echo [2/3] Installing Python packages...
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
  echo [3/3] Installing Playwright Chromium...
  python -m playwright install chromium
) else (
  call .venv\Scripts\activate.bat
)

echo.
echo Starting local agent...
echo Keep this window open while using the website.
echo.
python main.py

if errorlevel 1 (
  echo.
  echo The local agent stopped because of an error.
)
pause
