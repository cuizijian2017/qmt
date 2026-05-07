# -*- coding: utf-8 -*-
"""
完全按照官方示例「简单买卖各一笔」重写，最简测试能否下单成功。
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
        print("[回调] 委托: %s %s status=%s vol=%s traded=%s sysid=%s" % (
            order.stock_code, order.order_remark, order.order_status,
            order.order_volume, order.traded_volume, order.order_sysid))

    def on_stock_trade(self, trade):
        print("[回调] 成交: %s %s price=%s vol=%s" % (
            trade.stock_code, trade.order_remark, trade.traded_price, trade.traded_volume))

    def on_order_error(self, err):
        print("[回调] 下单失败: %s error_id=%s msg=%s" % (err.order_remark, err.error_id, err.error_msg))

    def on_cancel_error(self, err):
        print("[回调] 撤单失败: %s" % err.error_msg)

    def on_order_stock_async_response(self, rsp):
        print("[回调] 异步下单反馈: seq=%s order_id=%s" % (rsp.seq, rsp.order_id))

    def on_account_status(self, status):
        print("[回调] 账号状态: %s status=%s" % (status.account_id, status.status))


def main():
    path = r"D:\迅投极速交易终端 睿智融科版\userdata_mini"
    session_id = int(time.time())
    acc = StockAccount("2064890", "STOCK")

    # 1. 建立交易连接
    trader = XtQuantTrader(path, session_id)
    trader.register_callback(MyCallback())
    trader.start()
    ret = trader.connect()
    print("connect => %s (0=成功)" % ret)
    if ret != 0:
        print("连接失败，退出")
        return

    ret = trader.subscribe(acc)
    print("subscribe => %s (0=成功)" % ret)
    if ret != 0:
        print("订阅失败，退出")
        return

    # 2. 查资产
    asset = trader.query_stock_asset(acc)
    if asset:
        print("可用资金: %s  总资产: %s" % (getattr(asset, "cash", "?"), getattr(asset, "total_asset", "?")))
    else:
        print("query_stock_asset 返回 None")
        return

    # 3. 查持仓
    positions = trader.query_stock_positions(acc)
    if positions:
        for p in positions:
            print("持仓: %s vol=%s can_use=%s" % (p.stock_code, p.volume, p.can_use_volume))
    else:
        print("无持仓")

    # 4. 用 get_full_tick 取行情（官方示例写法）
    stock = "600000.SH"
    print("\n取行情: %s" % stock)
    full_tick = xtdata.get_full_tick([stock])
    print("get_full_tick 返回: %s" % full_tick)

    if not full_tick or stock not in full_tick:
        print("get_full_tick 没有拿到 %s 的数据，尝试 get_instrument_detail" % stock)
        detail = xtdata.get_instrument_detail(stock)
        print("get_instrument_detail: %s" % detail)
        if isinstance(detail, dict):
            current_price = detail.get("PreClose", 0) or detail.get("preClose", 0)
        elif detail and hasattr(detail, "PreClose"):
            current_price = getattr(detail, "PreClose", 0)
        else:
            current_price = 0
        print("用 PreClose 作为价格: %s" % current_price)
    else:
        current_price = full_tick[stock].get("lastPrice", 0)
        print("tick lastPrice: %s" % current_price)

    if not current_price or current_price <= 0:
        print("无法获取价格，退出")
        return

    # 5. 下单（完全按官方示例写法）
    buy_vol = 100
    print("\n下单: 买入 %s %s 股 价格=%s FIX_PRICE" % (stock, buy_vol, current_price))
    seq = trader.order_stock_async(acc, stock, xtconstant.STOCK_BUY, buy_vol,
                                   xtconstant.FIX_PRICE, current_price,
                                   "debug_test", "test_buy")
    print("order_stock_async 返回 seq=%s" % seq)

    # 6. 等几秒看委托状态
    print("\n等待 3 秒查询委托...")
    time.sleep(3)
    orders = trader.query_stock_orders(acc)
    if orders:
        for o in orders:
            print("委托: id=%s %s %s vol=%s traded=%s status=%s" % (
                o.order_id, o.stock_code, o.order_remark,
                o.order_volume, o.traded_volume, o.order_status))
    else:
        print("query_stock_orders 返回 None（无委托或无数据）")

    print("\n等待回调中（按 Ctrl+C 退出）...")
    try:
        trader.run_forever()
    except KeyboardInterrupt:
        print("\n退出")


if __name__ == "__main__":
    main()
