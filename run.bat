@echo off
cd /d "%~dp0"

py -3.13 --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.13 not found in PATH.
    pause
    exit /b 1
)

py -3.13 main.py
if %errorlevel% neq 0 (
    echo.
    echo =====================================================
    echo  ERROR: Application failed to start.
    echo  Run check_env.bat to diagnose the problem.
    echo  Run install_online.bat to install packages.
    echo =====================================================
    pause
)
