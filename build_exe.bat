@echo off
echo =====================================================
echo  Oracle SQL Tuner - Build EXE (PyInstaller)
echo =====================================================
echo.

cd /d "%~dp0"

if exist packages_build (
    echo Installing PyInstaller from packages_build...
    pip install --no-index --find-links=packages_build pyinstaller
    echo.
)

python -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] PyInstaller not installed.
    echo Run install_online.bat first, or put PyInstaller in packages_build folder.
    pause
    exit /b 1
)

if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist "SQL Tuner.spec" del "SQL Tuner.spec"

echo Building EXE...
echo.

python -m PyInstaller ^
    --name "SQL Tuner" ^
    --windowed ^
    --onedir ^
    --noconfirm ^
    --clean ^
    --add-data "core;core" ^
    --add-data "ui;ui" ^
    --hidden-import "oracledb" ^
    --hidden-import "oracledb.thick_impl" ^
    --hidden-import "PyQt6.QtWidgets" ^
    --hidden-import "PyQt6.QtCore" ^
    --hidden-import "PyQt6.QtGui" ^
    --hidden-import "sqlparse" ^
    main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build failed. Check the messages above.
    pause
    exit /b 1
)

echo.
echo =====================================================
echo  Build success!
echo  Output: dist\SQL Tuner\
echo.
echo  Copy the entire dist\SQL Tuner\ folder to other PCs.
echo  Oracle Client must be installed on target PCs.
echo  Python is NOT required on target PCs.
echo =====================================================
pause
