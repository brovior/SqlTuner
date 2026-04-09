@echo off
echo =====================================================
echo  Oracle SQL Tuner - Online Install (Internet required)
echo =====================================================
echo.

py -3.13 --version 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.13 not found. Please install Python 3.13 first.
    pause
    exit /b 1
)

echo Installing packages...
echo.

py -3.13 -m pip install PyQt6 oracledb sqlparse

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Install failed. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo =====================================================
echo  Install complete! Run run.bat to start.
echo  Note: DB connection requires Oracle Client.
echo        At home, only UI preview is available.
echo =====================================================
pause
