@echo off
chcp 65001
cd /d D:\qmt\code\qmt_etf_strategy

if not exist logs mkdir logs

:loop
echo [%date% %time%] starting strategy >> logs\watchdog.log
.venv\Scripts\python.exe main.py >> logs\console.log 2>&1
echo [%date% %time%] strategy exited, restart in 10 seconds >> logs\watchdog.log
timeout /t 10
goto loop
