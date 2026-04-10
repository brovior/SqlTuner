@echo off
chcp 65001 >nul
echo =====================================================
echo  Oracle SQL Tuner - Offline Install
echo  인터넷 없는 PC에서 실행하세요
echo =====================================================
echo.

rem 사용할 Python 결정 (32bit 우선)
set PYTHON=
set ARCH=

py -3.13-32 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON=py -3.13-32
    set ARCH=32
    echo [INFO] 32bit Python 3.13 감지
    goto :check_packages
)

py -3.13 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON=py -3.13
    set ARCH=64
    echo [INFO] 64bit Python 3.13 감지
    goto :check_packages
)

echo [ERROR] Python 3.13이 없습니다. python.org에서 설치하세요.
pause
exit /b 1

:check_packages
set PACKAGES_DIR=%~dp0packages_%ARCH%

if not exist "%PACKAGES_DIR%" (
    echo.
    echo [ERROR] %PACKAGES_DIR% 폴더가 없습니다.
    echo.
    echo 인터넷 되는 PC에서 download_packages.bat 실행 후
    echo packages_32\ 또는 packages_64\ 폴더를 이 폴더에 복사하세요.
    echo.
    pause
    exit /b 1
)

echo [INFO] %PACKAGES_DIR% 에서 설치합니다...
echo.

%PYTHON% -m pip install --no-index --find-links="%PACKAGES_DIR%" PyQt5 oracledb sqlparse

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] 설치 실패. packages_%ARCH%\ 폴더 내용을 확인하세요.
    pause
    exit /b 1
)

echo.
echo =====================================================
echo  설치 완료! run.bat으로 실행하세요.
echo =====================================================
pause
