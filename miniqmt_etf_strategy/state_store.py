# -*- coding: utf-8 -*-

import copy
import datetime
import json
import os

from config import ACCOUNT_ID, STATE_DIR, STATE_FILE, STRATEGY_ID


def default_state():
    return {
        "schema_version": 1,
        "strategy_id": STRATEGY_ID,
        "account_id": ACCOUNT_ID,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": "",
        "watermark": None,
        "day_start_equity": None,
        "risk_check_date": "",
        "in_lockdown": False,
        "lockdown_days_left": 0,
        "last_lockdown_order_date": "",
        "last_lockdown_check_date": "",
        "cooling_period_left": 0,
        "trade_day_counter": 0,
        "last_trade_date": "",
        "last_rebalance_date": "",
        "last_window_process_date": "",
        "pos_scale": 1.0,
        "target_etfs": [],
        "target_weights": [],
        "last_prices": {},
        "pending_orders": {},
        "order_book": {},
    }


def merge_defaults(state):
    merged = default_state()
    _deep_update(merged, state or {})
    return merged


def _deep_update(base, incoming):
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


def load_state(logger):
    if not os.path.exists(STATE_DIR):
        os.makedirs(STATE_DIR)

    if not os.path.exists(STATE_FILE):
        logger.info("未找到状态文件，使用默认状态")
        return default_state()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        if state.get("strategy_id") != STRATEGY_ID:
            logger.warning("状态文件 strategy_id 不匹配，使用默认状态")
            return default_state()

        if str(state.get("account_id")) != str(ACCOUNT_ID):
            logger.warning("状态文件 account_id 不匹配，使用默认状态")
            return default_state()

        logger.info("状态文件加载成功: %s", STATE_FILE)
        return merge_defaults(state)
    except Exception as exc:
        logger.exception("状态文件加载失败，使用默认状态: %s", exc)
        return default_state()


def save_state(state, logger, quiet=False):
    if not os.path.exists(STATE_DIR):
        os.makedirs(STATE_DIR)

    snapshot = copy.deepcopy(state)
    snapshot["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    tmp_file = STATE_FILE + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, STATE_FILE)
        state["updated_at"] = snapshot["updated_at"]
        if not quiet:
            logger.info("状态保存成功: %s", STATE_FILE)
    except Exception as exc:
        logger.exception("状态保存失败: %s", exc)
