@echo off
chcp 65001
setlocal

rem 强制 Python 以 UTF-8 输出，避免日志乱码
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
echo [%date% %time%] starting stock strategy >> "%LOG_DIR%\watchdog.log"
if not exist "%PY_EXE%" (
  echo [%date% %time%] python not found: "%PY_EXE%" >> "%LOG_DIR%\watchdog.log"
  timeout /t 10 >nul
  goto loop
)

"%PY_EXE%" "%STRATEGY_DIR%\main.py" >> "%LOG_DIR%\console.log" 2>&1
echo [%date% %time%] stock strategy exited, restart in 10 seconds >> "%LOG_DIR%\watchdog.log"
timeout /t 10
goto loop

