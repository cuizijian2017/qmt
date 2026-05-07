# -*- coding: utf-8 -*-
"""连接 trader 后再下载 ETF 日线数据"""

import sys
import time

XTQUANT_PATH = r"D:\迅投极速交易终端 睿智融科版\bin.x64\Lib\site-packages"
QMT_PATH = r"D:\迅投极速交易终端 睿智融科版\userdata_mini"
sys.path.append(XTQUANT_PATH)

from xtquant import xtconstant, xtdata, xttrader
from xtquant.xttype import StockAccount

# 1. 先连接 trader（策略能连上，看能不能顺带恢复行情）
print("1. 连接 xttrader...")
session_id = int(time.time())
trader = xttrader.XtQuantTrader(QMT_PATH, session_id)
trader.start()
ret = trader.connect()
print(f"   connect => {ret}")

account = StockAccount("2064890", "STOCK")
sub_ret = trader.subscribe(account)
print(f"   subscribe => {sub_ret}")

# 2. 试 xtdata
print("\n2. 试 get_instrument_detail...")
try:
    d = xtdata.get_instrument_detail("000001.SZ", False)
    print(f"   get_instrument_detail: PreClose={d.get('PreClose') if isinstance(d, dict) else 'N/A'}")
except Exception as e:
    print(f"   失败: {e}")

# 3. 下载数据
etfs = [
    "510300.SH", "159915.SZ", "513100.SH", "518880.SH",
    "159985.SZ", "159388.SZ", "512890.SH", "511010.SH",
]

print("\n3. 下载 ETF 日线数据...")
for etf in etfs:
    try:
        print(f"   {etf} ... ", end="")
        xtdata.download_history_data(etf, period="1d")
        print("OK")
    except Exception as e:
        print(f"失败: {e}")
    time.sleep(0.2)

trader.stop()

print("\n4. 验证数据...")
time.sleep(1)
for etf in etfs:
    try:
        r = xtdata.get_market_data_ex(stock_list=[etf], period="1d", count=5)
        if isinstance(r, dict) and etf in r:
            shape = r[etf].shape if hasattr(r[etf], "shape") else "?"
            if hasattr(r[etf], "shape") and r[etf].shape[0] > 0:
                print(f"   {etf}: {r[etf].shape}, close={r[etf]['close'].iloc[-1]}")
            else:
                print(f"   {etf}: 0 行数据")
    except Exception as e:
        print(f"   {etf}: 验证失败 {e}")

input("\n按回车退出...")
