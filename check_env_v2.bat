@echo off
echo ============================================
echo  SQL Tuner v2 - Environment Check
echo ============================================
echo.

:: [1] Python 3.13 32-bit
echo [1] Python 3.13 32-bit
py -3.13-32 --version > nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=*" %%v in ('py -3.13-32 --version 2^>^&1') do echo     OK  %%v
) else (
    echo     FAIL  py -3.13-32 not found.
    echo           Install Python 3.13 32-bit from python.org
)
echo.

:: [2] Required packages
echo [2] Required packages
py -3.13-32 -c "import PyQt5; print('    OK  PyQt5', PyQt5.QtCore.PYQT_VERSION_STR)" 2>nul || echo     FAIL  PyQt5 not installed
py -3.13-32 -c "import oracledb; print('    OK  oracledb', oracledb.__version__)" 2>nul || echo     FAIL  oracledb not installed
py -3.13-32 -c "import sqlglot; print('    OK  sqlglot', sqlglot.__version__)" 2>nul || echo     FAIL  sqlglot not installed
py -3.13-32 -c "import openai; print('    OK  openai', openai.__version__)" 2>nul || echo     FAIL  openai not installed
py -3.13-32 -c "import pytest; print('    OK  pytest', pytest.__version__)" 2>nul || echo     WARN  pytest not installed
echo.

:: [3] Oracle Client (Thick mode)
echo [3] Oracle Client (Thick mode)
py -3.13-32 -c "import oracledb; oracledb.init_oracle_client(); print('    OK  Oracle Client initialized')" 2>nul || (
    echo     WARN  Oracle Client init failed.
    echo           App will fall back to Thin mode automatically.
)
echo.

:: [4] v2 package import
echo [4] v2 package structure
py -3.13-32 -c "import sys,os; sys.path.insert(0,os.getcwd()); from v2.core.analysis.composite_analyzer import CompositeAnalyzer; print('    OK  v2 package importable')" 2>nul || (
    echo     FAIL  v2 package import failed.
    echo           Run this bat from project root: %CD%
)
echo.

echo ============================================
echo  Run install_online_v2.bat if packages are missing.
echo  Run run_v2.bat to start the app.
echo ============================================
echo.
pause
