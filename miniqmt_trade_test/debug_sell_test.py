# -*- coding: utf-8 -*-
"""
测试两种卖出方式在模拟盘的表现：
1. FIX_PRICE（限价）卖出
2. LATEST_PRICE（市价）卖出
"""
import time
import sys

sys.path.append(r"D:\迅投极速交易终端 睿智融科版\bin.x64\Lib\site-packages")

from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtconstant


class MyCallback(XtQuantTraderCallback):
    def on_disconnected(self):
        print("[回调] 连接断开")
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
    def on_account_status(self, status):
        print("[回调] 账号状态: %s status=%s" % (status.account_id, status.status))


def main():
    path = r"D:\迅投极速交易终端 睿智融科版\userdata_mini"
    session_id = int(time.time())
    acc = StockAccount("2064890", "STOCK")

    trader = XtQuantTrader(path, session_id)
    trader.register_callback(MyCallback())
    trader.start()
    ret = trader.connect()
    print("connect => %s (0=成功)" % ret)
    if ret != 0:
        return
    ret = trader.subscribe(acc)
    print("subscribe => %s (0=成功)" % ret)

    # 查可用持仓
    positions = trader.query_stock_positions(acc)
    print("\n当前持仓:")
    if positions:
        for p in positions:
            print("  %s vol=%s can_use=%s" % (p.stock_code, p.volume, p.can_use_volume))
    else:
        print("  无持仓")

    # 取价格
    stock = "600000.SH"
    full_tick = xtdata.get_full_tick([stock])
    detail = xtdata.get_instrument_detail(stock)
    if isinstance(detail, dict):
        pre_close = detail.get("PreClose", 0)
        up_stop = detail.get("UpStopPrice", 0)
        down_stop = detail.get("DownStopPrice", 0)
    else:
        pre_close = 0
        up_stop = down_stop = 0
    print("\n600000.SH 行情: get_full_tick=%s" % full_tick)
    print("  PreClose=%.2f  涨停=%.2f  跌停=%.2f" % (pre_close, up_stop, down_stop))

    # ====== 测试1: FIX_PRICE 卖出 ======
    print("\n====== 测试1: FIX_PRICE 限价卖出 100 股 ======")
    sell_price = round(pre_close * 0.998, 2)  # 略低于前收，确保能成交
    print("  卖出价: %.2f" % sell_price)
    seq1 = trader.order_stock_async(acc, stock, xtconstant.STOCK_SELL, 100,
                                     xtconstant.FIX_PRICE, sell_price,
                                     "sell_test", "sell_fix")
    print("  order_stock_async => seq=%s" % seq1)
    time.sleep(2)

    # ====== 测试2: LATEST_PRICE 卖出 ======
    print("\n====== 测试2: LATEST_PRICE 市价卖出 100 股 ======")
    seq2 = trader.order_stock_async(acc, stock, xtconstant.STOCK_SELL, 100,
                                     xtconstant.LATEST_PRICE, -1,
                                     "sell_test", "sell_latest")
    print("  order_stock_async => seq=%s" % seq2)

    print("\n等待 5 秒查委托状态...")
    time.sleep(5)

    orders = trader.query_stock_orders(acc)
    print("\n当日委托列表（只看本次测试的）:")
    if orders:
        for o in orders:
            if getattr(o, "order_remark", "") in ("sell_fix", "sell_latest", "sell_test"):
                print("  id=%s remark=%s %s status=%s vol=%s traded=%s" % (
                    o.order_id, o.order_remark, o.stock_code, o.order_status,
                    o.order_volume, o.traded_volume))
    else:
        print("  无委托")

    print("\n继续等待回调（Ctrl+C 退出）...")
    try:
        trader.run_forever()
    except KeyboardInterrupt:
        print("\n退出")


if __name__ == "__main__":
    main()
