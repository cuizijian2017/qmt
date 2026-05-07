# -*- coding: utf-8 -*-
"""
极简 xtquant tick 调试脚本
只做：连接、订阅 tick、轮询 get_full_tick
"""

import os
import sys
import time

XTQUANT_PATH = r"D:\迅投极速交易终端 睿智融科版\bin.x64\Lib\site-packages"
QMT_PATH = r"D:\迅投极速交易终端 睿智融科版\userdata_mini"
sys.path.append(XTQUANT_PATH)

from xtquant import xtconstant, xtdata, xttrader
from xtquant.xttype import StockAccount

import json

print("=" * 60)
print("1. 不手动设 data_dir，看看默认的是什么")
# 不主动设置 data_dir
print(f"   当前 xtdata.data_dir = {getattr(xtdata, 'data_dir', 'N/A')}")

# 先 reconnect 一下
print("\n2. xtdata.reconnect()")
try:
    r = xtdata.reconnect()
    print(f"   reconnect => {r}")
except Exception as e:
    print(f"   异常: {e}")

stock = "000001.SZ"

print(f"\n3. get_instrument_detail 看行情服务是否恢复")
try:
    d = xtdata.get_instrument_detail(stock, False)
    print(f"   PreClose={d.get('PreClose')} UpStop={d.get('UpStopPrice')} DownStop={d.get('DownStopPrice')}")
except Exception as e:
    print(f"   异常: {e}")

print("\n4. 之后再看看默认 data_dir 是否变了")
print(f"   xtdata.data_dir = {getattr(xtdata, 'data_dir', 'N/A')}")

# 看 xtdata 模块里的默认路径
print("\n5. 看看 xtdata 模块路径")
import inspect
try:
    module_path = inspect.getfile(xtdata)
    print(f"   xtdata 模块位置: {module_path}")
except:
    pass

print("\n6. 连接 xttrader")
session_id = int(time.time())
trader = xttrader.XtQuantTrader(QMT_PATH, session_id)
trader.start()
ret = trader.connect()
print(f"   connect => {ret}")
account = StockAccount("2064890", "STOCK")
sub_ret = trader.subscribe(account)
print(f"   subscribe => {sub_ret}")

print("\n7. get_instrument_detail（连接后）")
try:
    d = xtdata.get_instrument_detail(stock, False)
    if isinstance(d, dict):
        print(f"   PreClose={d.get('PreClose')} UpStop={d.get('UpStopPrice')} DownStop={d.get('DownStopPrice')}")
        # 下单
        protect = min(d.get('UpStopPrice', 999), max(d.get('DownStopPrice', 0), round(d.get('PreClose') * 1.02, 2)))
        print(f"   保护价={protect}")
        oid = trader.order_stock(account, stock, xtconstant.STOCK_BUY, 100, xtconstant.LATEST_PRICE, protect, "test", "test")
        print(f"   order_stock => {oid}")
except Exception as e:
    print(f"   异常: {e}")

print("\n8. get_full_tick（连接后）")
try:
    r = xtdata.get_full_tick([stock])
    if isinstance(r, dict):
        has_data = any(r.values())
        print(f"   有数据={has_data}, 内容={str(r)[:300]}")
except Exception as e:
    print(f"   异常: {e}")

print("\n" + "=" * 60)
print("按回车退出...")
input()

trader.stop()
