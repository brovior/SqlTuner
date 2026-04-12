@echo off
echo ============================================
echo  SQL Tuner v2 - Build EXE
echo ============================================
echo.

py -3.13-32 -m PyInstaller --version > nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    py -3.13-32 -m pip install pyinstaller
)

echo Building...
py -3.13-32 -m PyInstaller v2/SQL_Tuner_v2.spec --clean --noconfirm

if %errorlevel% equ 0 (
    echo.
    echo ============================================
    echo  Build succeeded!
    echo  Output: dist\SQL Tuner v2\
    echo  NOTE: Target PC requires Oracle Client 32-bit
    echo ============================================
) else (
    echo.
    echo ============================================
    echo  Build failed. Check output above.
    echo ============================================
)
echo.
pause
