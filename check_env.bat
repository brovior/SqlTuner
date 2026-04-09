@echo off
echo =====================================================
echo  Oracle SQL Tuner - Environment Check
echo =====================================================
echo.

rem 사용할 Python 결정 (32bit 우선)
set PYTHON=
py -3.13-32 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON=py -3.13-32
) else (
    py -3.13 --version >nul 2>&1
    if %errorlevel% equ 0 set PYTHON=py -3.13
)

echo [1] Python
if "%PYTHON%"=="" (
    echo    [ERROR] Python 3.13을 찾을 수 없습니다
) else (
    %PYTHON% --version
    echo    [OK] %PYTHON%
)
echo.

echo [2] Required Packages
if not "%PYTHON%"=="" (
    %PYTHON% -c "import PyQt6; print('   PyQt6      [OK]', PyQt6.QtCore.PYQT_VERSION_STR)" 2>nul || echo    PyQt6      [NOT INSTALLED]
    %PYTHON% -c "import oracledb; print('   oracledb   [OK]', oracledb.__version__)" 2>nul || echo    oracledb   [NOT INSTALLED]
    %PYTHON% -c "import sqlparse; print('   sqlparse   [OK]', sqlparse.__version__)" 2>nul || echo    sqlparse   [NOT INSTALLED]
) else (
    echo    Python 없음 - 패키지 확인 불가
)
echo.

echo [3] Oracle Client
where sqlplus 2>nul
if %errorlevel% equ 0 (
    echo    [OK] sqlplus found in PATH
) else (
    echo    [NOT FOUND] Oracle Client not installed or not in PATH
    echo    (Thin 모드로 자동 연결 시도합니다)
)
echo.

echo [4] Oracle Environment Variables
if defined TNS_ADMIN (
    echo    TNS_ADMIN   = %TNS_ADMIN%
) else (
    echo    TNS_ADMIN   [not set]
)
if defined ORACLE_HOME (
    echo    ORACLE_HOME = %ORACLE_HOME%
) else (
    echo    ORACLE_HOME [not set]
)
echo.

echo [5] packages folder (offline install)
if exist packages (
    echo    [OK] packages folder exists
) else (
    echo    [NOT FOUND] Run install_online.bat if internet is available
)
echo.

echo =====================================================
echo  Done. Press any key to close.
echo =====================================================
pause
