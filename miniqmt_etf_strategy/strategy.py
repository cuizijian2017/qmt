# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd

from config import (
    ALL_ETFS,
    EQUITY_ETFS,
    MA_WINDOW,
    MIN_HOLDINGS,
    MOMENTUM_WINDOW_LONG,
    MOMENTUM_WINDOW_SHORT,
    VOL_LOOKBACK,
    VOL_THRESHOLD,
)


def extract_close_values(raw):
    # 兼容 xtdata 各类返回结构，提取一维有效收盘价序列
    if raw is None:
        return []
    try:
        values = raw.values if hasattr(raw, "values") else raw
        arr = np.asarray(values, dtype=object).reshape(-1)
    except Exception:
        arr = [raw]

    close = []
    for x in arr:
        try:
            if isinstance(x, (list, tuple, np.ndarray)):
                sub_arr = np.asarray(x, dtype=object).reshape(-1)
                if len(sub_arr) == 0:
                    continue
                x = sub_arr[-1]
            v = float(x)
            if not np.isnan(v) and 0 < v < 1e6:
                close.append(v)
        except Exception:
            continue
    return close


def calculate_position_scale(market_data, current_date=None, logger=None):
    # 基于创业板近期波动率做仓位缩放：波动越高，仓位越低
    if current_date is None:
        current_date = ""
    raw = market_data.get_close_history(["159915.SZ"], VOL_LOOKBACK + 5, current_date).get("159915.SZ")
    close = extract_close_values(raw)
    if len(close) < VOL_LOOKBACK + 2:
        return 1.0

    close = np.array(close[-(VOL_LOOKBACK + 2):])
    daily_ret = (close[1:] - close[:-1]) / close[:-1]
    vol = np.std(daily_ret) * np.sqrt(252)
    if vol > VOL_THRESHOLD:
        scale = VOL_THRESHOLD / vol
        if logger:
            logger.info("[%s] 波动率高企: 创业板年化 %.2f%% 仓位压降至 %.2f", current_date, vol * 100, scale)
        return scale
    return 1.0


def compute_targets(market_data, current_date=None, state=None, logger=None):
    # 选股逻辑：动量排序 + 权益均线过滤 + 正动量归一化配权
    if current_date is None:
        current_date = ""
    if state is None:
        state = {}
    needed = MA_WINDOW + max(MOMENTUM_WINDOW_SHORT, MOMENTUM_WINDOW_LONG) + 2
    data = market_data.get_close_history(ALL_ETFS, needed, current_date)
    if not data:
        if logger:
            logger.error("[%s] 无法获取行情数据", current_date)
        return [], []

    scores = {}
    valid_count = 0

    for etf in ALL_ETFS:
        if etf not in data:
            continue
        close = extract_close_values(data[etf])
        if len(close) < needed:
            continue

        valid_count += 1
        close_arr = np.array(close)
        ma = np.mean(close_arr[-MA_WINDOW:])
        current_price = float(close_arr[-1])
        state.setdefault("last_prices", {})[etf] = current_price

        ref_short = close_arr[-MOMENTUM_WINDOW_SHORT - 1]
        ref_long = close_arr[-MOMENTUM_WINDOW_LONG - 1]
        mom_short = current_price / ref_short - 1 if ref_short else 0
        mom_long = current_price / ref_long - 1 if ref_long else 0
        momentum = (mom_short + mom_long) / 2.0

        if etf in EQUITY_ETFS and current_price < ma:
            scores[etf] = -999
        else:
            scores[etf] = momentum

    if valid_count == 0:
        if logger:
            logger.error("[%s] 没有足够有效行情数据", current_date)
        return [], []

    ser = pd.Series(scores).sort_values(ascending=False)
    if logger:
        logger.info("[%s] 动量评分: %s", current_date, ser.head(3).to_dict())

    positive = ser[ser > 0]
    if positive.empty:
        if logger:
            logger.info("[%s] 无正向动量，全配避险国债", current_date)
        return ["511010.SH"], [1.0]

    selected = positive.head(MIN_HOLDINGS)
    total = float(selected.sum())
    if total <= 0:
        if logger:
            logger.warning("[%s] 权重异常，全配避险国债", current_date)
        return ["511010.SH"], [1.0]

    return selected.index.tolist(), [float(v / total) for v in selected.values]


