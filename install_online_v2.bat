@echo off
echo [SQL Tuner v2] Installing packages...
echo.
py -3.13-32 -m pip install --upgrade pip
py -3.13-32 -m pip install PyQt5 oracledb sqlglot pytest
echo.
echo Done. Run check_env_v2.bat to verify.
pause
