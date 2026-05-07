@echo off
chcp 65001 >nul
setlocal
set "DIR=%~dp0"
if "%DIR:~-1%"=="\" set "DIR=%DIR:~0,-1%"
set "REPO=%DIR%\.."
set "PY=%REPO%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%DIR%"
"%PY%" main.py %*
