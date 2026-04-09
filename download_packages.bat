@echo off
echo =====================================================
echo  Oracle SQL Tuner - Download Packages
echo  인터넷 되는 PC에서 실행하세요 (집 PC 등)
echo =====================================================
echo.

rem Python 확인
py -3.13 --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.13이 없습니다.
    pause
    exit /b 1
)

if not exist packages_64  mkdir packages_64
if not exist packages_32  mkdir packages_32
if not exist packages_build mkdir packages_build

echo [1/3] 64bit 패키지 다운로드 중 (win_amd64)...
py -3.13 -m pip download PyQt6 oracledb sqlparse ^
    --dest packages_64 ^
    --platform win_amd64 ^
    --python-version 3.13 ^
    --only-binary :all:
if %errorlevel% neq 0 (
    echo [ERROR] 64bit 다운로드 실패
    pause
    exit /b 1
)

echo.
echo [2/3] 32bit 패키지 다운로드 중 (win32)...
py -3.13 -m pip download PyQt6 oracledb sqlparse ^
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
echo [3/3] PyInstaller 다운로드 중 (빌드용)...
py -3.13 -m pip download pyinstaller --dest packages_build
echo.

echo =====================================================
echo  완료! 아래 폴더를 회사 PC에 통째로 복사하세요:
echo    packages_64\    - 64bit Python 환경용
echo    packages_32\    - 32bit Python 환경용
echo    packages_build\ - EXE 빌드용 (빌드할 PC만)
echo =====================================================
pause
