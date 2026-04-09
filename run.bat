@echo off
cd /d "%~dp0"

rem 32bit Python 우선 시도 (32bit Oracle Client 환경 대응)
py -3.13-32 --version >nul 2>&1
if %errorlevel% equ 0 (
    py -3.13-32 main.py
    goto :check_result
)

rem 64bit Python 시도
py -3.13 --version >nul 2>&1
if %errorlevel% equ 0 (
    py -3.13 main.py
    goto :check_result
)

echo [ERROR] Python 3.13을 찾을 수 없습니다.
echo python.org 에서 Python 3.13을 설치하세요.
pause
exit /b 1

:check_result
if %errorlevel% neq 0 (
    echo.
    echo =====================================================
    echo  ERROR: Application failed to start.
    echo  Run check_env.bat to diagnose the problem.
    echo  Run install_online.bat to install packages.
    echo =====================================================
    pause
)
