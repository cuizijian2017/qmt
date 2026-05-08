@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 强制调仓工具 ===
echo.
echo [1/2] 停止策略进程...
taskkill /f /im python.exe 2>nul >nul
echo [done]
echo.
echo [2/2] 修改状态文件...
"D:\qmt\code\qmt\.venv\Scripts\python.exe" -c "
import json, os, glob
bat_dir = os.getcwd()
state_dir = os.path.join(bat_dir, '..', 'state')
files = glob.glob(os.path.join(state_dir, 'strategy_state_*.json'))
if not files:
    print('未找到状态文件')
    exit(1)
f = max(files, key=os.path.getmtime)
print('修改文件:', os.path.basename(f))
with open(f, 'r', encoding='utf-8-sig') as fp:
    s = json.load(fp)
curr = int(s.get('trade_day_counter', 0))
forced = ((curr // 19) + 1) * 19
s['trade_day_counter'] = forced
s['last_rebalance_date'] = ''
s['last_window_process_date'] = ''
s['rebalance_phase'] = None
s['in_lockdown'] = False
s['lockdown_days_left'] = 0
with open(f, 'w', encoding='utf-8') as fp:
    json.dump(s, fp, ensure_ascii=False, indent=2)
print(f'trade_day_counter: {curr} -> {forced}')
print('rebalance_phase 已清空')
print('状态已更新，请重启策略')
"
if %ERRORLEVEL% neq 0 (
    echo 执行失败
    pause
    exit /b 1
)
echo.
pause
