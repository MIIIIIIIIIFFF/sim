@echo off
title Overnight Edge Scanner
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python is not on PATH. If you have OvernightEdge.exe, double-click that instead.
    pause
    exit /b 1
)

if not exist ".venv\" (
    python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q

echo Opening Overnight Edge...
python app.py
if errorlevel 1 pause
