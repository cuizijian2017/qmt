@echo off
chcp 65001 >nul
cd /d "%~dp0"
D:\qmt\code\qmt\.venv\Scripts\python.exe debug_order.py
pause
