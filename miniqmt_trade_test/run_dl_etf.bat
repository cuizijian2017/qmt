@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
D:\qmt\code\qmt\.venv\Scripts\python.exe dl_etf_data.py
pause
