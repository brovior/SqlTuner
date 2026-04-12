@echo off
echo Starting Oracle SQL Tuner v2...
py -3.13-32 v2/main.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to start the app.
    echo   - Check if Python 3.13 32-bit is installed.
    echo   - Run check_env_v2.bat to diagnose.
    pause
)
