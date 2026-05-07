# -*- coding: utf-8 -*-

import copy
import datetime
import glob
import json
import os

from config import ACCOUNT_ID, STATE_DIR, STRATEGY_ID


def default_state():
    return {
        "schema_version": 1,
        "strategy_id": STRATEGY_ID,
        "account_id": ACCOUNT_ID,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": "",
        "trade_day_counter": 0,
        "last_trade_date": "",
        "last_rebalance_date": "",
        "last_window_process_date": "",
        "last_preopen_date": "",
        "if_trade": False,
        "target_stocks": [],
        "target_weights": [],
        "pending_orders": {},
        "order_book": {},
        "watermark": None,
        "day_start_equity": None,
        "risk_check_date": "",
        "hold_days": 0,
        "in_lockdown": False,
        "lockdown_days_left": 0,
        "in_atr_lockdown": False,
    }


def _today_tag(trade_date=None):
    if trade_date:
        return str(trade_date)[:10].replace("-", "")
    return datetime.datetime.now().strftime("%Y%m%d")


def _state_path(trade_date=None):
    return os.path.join(STATE_DIR, f"strategy_state_{_today_tag(trade_date)}.json")


def _latest_state_file():
    files = glob.glob(os.path.join(STATE_DIR, "strategy_state_*.json"))
    return max(files, key=os.path.getmtime) if files else ""


def load_state(logger):
    if not os.path.exists(STATE_DIR):
        os.makedirs(STATE_DIR)

    state_file = _state_path()
    if not os.path.exists(state_file):
        latest = _latest_state_file()
        if latest:
            state_file = latest
            logger.info("今日状态文件不存在，回退加载最近状态: %s", state_file)
        else:
            logger.info("未找到状态文件，使用默认状态")
            return default_state()

    try:
        with open(state_file, "r", encoding="utf-8-sig") as f:
            state = json.load(f)
        merged = default_state()
        merged.update(state or {})
        return merged
    except Exception as exc:
        logger.exception("状态文件加载失败，使用默认状态: %s", exc)
        return default_state()


def save_state(state, logger, quiet=False, trade_date=None):
    if not os.path.exists(STATE_DIR):
        os.makedirs(STATE_DIR)
    state_file = _state_path(trade_date)
    snapshot = copy.deepcopy(state)
    snapshot["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tmp = state_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    os.replace(tmp, state_file)
    if not quiet:
        logger.info("状态保存成功: %s", state_file)

