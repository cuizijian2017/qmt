# -*- coding: utf-8 -*-

import datetime as dt
import time
import traceback

from broker_xtquant import QmtBroker
from config import (
    COOLING_PERIOD_DAYS,
    DRAWDOWN_LIMIT,
    HEARTBEAT_INTERVAL_SECONDS,
    LOCKDOWN_DAYS,
    LOOP_INTERVAL_SECONDS,
    MAX_INTRADAY_DRAWDOWN,
    MIN_TRADE_VALUE,
    REBALANCE_FREQ,
    REBALANCE_WINDOW_END,
    REBALANCE_WINDOW_START,
)
from logger import setup_logger
from state_store import load_state, save_state
from strategy import compute_targets, calculate_position_scale


def today_str():
    return dt.datetime.now().strftime("%Y-%m-%d")


def current_time_hhmm():
    return dt.datetime.now().strftime("%H:%M")


def is_trading_session_time():
    # 仅在连续竞价时段执行“补单/常规落盘”，避免非交易时段误动作
    now = dt.datetime.now()
    if now.weekday() >= 5:
        return False
    morning_start = now.replace(hour=9, minute=30, second=0, microsecond=0)
    morning_end = now.replace(hour=11, minute=30, second=0, microsecond=0)
    afternoon_start = now.replace(hour=13, minute=0, second=0, microsecond=0)
    afternoon_end = now.replace(hour=15, minute=0, second=0, microsecond=0)
    return (morning_start <= now <= morning_end) or (afternoon_start <= now <= afternoon_end)


def is_trading_day(broker, trade_date=None):
    if broker is not None:
        try:
            return broker.is_trading_day(trade_date)
        except Exception:
            pass
    try:
        if trade_date:
            return dt.datetime.strptime(trade_date, "%Y-%m-%d").weekday() < 5
    except Exception:
        pass
    return dt.datetime.now().weekday() < 5


def _weekday_fallback_day(trade_date=None):
    try:
        if trade_date:
            return dt.datetime.strptime(trade_date, "%Y-%m-%d").weekday() < 5
    except Exception:
        pass
    return dt.datetime.now().weekday() < 5


def get_trading_day_status(broker, trade_date=None):
    # 交易日统一入口：优先 broker(xtdata) 判定，失败回退到工作日规则
    if broker is not None:
        try:
            return broker.get_trading_day_status(trade_date)
        except Exception:
            pass
    return _weekday_fallback_day(trade_date), "fallback_weekday"


def is_state_active_day(broker, trade_date=None):
    # 状态活跃日用于“状态连续性”，和“是否允许交易”分离处理
    is_trade_day, source = get_trading_day_status(broker, trade_date)
    if source == "fallback_conservative":
        # Calendar API unavailable: avoid trading, but keep state continuity.
        return _weekday_fallback_day(trade_date)
    return is_trade_day


def is_rebalance_window(broker, trade_date=None):
    if not is_trading_day(broker, trade_date):
        return False
    now = current_time_hhmm()
    return REBALANCE_WINDOW_START <= now < REBALANCE_WINDOW_END


def estimate_future_trading_date(broker, start_date, trading_days_ahead):
    # 用于日志提示“预计下次调仓/解锁日期”，不参与交易决策
    if trading_days_ahead <= 0:
        return start_date
    try:
        cursor = dt.datetime.strptime(start_date, "%Y-%m-%d")
    except Exception:
        return ""

    passed = 0
    for _ in range(370):
        cursor += dt.timedelta(days=1)
        cursor_str = cursor.strftime("%Y-%m-%d")
        is_day, source = get_trading_day_status(broker, cursor_str)
        if source == "fallback_conservative":
            return ""
        if is_day:
            passed += 1
            if passed >= trading_days_ahead:
                return cursor_str
    return ""


def update_day_counter(state, broker, trade_date):
    # 交易日计数是调仓节奏核心，日历不可用时宁可不推进，避免节奏漂移
    is_trade_day, source = get_trading_day_status(broker, trade_date)
    if not is_trade_day:
        return False
    if source == "fallback_conservative":
        # Calendar is unavailable; do not advance trade-day counter to avoid cadence drift.
        return False
    if state.get("last_trade_date") != trade_date:
        state["last_trade_date"] = trade_date
        state["trade_day_counter"] = int(state.get("trade_day_counter", 0)) + 1
        return True
    return False


def log_trading_day_status_once_per_day(state, broker, trade_date, logger):
    # 每日只打一组摘要，便于人工快速巡检
    if state.get("last_trading_day_log_date") == trade_date:
        return

    is_trade_day, source = get_trading_day_status(broker, trade_date)
    state_active_day = is_state_active_day(broker, trade_date)

    state["last_trading_day_log_date"] = trade_date
    logger.info(
        "[%s] 今天是否交易日: %s (source=%s, state_day=%s)",
        trade_date,
        "是" if is_trade_day else "否",
        source,
        "是" if state_active_day else "否",
    )
    counter = int(state.get("trade_day_counter", 0))
    days_to_rebalance = (REBALANCE_FREQ - (counter % REBALANCE_FREQ)) % REBALANCE_FREQ
    next_rebalance_date = estimate_future_trading_date(broker, trade_date, days_to_rebalance)
    if next_rebalance_date:
        logger.info(
            "[%s] 调仓节奏: trade_day_counter=%s, days_to_rebalance=%s, next_rebalance_date=%s",
            trade_date,
            counter,
            days_to_rebalance,
            next_rebalance_date,
        )
    else:
        logger.warning(
            "[%s] 调仓节奏: trade_day_counter=%s, days_to_rebalance=%s, next_rebalance_date=unknown",
            trade_date,
            counter,
            days_to_rebalance,
        )

    if state.get("in_lockdown"):
        left = int(state.get("lockdown_days_left", 0))
        unlock_date = estimate_future_trading_date(broker, trade_date, max(left, 0))
        if unlock_date:
            logger.info("[%s] 锁仓状态: lockdown_days_left=%s, estimated_unlock_date=%s", trade_date, left, unlock_date)
        else:
            logger.warning("[%s] 锁仓状态: lockdown_days_left=%s, estimated_unlock_date=unknown", trade_date, left)


def log_startup_strategy_snapshot(state, broker, trade_date, logger):
    # 启动快照：开机后第一时间确认策略“接到了哪里”
    counter = int(state.get("trade_day_counter", 0))
    days_to_rebalance = (REBALANCE_FREQ - (counter % REBALANCE_FREQ)) % REBALANCE_FREQ
    next_rebalance_date = estimate_future_trading_date(broker, trade_date, days_to_rebalance)
    last_rebalance_date = state.get("last_rebalance_date") or "N/A"
    logger.info(
        "[启动检查] 上次调仓日期=%s, 当前计数=%s, 距下次调仓剩余交易日=%s, 下次调仓预估日期=%s",
        last_rebalance_date,
        counter,
        days_to_rebalance,
        next_rebalance_date or "unknown",
    )

    in_lockdown = bool(state.get("in_lockdown"))
    lockdown_days_left = int(state.get("lockdown_days_left", 0))
    pending_count = len(state.get("pending_orders", {}))
    logger.info(
        "[启动检查] 锁仓状态=%s, 锁仓剩余天数=%s, 待补单数量=%s",
        "ON" if in_lockdown else "OFF",
        lockdown_days_left,
        pending_count,
    )

    if in_lockdown:
        positions = broker.query_positions()
        if positions is None:
            logger.warning("[启动检查] 锁仓清仓进度=unknown (持仓查询失败)")
        else:
            remain_positions = len(positions)
            logger.info("[启动检查] 锁仓清仓进度=剩余持仓标的数 %s", remain_positions)


def save_state_if_trading_day(state, broker, trade_date, logger, quiet=False):
    # 常规状态落盘：仅在状态活跃日 + 交易时段执行
    if not is_state_active_day(broker, trade_date):
        return False
    if not is_trading_session_time():
        return False
    save_state(state, logger, quiet=quiet, trade_date=trade_date)
    return True


def update_risk_baseline(state, broker, trade_date, logger):
    asset = broker.query_asset()
    if asset is None:
        logger.error("无法获取账户资产，跳过本轮处理")
        return None

    total_asset = float(getattr(asset, "total_asset", 0) or getattr(asset, "m_dTotalAsset", 0) or 0)
    if total_asset <= 0:
        logger.error("账户总资产无效: %s", total_asset)
        return None

    if state.get("risk_check_date") != trade_date:
        state["risk_check_date"] = trade_date
        state["day_start_equity"] = total_asset

    if not state.get("watermark") or total_asset > float(state["watermark"]):
        state["watermark"] = total_asset

    return total_asset


def check_global_risk(state, broker, trade_date, total_asset, logger):
    # 全局风控：日内回撤与账户级回撤任一触发即进入锁仓
    day_start = state.get("day_start_equity")
    if day_start and total_asset < float(day_start) * (1 - MAX_INTRADAY_DRAWDOWN):
        logger.error("当日资产回撤超过 %.2f%%，进入空仓保护", MAX_INTRADAY_DRAWDOWN * 100)
        trigger_lockdown(state, broker, trade_date, logger)
        return False

    watermark = state.get("watermark")
    if watermark:
        drawdown = (total_asset - float(watermark)) / float(watermark)
        if drawdown < -DRAWDOWN_LIMIT and not state.get("in_lockdown"):
            logger.error("账户回撤 %.2f%% 超过阈值，进入空仓保护", drawdown * 100)
            trigger_lockdown(state, broker, trade_date, logger)
            return False

    return True


def cancel_active_buy_orders_for_lockdown(state, broker, logger):
    # 锁仓前先撤活跃买单，防止锁仓后买单继续成交
    canceled = 0
    for key, order in list(state.get("order_book", {}).items()):
        if str(order.get("side", "")).lower() != "buy":
            continue
        if str(order.get("status", "")).lower() not in ("pending", "submitted", "partial_filled", "canceling", "partial_canceling", "unknown"):
            continue
        if order.get("cancel_requested"):
            continue
        if broker.cancel_order(key, order):
            canceled += 1
    if canceled > 0:
        logger.warning("锁仓前撤销活跃买单: %s 笔", canceled)


def trigger_lockdown(state, broker, trade_date, logger):
    state["in_lockdown"] = True
    state["lockdown_days_left"] = LOCKDOWN_DAYS
    state["pending_orders"] = {}
    # Prevent pending buy orders from filling after lockdown is triggered.
    cancel_active_buy_orders_for_lockdown(state, broker, logger)
    submit_lockdown_orders(state, broker, trade_date, logger)
    # Critical risk state should be persisted immediately.
    save_state(state, logger, trade_date=trade_date)


def submit_lockdown_orders(state, broker, trade_date, logger):
    positions = broker.query_positions()
    if positions is None:
        logger.error("无法确认持仓，保持空仓保护")
        return True
    if not positions:
        return False

    if state.get("last_lockdown_order_date") == trade_date:
        logger.warning("空仓保护持仓未清，今日已提交过清仓委托")
        return True

    for stock, pos in positions.items():
        volume = int(pos.get("can_use", pos.get("shares", 0)) / 100) * 100
        if stock and volume >= 100:
            broker.order("sell", stock, volume, "空仓保护")

    state["last_lockdown_order_date"] = trade_date
    return True


def process_lockdown(state, broker, trade_date, logger):
    # 锁仓计时一天最多处理一次，并在变更后立即落盘
    has_positions = submit_lockdown_orders(state, broker, trade_date, logger)
    if has_positions:
        return True

    if state.get("last_lockdown_check_date") == trade_date:
        logger.info("空仓保护计时今日已处理，跳过重复递减")
        return True

    state["last_lockdown_check_date"] = trade_date
    state["lockdown_days_left"] = int(state.get("lockdown_days_left", 0)) - 1
    if state["lockdown_days_left"] <= 0:
        asset = broker.query_asset()
        total_asset = float(getattr(asset, "total_asset", 0) or 0) if asset else 0
        state["in_lockdown"] = False
        state["watermark"] = total_asset or state.get("watermark")
        logger.info("空仓保护结束")
    else:
        logger.info("空仓保护剩余 %s 天", state["lockdown_days_left"])
    # Lockdown timer updates are critical and should be persisted immediately.
    save_state(state, logger, trade_date=trade_date)
    return True


def sync_and_archive_orders(state, broker, logger):
    broker.sync_orders()
    broker.archive_final_orders()
    broker.cancel_stale_orders()


def execute_pending_orders(state, broker, trade_date, logger):
    # 补单本身不做日期门禁，由外层 maybe_execute... 控制执行时机
    pending = state.get("pending_orders", {})
    if not pending:
        return

    asset = broker.query_asset()
    if asset is None:
        logger.warning("无法获取资金，跳过补单")
        return

    cash = float(getattr(asset, "cash", 0) or getattr(asset, "m_dCash", 0) or 0)
    expired = []

    for stock, order in list(pending.items()):
        if stock not in state.get("target_etfs", []):
            expired.append(stock)
            continue
        if broker.has_active_order(stock, "buy")[0]:
            logger.info("已有买入活跃委托，跳过补单: %s", stock)
            continue

        price = broker.get_latest_price(stock)
        shares = int(order.get("shares", 0) or 0)
        shares = int(shares / 100) * 100
        if price <= 0 or shares < 100:
            expired.append(stock)
            continue

        max_shares = int(cash * 0.98 / price / 100) * 100
        buy_shares = min(shares, max_shares)
        if buy_shares < 100:
            order["days"] = int(order.get("days", 0)) + 1
            if order["days"] > 5:
                expired.append(stock)
            continue

        remark = "补单完成" if buy_shares == shares else "补单部分"
        order_id = broker.order("buy", stock, buy_shares, remark)
        if order_id:
            cash -= buy_shares * price * 1.02
            order["attempt_count"] = int(order.get("attempt_count", 0)) + 1
            order["last_order_id"] = str(order_id)
            order["last_attempt_time"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            order["shares"] = shares - buy_shares
            if order["shares"] < 100:
                expired.append(stock)

    for stock in expired:
        pending.pop(stock, None)


def maybe_execute_pending_orders_once_per_day(state, broker, trade_date, logger):
    # 每天最多尝试一次补单，且仅允许在交易日+交易时段触发
    if state.get("last_pending_process_date") == trade_date:
        return
    if not is_trading_day(broker, trade_date):
        return
    if not is_trading_session_time():
        return
    state["last_pending_process_date"] = trade_date
    execute_pending_orders(state, broker, trade_date, logger)


def set_pending(state, stock, shares, reason, trade_date, order_id=None):
    # 统一登记待补单，保证股数按 100 股取整并记录追踪字段
    shares = int(shares / 100) * 100
    if shares < 100:
        return
    pending = state.setdefault("pending_orders", {})
    if stock not in pending:
        pending[stock] = {
            "shares": shares,
            "days": 0,
            "reason": reason,
            "source_rebalance_date": trade_date,
            "last_order_id": str(order_id) if order_id else "",
            "attempt_count": 0,
        }
    else:
        pending[stock]["shares"] = int(pending[stock].get("shares", 0)) + shares
        pending[stock]["reason"] = reason
        if order_id:
            pending[stock]["last_order_id"] = str(order_id)


def execute_rebalance(state, broker, targets, weights, pos_scale, trade_date, logger):
    # 调仓原则：先卖后买；买入只使用“实时可用资金”，不预支卖出回款
    asset = broker.query_asset()
    if asset is None:
        logger.error("无法获取资产，调仓中止")
        return False

    total_asset = float(getattr(asset, "total_asset", 0) or getattr(asset, "m_dTotalAsset", 0) or 0)
    cash = float(getattr(asset, "cash", 0) or getattr(asset, "m_dCash", 0) or 0)
    if total_asset <= 0:
        logger.error("账户资产无效，调仓中止")
        return False

    positions = broker.positions_dict()
    target_set = set(targets)
    scaled_asset = total_asset * pos_scale

    logger.info("目标持仓: %s", dict(zip(targets, weights)))
    logger.info("仓位缩放: %.4f, 总资产: %.2f, 可用资金: %.2f", pos_scale, total_asset, cash)

    for stock, pos in list(positions.items()):
        shares = int(pos.get("shares", 0) / 100) * 100
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
        target_value = scaled_asset * weights[idx]
        target_shares = int(target_value / price / 100) * 100
        delta = target_shares - shares
        if delta <= -100 and not broker.has_active_order(stock, "sell")[0]:
            broker.order("sell", stock, abs(delta), "调仓卖出")

    sync_and_archive_orders(state, broker, logger)
    asset = broker.query_asset()
    cash = float(getattr(asset, "cash", 0) or getattr(asset, "m_dCash", 0) or 0) if asset else 0

    for stock, weight in zip(targets, weights):
        if broker.has_active_order(stock, "buy")[0]:
            continue

        price = broker.get_latest_price(stock)
        if price <= 0:
            continue

        current_shares = int(positions.get(stock, {}).get("shares", 0))
        target_value = scaled_asset * weight
        if target_value < MIN_TRADE_VALUE:
            continue

        target_shares = int(target_value / price / 100) * 100
        delta = target_shares - current_shares
        if delta < 100:
            continue

        max_affordable = int(cash * 0.98 / price / 100) * 100
        buy_shares = min(delta, max_affordable)
        submitted = 0
        if buy_shares >= 100:
            order_id = broker.order("buy", stock, buy_shares, "调仓买入" if buy_shares == delta else "调仓部分买入")
            if order_id:
                submitted = buy_shares
                cash -= buy_shares * price * 1.02

        remaining = delta - submitted
        if remaining >= 100:
            set_pending(state, stock, remaining, "cash_limited_or_unsubmitted", trade_date)

    state["target_etfs"] = targets
    state["target_weights"] = weights
    state["pos_scale"] = pos_scale
    state["last_rebalance_date"] = trade_date
    state["last_window_process_date"] = trade_date
    return True


def process_rebalance_window(state, broker, trade_date, logger):
    # 窗口内每个交易日只处理一次，避免重复调仓
    if state.get("last_rebalance_date") == trade_date:
        return
    if state.get("last_window_process_date") == trade_date:
        return

    if state.get("cooling_period_left", 0) > 0:
        state["cooling_period_left"] = int(state.get("cooling_period_left", 0)) - 1
        state["last_window_process_date"] = trade_date
        logger.info("冷却期剩余 %s 天", state["cooling_period_left"])
        return

    if int(state.get("trade_day_counter", 0)) % REBALANCE_FREQ != 0:
        state["last_window_process_date"] = trade_date
        logger.info("非调仓周期，今日跳过调仓")
        return

    logger.info("进入调仓窗口")
    pos_scale = calculate_position_scale(broker, trade_date, logger)
    targets, weights = compute_targets(broker, trade_date, state, logger)
    if not targets:
        logger.warning("目标为空，跳过调仓")
        return

    state["pending_orders"] = {}
    ok = execute_rebalance(state, broker, targets, weights, pos_scale, trade_date, logger)
    if ok:
        logger.info("调仓完成")
    else:
        logger.warning("调仓未完成，将允许后续窗口重试")


def main():
    logger = setup_logger()
    logger.info("策略程序启动")

    state = load_state(logger)
    broker = QmtBroker(logger, state)
    last_heartbeat_time = 0

    try:
        broker.connect()
        logger.info("miniQMT 连接成功")
        broker.print_account_snapshot()
        startup_trade_date = today_str()
        log_startup_strategy_snapshot(state, broker, startup_trade_date, logger)
        if save_state_if_trading_day(state, broker, startup_trade_date, logger, quiet=False):
            logger.info("[%s] 交易时段内，状态文件已写入", startup_trade_date)
        else:
            logger.info("[%s] 非交易时段或非交易日，跳过状态文件写入", startup_trade_date)

        logger.info("进入主循环")
        while True:
            try:
                trade_date = today_str()
                now = time.time()
                log_trading_day_status_once_per_day(state, broker, trade_date, logger)

                sync_and_archive_orders(state, broker, logger)

                total_asset = update_risk_baseline(state, broker, trade_date, logger)
                if total_asset is None:
                    time.sleep(LOOP_INTERVAL_SECONDS)
                    continue

                if not check_global_risk(state, broker, trade_date, total_asset, logger):
                    # Risk-triggered state changes are critical; persist immediately.
                    save_state(state, logger, trade_date=trade_date)
                    time.sleep(LOOP_INTERVAL_SECONDS)
                    continue

                if state.get("in_lockdown"):
                    process_lockdown(state, broker, trade_date, logger)
                    save_state_if_trading_day(state, broker, trade_date, logger)
                    time.sleep(LOOP_INTERVAL_SECONDS)
                    continue

                if update_day_counter(state, broker, trade_date):
                    logger.info("[%s] 交易日计数递增: trade_day_counter=%s", trade_date, state.get("trade_day_counter", 0))
                else:
                    is_trade_day, source = get_trading_day_status(broker, trade_date)
                    if is_trade_day and source == "fallback_conservative":
                        logger.warning(
                            "[%s] 交易日计数被保护性跳过: source=%s。请人工确认交易日历/xtdata状态。",
                            trade_date,
                            source,
                        )

                maybe_execute_pending_orders_once_per_day(state, broker, trade_date, logger)

                if is_rebalance_window(broker, trade_date):
                    process_rebalance_window(state, broker, trade_date, logger)

                if now - last_heartbeat_time >= HEARTBEAT_INTERVAL_SECONDS:
                    logger.info("心跳: 策略运行正常")
                    broker.print_account_snapshot()
                    last_heartbeat_time = now

                save_state_if_trading_day(state, broker, trade_date, logger)
                time.sleep(LOOP_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                logger.info("收到手动停止信号")
                break
            except Exception as e:
                logger.error("主循环异常: %s", e)
                logger.error(traceback.format_exc())
                time.sleep(LOOP_INTERVAL_SECONDS)

    except Exception as e:
        logger.error("策略启动失败: %s", e)
        logger.error(traceback.format_exc())
    finally:
        try:
            shutdown_trade_date = today_str()
            if save_state_if_trading_day(state, broker, shutdown_trade_date, logger):
                logger.info("[%s] 交易时段内，退出前状态文件已写入", shutdown_trade_date)
            else:
                logger.info("[%s] 非交易时段或非交易日，退出前跳过状态文件写入", shutdown_trade_date)
        except Exception:
            logger.error("退出前保存状态失败")
            logger.error(traceback.format_exc())
        broker.stop()
        logger.info("策略程序退出")


if __name__ == "__main__":
    main()
