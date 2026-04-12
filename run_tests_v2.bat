@echo off
echo [SQL Tuner v2] Running unit tests...
echo.
py -3.13-32 -m pytest v2/tests/ -v --tb=short
if %errorlevel% equ 0 (
    echo.
    echo [PASS] All tests passed.
) else (
    echo.
    echo [FAIL] Some tests failed. Check output above.
)
pause
