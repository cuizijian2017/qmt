@echo off
setlocal

rem 强制 Python 以 UTF-8 输出
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set "BAT_DIR=%~dp0"
if "%BAT_DIR:~-1%"=="\" set "BAT_DIR=%BAT_DIR:~0,-1%"
set "STRATEGY_DIR=%BAT_DIR%\.."
set "REPO_DIR=%STRATEGY_DIR%\.."
set "LOG_DIR=%STRATEGY_DIR%\logs"
set "PY_EXE=%REPO_DIR%\.venv\Scripts\python.exe"

cd /d "%STRATEGY_DIR%"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:loop

if not exist "%PY_EXE%" (
  echo [%TIME%] python not found >> "%LOG_DIR%\watchdog.log"
  timeout /t 10 >nul
  goto loop
)

"%PY_EXE%" "%STRATEGY_DIR%\main.py" 1>> "%LOG_DIR%\console.log" 2>&1
timeout /t 10 >nul
goto loop

