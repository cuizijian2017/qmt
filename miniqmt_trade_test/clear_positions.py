# -*- coding: utf-8 -*-
"""用 FIX_PRICE + PreClose 清空模拟盘所有持仓（简单版，不卡 run_forever）。"""
import sys
import time

sys.path.append(r"D:\迅投极速交易终端 睿智融科版\bin.x64\Lib\site-packages")

from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtconstant


class Callback(XtQuantTraderCallback):
    def on_stock_order(self, order):
        print("[回调] 委托: %s %s status=%s vol=%s traded=%s" % (
            order.stock_code, order.order_remark, order.order_status,
            order.order_volume, order.traded_volume))

    def on_stock_trade(self, trade):
        print("[回调] 成交: %s %s price=%s vol=%s" % (
            trade.stock_code, trade.order_remark, trade.traded_price, trade.traded_volume))

    def on_order_error(self, err):
        print("[回调] 下单失败: %s error_id=%s msg=%s" % (err.order_remark, err.error_id, err.error_msg))

    def on_order_stock_async_response(self, rsp):
        print("[回调] 异步下单反馈: seq=%s order_id=%s" % (rsp.seq, rsp.order_id))


def get_price(stock):
    detail = xtdata.get_instrument_detail(stock, False)
    if isinstance(detail, dict):
        pc = detail.get("PreClose") or detail.get("preClose")
        if pc not in (None, "", 0):
            return float(pc)
    return 0


def main():
    path = r"D:\迅投极速交易终端 睿智融科版\userdata_mini"
    session_id = int(time.time())
    acc = StockAccount("2064890", "STOCK")

    trader = XtQuantTrader(path, session_id)
    trader.register_callback(Callback())
    trader.start()
    ret = trader.connect()
    print("connect => %s (0=成功)" % ret)
    if ret != 0:
        return

    ret = trader.subscribe(acc)
    print("subscribe => %s (0=成功)" % ret)

    positions = trader.query_stock_positions(acc)
    if not positions:
        print("当前无持仓")
        return

    print("\n当前持仓:")
    for p in positions:
        stock = getattr(p, "stock_code", "?")
        vol = int(getattr(p, "volume", 0) or 0)
        can_use = int(getattr(p, "can_use_volume", 0) or 0)
        print("  %s 总=%s 可用=%s" % (stock, vol, can_use))

    print("\n开始清仓 (FIX_PRICE + PreClose)...")
    for p in positions:
        stock = getattr(p, "stock_code", "")
        can_use = int(getattr(p, "can_use_volume", 0) or 0)
        if not stock or can_use < 100:
            continue
        sell_vol = int(can_use / 100) * 100
        if sell_vol < 100:
            continue
        price = get_price(stock)
        if price <= 0:
            print("跳过 %s: 无法获取价格" % stock)
            continue
        print("卖出 %s %s 股 价格=%s FIX_PRICE" % (stock, sell_vol, price))
        seq = trader.order_stock_async(acc, stock, xtconstant.STOCK_SELL, sell_vol,
                                        xtconstant.FIX_PRICE, price, "clear_all", "清仓")
        print("  seq=%s" % seq)

    print("\n等待 6 秒看回调...")
    time.sleep(6)

    print("\n查询委托状态:")
    orders = trader.query_stock_orders(acc)
    if orders:
        for o in orders:
            print("  id=%s %s status=%s vol=%s traded=%s" % (
                o.order_id, o.stock_code, o.order_status,
                o.order_volume, o.traded_volume))

    print("\n清仓完成")


if __name__ == "__main__":
    main()
