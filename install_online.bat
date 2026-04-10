@echo off
chcp 65001 >nul
echo =====================================================
echo  Oracle SQL Tuner - Online Install (Internet required)
echo =====================================================
echo.

rem 32bit Python 우선 시도
set PYTHON=
py -3.13-32 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON=py -3.13-32
    echo [INFO] 32bit Python 3.13 감지 - 32bit 패키지를 설치합니다.
    goto :install
)

py -3.13 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON=py -3.13
    echo [INFO] 64bit Python 3.13 감지 - 64bit 패키지를 설치합니다.
    goto :install
)

echo [ERROR] Python 3.13을 찾을 수 없습니다. python.org 에서 설치하세요.
pause
exit /b 1

:install
echo Installing packages...
echo.
%PYTHON% -m pip install PyQt5 oracledb sqlparse

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
echo =====================================================
pause
