# -*- coding: utf-8 -*-
"""
交易接口测试：连接、快照、委托列表、现价、模拟调仓计划、买卖、撤单。

务必使用模拟盘账号；真实下单请加 --live。

示例:
  python main.py snapshot
  python main.py check
  python main.py orders
  python main.py quote 600000.SH
  python main.py price 600519.SH
  python main.py dry-rebalance --stocks 600519.SH,000858.SZ
  python main.py auto-buy 600000.SH 100 --live
  python main.py buy 600519.SH 100 --live --px 10.5
  python main.py limit-buy 600000.SH 100 8.50 --live
  python main.py sell 600519.SH 100 --live --px 10.5
  python main.py cancel 12345 --live
  python main.py cancel-active --live
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from broker import TradeTestBroker
from config import MIN_ORDER_VOLUME


def setup_log(verbose: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger("trade_test")


def require_live(args, log):
    if not getattr(args, "live", False):
        log.error("本次命令会改写柜台委托。若确认执行请加参数: --live")
        sys.exit(2)


def cmd_snapshot(broker, _args, log):
    broker.snapshot()


def cmd_orders(broker, _args, log):
    broker.dump_orders()


def cmd_check(broker, _args, log):
    broker.snapshot()
    broker.dump_orders()


def cmd_quote(broker, args, log):
    broker.dump_quote(args.stock)


def cmd_price(broker, args, log):
    p = broker.get_latest_close(args.stock)
    log.info("%s 参考价: %s", args.stock, p if p else "无效")


def cmd_dry_rebalance(broker, args, log):
    stocks = [s.strip() for s in args.stocks.split(",") if s.strip()]
    broker.plan_rebalance_equal(stocks)


def cmd_auto_buy(broker, args, log):
    require_live(args, log)
    px = broker.get_latest_close(args.stock, require_tick=False)
    if not px or px <= 0:
        log.error("自动查询参考价失败，请确认终端已登录且行情可用")
        sys.exit(1)
    lo, hi = broker.get_limit_bounds(args.stock)
    if lo is not None and hi is not None:
        log.info("自动查询: 参考价=%.2f  涨跌停=%.2f ~ %.2f", px, lo, hi)
    else:
        log.info("自动查询: 参考价=%.2f", px)
    oid = broker.order_buy(args.stock, args.volume, args.remark or "auto_buy", ref_price=px)
    if oid:
        time.sleep(1)
        broker.dump_orders()  # 下单后立即查询确认


def cmd_buy(broker, args, log):
    require_live(args, log)
    oid = broker.order_buy(args.stock, args.volume, args.remark or "test_buy", ref_price=args.px)
    if oid:
        time.sleep(1)
        broker.dump_orders()


def cmd_sell(broker, args, log):
    require_live(args, log)
    oid = broker.order_sell(args.stock, args.volume, args.remark or "test_sell", ref_price=args.px)
    if oid:
        time.sleep(1)
        broker.dump_orders()


def cmd_limit_buy(broker, args, log):
    require_live(args, log)
    broker.order_limit_buy(args.stock, args.volume, args.price, args.remark or "limit_buy")


def cmd_cancel(broker, args, log):
    require_live(args, log)
    broker.cancel_order_id(args.order_id)


def cmd_cancel_active(broker, args, log):
    require_live(args, log)
    broker.cancel_all_cancellable()


def build_parser():
    p = argparse.ArgumentParser(description="miniqmt 交易接口测试（独立项目）")
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG 日志")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("snapshot", help="资产 + 持仓")

    sub.add_parser("check", help="只读：snapshot + orders 一次性检查")

    sub.add_parser("orders", help="当前委托列表")

    sp = sub.add_parser("quote", help="探测 get_instrument_detail / get_full_tick / get_market_data 取价")
    sp.add_argument("stock")

    sp = sub.add_parser("price", help="取参考价（tick 优先，其次日K）")
    sp.add_argument("stock", help="如 600519.SH")

    sp = sub.add_parser("dry-rebalance", help="仅打印等权调仓计划（不下单）")
    sp.add_argument(
        "--stocks",
        required=True,
        help="逗号分隔代码，如 600519.SH,000858.SZ",
    )

    sp = sub.add_parser("buy", help="市价(含保护价)；无行情时可 --px 指定参考价，需 --live")
    sp.add_argument("stock")
    sp.add_argument("volume", type=int, help=f"股数，>= {MIN_ORDER_VOLUME} 且 100 整数倍")
    sp.add_argument(
        "--px",
        type=float,
        default=None,
        help="参考价（=昨收/现价）。不设则拉行情；拉不到则拒绝下单",
    )
    sp.add_argument("--remark", default="")
    sp.add_argument("--live", action="store_true", help="确认向柜台发单")

    sp = sub.add_parser(
        "auto-buy",
        help="自动查价后买入（优先 tick 最新价）；委托价会按涨跌停钳位，需 --live",
    )
    sp.add_argument("stock")
    sp.add_argument("volume", type=int, help=f"股数，>= {MIN_ORDER_VOLUME} 且 100 整数倍")
    sp.add_argument("--remark", default="")
    sp.add_argument("--live", action="store_true")

    sp = sub.add_parser("limit-buy", help="限价买入（悬挂单测试撤单用），需 --live")
    sp.add_argument("stock")
    sp.add_argument("volume", type=int)
    sp.add_argument("price", type=float, help="委托价（元）")
    sp.add_argument("--remark", default="")
    sp.add_argument("--live", action="store_true")

    sp = sub.add_parser("sell", help="同上")
    sp.add_argument("stock")
    sp.add_argument("volume", type=int)
    sp.add_argument("--px", type=float, default=None, help="参考价；不设则拉行情")
    sp.add_argument("--remark", default="")
    sp.add_argument("--live", action="store_true")

    sp = sub.add_parser("cancel", help="按 order_id 撤单，需 --live")
    sp.add_argument("order_id", type=int)
    sp.add_argument("--live", action="store_true")

    sp = sub.add_parser("cancel-active", help="撤掉所有「认为仍可撤」的委托，需 --live")
    sp.add_argument("--live", action="store_true")

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    log = setup_log(args.verbose)

    handlers = {
        "snapshot": cmd_snapshot,
        "check": cmd_check,
        "orders": cmd_orders,
        "quote": cmd_quote,
        "price": cmd_price,
        "dry-rebalance": cmd_dry_rebalance,
        "auto-buy": cmd_auto_buy,
        "buy": cmd_buy,
        "limit-buy": cmd_limit_buy,
        "sell": cmd_sell,
        "cancel": cmd_cancel,
        "cancel-active": cmd_cancel_active,
    }

    broker = TradeTestBroker(log)
    try:
        broker.connect()
        handlers[args.cmd](broker, args, log)
    except KeyboardInterrupt:
        log.info("中断退出")
    except Exception as exc:
        log.exception("执行失败: %s", exc)
        sys.exit(1)
    finally:
        broker.stop()


if __name__ == "__main__":
    main()
