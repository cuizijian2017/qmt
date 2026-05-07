@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "BAT_DIR=%~dp0"
if "%BAT_DIR:~-1%"=="\" set "BAT_DIR=%BAT_DIR:~0,-1%"
set "STRATEGY_DIR=%BAT_DIR%\.."
set "STATE_DIR=%STRATEGY_DIR%\state"

set "REBALANCE_FREQ=19"

if not exist "%STATE_DIR%" mkdir "%STATE_DIR%"

echo [1/2] 停止策略相关进程...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$all = Get-CimInstance Win32_Process; " ^
  "foreach($p in $all){ " ^
  "  $n=(''+$p.Name).ToLower(); $c=(''+$p.CommandLine).ToLower(); " ^
  "  if([string]::IsNullOrWhiteSpace($c)){ continue }; " ^
  "  if(($n -eq 'cmd.exe' -and $c.Contains('start_strategy.bat')) -or (($n -eq 'python.exe' -or $n -eq 'pythonw.exe') -and $c.Contains('main.py'))){ try{ Stop-Process -Id $p.ProcessId -Force } catch{} } " ^
  "}"

echo [2/2] 写入强制调仓状态...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$stateDir='%STATE_DIR%'; $todayTag=Get-Date -Format 'yyyyMMdd'; " ^
  "$file=Join-Path $stateDir ('strategy_state_'+$todayTag+'.json'); " ^
  "$s=@{}; if(Test-Path $file){ $raw=Get-Content -Path $file -Raw -Encoding UTF8; if(-not [string]::IsNullOrWhiteSpace($raw)){ $obj=$raw|ConvertFrom-Json; $obj.PSObject.Properties|%%{ $s[$_.Name]=$_.Value } } }; " ^
  "if(-not $s.ContainsKey('trade_day_counter')){ $s['trade_day_counter']=0 }; " ^
  "$curr=[int]$s['trade_day_counter']; $freq=[int]%REBALANCE_FREQ%; $forced=[int]([Math]::Ceiling(([double]($curr+1))/[double]$freq)*$freq); " ^
  "$s['trade_day_counter']=$forced; $s['last_rebalance_date']=''; $s['last_window_process_date']=''; $s['cooling_period_left']=0; $s['in_lockdown']=$false; $s['lockdown_days_left']=0; " ^
  "$tmp=$file+'.tmp'; $s|ConvertTo-Json -Depth 20|Set-Content -Path $tmp -Encoding UTF8; Move-Item $tmp $file -Force; " ^
  "Write-Host ('[state] trade_day_counter: '+$curr+' -> '+$forced)"

echo [完成] 已处理，手动启动 bat_start\start_strategy.bat
pause
exit /b 0

