# -*- coding: utf-8 -*-

import datetime as dt
import time
import traceback

from broker_xtquant import QmtBroker
from config import BUY_SLIPPAGE_BUFFER, HEARTBEAT_INTERVAL_SECONDS, LOOP_INTERVAL_SECONDS, MIN_TRADE_VALUE, REBALANCE_FREQ, REBALANCE_WINDOW_END, REBALANCE_WINDOW_START
from logger import setup_logger
from state_store import load_state, save_state
from strategy import before_trading_start, initialize_state


def today_str():
    return dt.datetime.now().strftime("%Y-%m-%d")


def current_time_hhmm():
    return dt.datetime.now().strftime("%H:%M")


def is_rebalance_window():
    now = current_time_hhmm()
    return REBALANCE_WINDOW_START <= now < REBALANCE_WINDOW_END


def update_day_counter(state, broker, trade_date):
    if not broker.is_trading_day(trade_date):
        return False
    if state.get("last_trade_date") == trade_date:
        return False
    state["last_trade_date"] = trade_date
    state["trade_day_counter"] = int(state.get("trade_day_counter", 0)) + 1
    return True


def process_rebalance(state, broker, trade_date, logger):
    if state.get("last_rebalance_date") == trade_date:
        return
    if int(state.get("trade_day_counter", 0)) % REBALANCE_FREQ != 0:
        logger.info("[%s] 非调仓周期，今日跳过调仓", trade_date)
        state["last_window_process_date"] = trade_date
        return
    if not state.get("if_trade", False):
        logger.info("[%s] 当日策略标记不调仓，跳过窗口执行", trade_date)
        state["last_window_process_date"] = trade_date
        return

    logger.info("[%s] 进入调仓窗口", trade_date)
    targets = state.get("target_stocks", [])
    weights = state.get("target_weights", [])
    if not targets:
        logger.warning("[%s] 目标为空，跳过调仓", trade_date)
        state["last_window_process_date"] = trade_date
        return

    state["target_stocks"] = targets
    state["target_weights"] = weights
    state["last_rebalance_date"] = trade_date
    state["last_window_process_date"] = trade_date
    execute_rebalance(state, broker, targets, weights, trade_date, logger)
    logger.info("[%s] 调仓流程完成，目标=%s", trade_date, dict(zip(targets, weights)))


def execute_rebalance(state, broker, targets, weights, trade_date, logger):
    broker.sync_orders()
    broker.cancel_stale_orders()

    total_asset = broker.get_total_asset()
    cash = broker.get_cash()
    if total_asset is None or total_asset <= 0 or cash is None:
        logger.error("[%s] 资产/资金查询失败，跳过调仓", trade_date)
        return

    positions = broker.positions_dict()
    target_set = set(targets)

    # 先卖
    for stock, pos in list(positions.items()):
        shares = int(pos.get("can_use", pos.get("shares", 0)) / 100) * 100
        if shares < 100:
            continue
        if stock not in target_set:
            if not broker.has_active_order(stock, "sell")[0]:
                broker.order("sell", stock, shares, "清仓非目标")
            continue
        idx = targets.index(stock)
        price = broker.get_latest_price(stock)
        if price <= 0:
            continue
        target_value = total_asset * float(weights[idx])
        target_shares = int(target_value / price / 100) * 100
        delta = target_shares - int(pos.get("shares", 0))
        if delta <= -100 and not broker.has_active_order(stock, "sell")[0]:
            broker.order("sell", stock, abs(delta), "调仓卖出")

    broker.sync_orders()
    cash = broker.get_cash() or cash
    positions = broker.positions_dict()

    # 后买
    for stock, weight in zip(targets, weights):
        if broker.has_active_order(stock, "buy")[0]:
            continue
        price = broker.get_latest_price(stock)
        if price <= 0:
            continue
        target_value = total_asset * float(weight)
        if target_value < MIN_TRADE_VALUE:
            continue
        current_shares = int(positions.get(stock, {}).get("shares", 0))
        target_shares = int(target_value / price / 100) * 100
        delta = target_shares - current_shares
        if delta < 100:
            continue
        max_affordable = int(cash * 0.98 / price / 100) * 100
        buy_shares = min(delta, max_affordable)
        if buy_shares >= 100:
            order_id = broker.order("buy", stock, buy_shares, "调仓买入")
            if order_id:
                cash -= buy_shares * price * BUY_SLIPPAGE_BUFFER


def main():
    logger = setup_logger()
    logger.info("股票策略程序启动")

    state = load_state(logger)
    initialize_state(state)
    broker = QmtBroker(logger, state)
    last_heartbeat_time = 0

    try:
        broker.connect()
        logger.info("miniQMT 连接成功")
        broker.print_account_snapshot()
        save_state(state, logger, quiet=True, trade_date=today_str())

        logger.info("进入主循环")
        while True:
            try:
                trade_date = today_str()
                now = time.time()

                if update_day_counter(state, broker, trade_date):
                    logger.info("[%s] 交易日计数递增: trade_day_counter=%s", trade_date, state.get("trade_day_counter", 0))

                if state.get("last_preopen_date") != trade_date:
                    state["last_preopen_date"] = trade_date
                    before_trading_start(state, broker, trade_date, logger)

                if is_rebalance_window():
                    process_rebalance(state, broker, trade_date, logger)

                if now - last_heartbeat_time >= HEARTBEAT_INTERVAL_SECONDS:
                    logger.info("心跳: 股票策略运行正常")
                    broker.print_account_snapshot()
                    last_heartbeat_time = now

                save_state(state, logger, quiet=True, trade_date=trade_date)
                time.sleep(LOOP_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                logger.info("收到手动停止信号")
                break
            except Exception as exc:
                logger.error("主循环异常: %s", exc)
                logger.error(traceback.format_exc())
                time.sleep(LOOP_INTERVAL_SECONDS)

    except Exception as exc:
        logger.error("策略启动失败: %s", exc)
        logger.error(traceback.format_exc())
    finally:
        try:
            save_state(state, logger, quiet=True, trade_date=today_str())
        except Exception:
            logger.error("退出前保存状态失败")
            logger.error(traceback.format_exc())
        broker.stop()
        logger.info("股票策略程序退出")


if __name__ == "__main__":
    main()

