@echo off
echo =====================================================
echo  Oracle SQL Tuner - Offline Install
echo =====================================================
echo.

set PACKAGES_DIR=%~dp0packages

if not exist "%PACKAGES_DIR%" (
    echo [ERROR] packages folder not found.
    echo.
    echo On a PC with internet, run: download_packages.bat
    echo Then copy the packages folder here and run this again.
    echo.
    echo If you have internet here, run install_online.bat instead.
    echo.
    pause
    exit /b 1
)

echo Installing from packages folder...
pip install --no-index --find-links="%PACKAGES_DIR%" -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Install failed.
    pause
    exit /b 1
)

echo.
echo =====================================================
echo  Install complete! Run run.bat to start.
echo =====================================================
pause
