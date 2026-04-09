@echo off
echo =====================================================
echo  Oracle SQL Tuner - Environment Check
echo =====================================================
echo.

echo [1] Python
py -3.13 --version 2>nul
if %errorlevel% neq 0 (
    echo    [ERROR] Python 3.13 not found in PATH
) else (
    echo    [OK]
)
echo.

echo [2] Required Packages
py -3.13 -c "import PyQt6; print('   PyQt6      [OK]', PyQt6.QtCore.PYQT_VERSION_STR)" 2>nul || echo    PyQt6      [NOT INSTALLED]
py -3.13 -c "import oracledb; print('   oracledb   [OK]', oracledb.__version__)" 2>nul || echo    oracledb   [NOT INSTALLED]
py -3.13 -c "import sqlparse; print('   sqlparse   [OK]', sqlparse.__version__)" 2>nul || echo    sqlparse   [NOT INSTALLED]
echo.

echo [3] Oracle Client
where sqlplus 2>nul
if %errorlevel% equ 0 (
    echo    [OK] sqlplus found in PATH
) else (
    echo    [NOT FOUND] Oracle Client not installed or not in PATH
    echo    (At home: DB connection disabled, UI only)
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
