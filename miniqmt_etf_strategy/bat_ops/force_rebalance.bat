@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 强制调仓工具 ===
echo.
echo [1/2] 停止策略进程...
set "PID_FILE=%~dp0strategy.pid"
if exist "%PID_FILE%" (
    set /p "STRAT_PID=" < "%PID_FILE%"
    if defined STRAT_PID (
        tasklist /nh /fi "PID eq %STRAT_PID%" 2>nul | findstr /i "python.exe" >nul
        if not errorlevel 1 (
            taskkill /f /pid %STRAT_PID% >nul 2>&1
            echo [done] 已终止策略进程 PID=%STRAT_PID%
        ) else (
            echo [跳过] PID=%STRAT_PID% 不是 python.exe，可能已退出
        )
    ) else (
        echo [跳过] PID 文件为空
    )
) else (
    echo [警告] 未找到 PID 文件（策略可能未启动），跳过杀进程
)
echo.
echo [2/2] 修改状态文件...
"D:\qmt\code\qmt\.venv\Scripts\python.exe" "%~dp0_force_rebalance.py" %*
if %ERRORLEVEL% neq 0 (
    echo 执行失败
    pause
    exit /b 1
)
echo.
pause
