# -*- coding: utf-8 -*-
"""强制调仓：修改 state JSON 使策略今日可调仓。由 force_rebalance.bat 调用。"""
import json, os, glob, sys

state_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "state")
files = glob.glob(os.path.join(state_dir, "strategy_state_*.json"))
if not files:
    print("未找到状态文件")
    sys.exit(1)

f = max(files, key=os.path.getmtime)
print("修改文件:", os.path.basename(f))

with open(f, "r", encoding="utf-8-sig") as fp:
    s = json.load(fp)

curr = int(s.get("trade_day_counter", 0))
forced = ((curr // 19) + 1) * 19
s["trade_day_counter"] = forced
s["last_rebalance_date"] = ""
s["last_window_process_date"] = ""
s["rebalance_phase"] = None
s["in_lockdown"] = False
s["lockdown_days_left"] = 0

# 原子写入：先写 tmp 再 replace，避免写入过程中崩溃导致文件损坏
tmp = f + ".tmp"
with open(tmp, "w", encoding="utf-8") as fp:
    json.dump(s, fp, ensure_ascii=False, indent=2)
os.replace(tmp, f)

print(f"trade_day_counter: {curr} -> {forced}")
print("rebalance_phase 已清空")
print("状态已更新，请重启策略")
