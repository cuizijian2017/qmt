@echo off
chcp 65001 >nul
cd /d "%~dp0"
D:\qmt\code\qmt\.venv\Scripts\python.exe main.py auto-buy 600000.SH 100 --live
pause
