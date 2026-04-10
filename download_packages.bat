@echo off
chcp 65001 >nul
echo =====================================================
echo  Oracle SQL Tuner - Download Packages (32bit)
echo  인터넷 되는 PC에서 실행하세요 (집 PC 등)
echo  32bit Oracle Client 환경용 패키지만 다운로드합니다.
echo =====================================================
echo.

rem 32bit Python 3.13 확인
py -3.13-32 --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.13 32bit가 없습니다.
    echo python.org 에서 "Windows installer (32-bit)" 를 설치하세요.
    pause
    exit /b 1
)

if not exist packages_32   mkdir packages_32
if not exist packages_build mkdir packages_build

echo [1/2] 32bit 패키지 다운로드 중 (win32)...
py -3.13-32 -m pip download PyQt5 oracledb sqlparse ^
    --dest packages_32 ^
    --platform win32 ^
    --python-version 3.13 ^
    --only-binary :all:
if %errorlevel% neq 0 (
    echo [ERROR] 32bit 다운로드 실패
    pause
    exit /b 1
)

echo.
echo [2/2] PyInstaller 다운로드 중 (EXE 빌드용)...
py -3.13-32 -m pip download pyinstaller --dest packages_build
echo.

echo =====================================================
echo  완료! 아래 폴더를 회사 PC에 통째로 복사하세요:
echo    packages_32\    - 32bit Python 환경용 패키지
echo    packages_build\ - EXE 빌드용 (빌드할 PC만)
echo =====================================================
pause
