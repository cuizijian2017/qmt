# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd

from config import (
    ATR_EXTREME_RATIO,
    ATR_NORMAL_RATIO,
    ATR_PERIOD,
    DRAWDOWN_LIMIT,
    FACTOR_WEIGHTS,
    INDEX_CODE,
    LOCKDOWN_LENGTH,
    PANIC_THRESHOLD,
    REBALANCE_FREQ,
    STOCK_NUM,
)


def initialize_state(state):
    state.setdefault("hold_days", 0)
    state.setdefault("if_trade", False)
    state.setdefault("in_lockdown", False)
    state.setdefault("lockdown_days_left", 0)
    state.setdefault("in_atr_lockdown", False)
    state.setdefault("watermark", None)
    state.setdefault("target_stocks", [])
    state.setdefault("target_weights", [])


def _pct_change(values):
    if len(values) < 2:
        return np.array([])
    prev = values[:-1]
    curr = values[1:]
    mask = prev != 0
    ret = np.zeros_like(curr, dtype=float)
    ret[mask] = (curr[mask] - prev[mask]) / prev[mask]
    return ret


def check_atr_extreme(broker, trade_date):
    bars = broker.get_index_bars(
        INDEX_CODE,
        count=252 + ATR_PERIOD + 1,
        fields=["close", "high", "low"],
        end_date=trade_date,
    )
    high = bars.get("high", np.array([]))
    low = bars.get("low", np.array([]))
    close = bars.get("close", np.array([]))
    if len(close) < ATR_PERIOD + 2 or len(high) != len(close) or len(low) != len(close):
        return "normal"

    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr1 = high - low
    tr2 = np.abs(high - prev_close)
    tr3 = np.abs(low - prev_close)
    tr = np.maximum(np.maximum(tr1, tr2), tr3)
    atr = pd.Series(tr).rolling(window=ATR_PERIOD).mean().values
    current_atr = atr[-1]
    historical_atr = atr[ATR_PERIOD:-1]
    historical_atr = historical_atr[~np.isnan(historical_atr)]
    if len(historical_atr) < 100:
        return "normal"
    median_atr = np.median(historical_atr)
    if median_atr == 0:
        return "normal"
    ratio = current_atr / median_atr
    if ratio >= ATR_EXTREME_RATIO:
        return "extreme"
    if ratio <= ATR_NORMAL_RATIO:
        return "normal"
    return "gray"


def _index_5d_change(broker, trade_date):
    bars = broker.get_index_bars(INDEX_CODE, count=6, fields=["close"], end_date=trade_date)
    close = bars.get("close", np.array([]))
    if len(close) < 6 or close[0] == 0:
        return None
    return (close[-1] / close[0]) - 1


def before_trading_start(state, broker, trade_date, logger):
    """
    聚宽 before_trading_start 的 miniQMT 对应实现。
    只在每日首次处理时调用，计算当日是否允许调仓及目标持仓。
    """
    state["hold_days"] = int(state.get("hold_days", 0)) + 1
    state["if_trade"] = False

    atr_status = check_atr_extreme(broker, trade_date)
    if atr_status == "extreme":
        if not state.get("in_atr_lockdown", False):
            logger.info("【ATR风控】市场进入极端波动状态，暂停调仓")
            state["in_atr_lockdown"] = True
        return
    if atr_status == "normal" and state.get("in_atr_lockdown", False):
        logger.info("【ATR风控】极端波动结束，恢复正常交易")
        state["in_atr_lockdown"] = False
    if state.get("in_atr_lockdown", False):
        return

    if state.get("in_lockdown", False):
        left = int(state.get("lockdown_days_left", 0)) - 1
        state["lockdown_days_left"] = left
        if left <= 0:
            state["in_lockdown"] = False
            total = broker.get_total_asset()
            state["watermark"] = total if total and total > 0 else state.get("watermark")
            logger.info("【风控】空仓保护期结束，水线重置")
        else:
            logger.info("【风控】空仓保护剩余 %s 天", left)
        return

    total = broker.get_total_asset()
    if total is None or total <= 0:
        logger.warning("资产无效，跳过当日预处理")
        return
    watermark = state.get("watermark")
    if watermark is None or total > float(watermark):
        state["watermark"] = total
        watermark = total
    dd = (total - float(watermark)) / float(watermark) if watermark else 0.0
    if dd < -DRAWDOWN_LIMIT:
        idx_drop = _index_5d_change(broker, trade_date)
        if idx_drop is not None and idx_drop < -PANIC_THRESHOLD:
            logger.info("【风控】回撤 %.2f%%，但指数5日跌幅 %.2f%%，暂不锁仓", dd * 100, idx_drop * 100)
        else:
            state["in_lockdown"] = True
            state["lockdown_days_left"] = LOCKDOWN_LENGTH
            state["if_trade"] = False
            logger.info("【风控】组合回撤 %.2f%%，进入空仓保护 %s 天", dd * 100, LOCKDOWN_LENGTH)
            return

    if int(state.get("hold_days", 0)) % REBALANCE_FREQ != 0:
        return

    stocks = broker.get_index_stocks(INDEX_CODE, trade_date)
    if not stocks:
        logger.warning("指数成分股为空，跳过当日调仓")
        return
    scores = calculate_factors(stocks, broker, trade_date, logger)
    if scores.empty:
        logger.warning("因子评分为空，跳过当日调仓")
        return

    target = scores.nlargest(STOCK_NUM, "score").index.tolist()
    if not target:
        return
    state["target_stocks"] = target
    state["target_weights"] = [1.0 / len(target)] * len(target)
    state["if_trade"] = True
    logger.info("选股完成，目标持仓数：%s", len(target))


def calculate_factors(stocks, broker, trade_date, logger):
    """
    多因子评分框架：
    - 先从 broker 读取因子原始表（后续接入财务/行情数据）
    - 按 v8.2 权重计算 score
    """
    factor_df = broker.get_factor_frame(stocks, trade_date)
    if factor_df is None or factor_df.empty:
        return pd.DataFrame()

    df = factor_df.copy()
    need_cols = ["ep", "bp", "roe", "lowvol", "size"]
    for col in need_cols:
        if col not in df.columns:
            df[col] = np.nan
    df = df.dropna(subset=need_cols)
    if df.empty:
        return df

    for fac in need_cols:
        mean = df[fac].mean()
        std = df[fac].std()
        if std and std > 0:
            df[fac + "_z"] = ((df[fac] - mean) / std).clip(-3, 3)
        else:
            df[fac + "_z"] = 0.0

    w = FACTOR_WEIGHTS
    df["score"] = (
        df["ep_z"] * w["ep"]
        + df["bp_z"] * w["bp"]
        + df["roe_z"] * w["roe"]
        + df["lowvol_z"] * w["lowvol"]
        + df["size_z"] * w["size"]
    )
    logger.info("因子计算后剩余股票数: %s", len(df))
    return df[["score"]]

