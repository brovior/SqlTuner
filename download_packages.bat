@echo off
echo =====================================================
echo  Oracle SQL Tuner - Download Packages
echo  Run this on a PC with internet access
echo =====================================================
echo.

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo Detected Python version: %PYVER%

for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do set PYMAJMIN=%%a.%%b
echo Using version parameter: %PYMAJMIN%
echo.

if not exist packages mkdir packages

echo [1/2] Downloading runtime packages (win_amd64, Python %PYMAJMIN%)...
pip download -r requirements.txt -d packages ^
    --platform win_amd64 ^
    --python-version %PYMAJMIN% ^
    --only-binary :all:

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Download failed.
    echo PyQt6 may not have wheels for Python %PYMAJMIN%.
    echo Try changing PYMAJMIN to 3.12 in this file manually.
    pause
    exit /b 1
)

echo.
echo [2/2] Downloading PyInstaller (for EXE build)...
if not exist packages_build mkdir packages_build
pip download pyinstaller -d packages_build

echo.
echo =====================================================
echo  Download complete!
echo  Copy these folders to the office PC:
echo    packages\       - for install.bat
echo    packages_build\ - for build_exe.bat
echo =====================================================
pause
