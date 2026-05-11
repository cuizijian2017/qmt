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
        "watermark": None,
        "day_start_equity": None,
        "risk_check_date": "",
        "in_lockdown": False,
        "lockdown_days_left": 0,
        "last_lockdown_order_date": "",
        "last_lockdown_check_date": "",

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


def _normalize_date_tag(trade_date=None):
    # 统一状态文件日期标签：YYYYMMDD
    if trade_date:
        text = str(trade_date).strip()
        if len(text) >= 10:
            return text[:10].replace("-", "")
    return datetime.datetime.now().strftime("%Y%m%d")


def build_state_file_path(trade_date=None):
    date_tag = _normalize_date_tag(trade_date)
    filename = f"strategy_state_{date_tag}.json"
    return os.path.join(STATE_DIR, filename)


def _find_latest_state_file():
    # 跨日启动兜底：找最近一个状态文件继续运行
    pattern = os.path.join(STATE_DIR, "strategy_state_*.json")
    files = glob.glob(pattern)
    if not files:
        return ""
    return max(files, key=os.path.getmtime)

def load_state(logger):
    if not os.path.exists(STATE_DIR):
        os.makedirs(STATE_DIR)

    # 优先读取当日状态；若当日不存在，回退到最近状态文件
    state_file = build_state_file_path()
    if not os.path.exists(state_file):
        latest = _find_latest_state_file()
        if latest:
            state_file = latest
            logger.info("今日状态文件不存在，回退加载最近状态: %s", state_file)
        else:
            logger.info("未找到状态文件，使用默认状态")
            return default_state()

    try:
        # 兼容外部脚本（如 bat/powershell）写入带 BOM 的 UTF-8 文件
        # utf-8-sig 同时兼容有/无 BOM，避免 JSONDecodeError: Unexpected UTF-8 BOM
        with open(state_file, "r", encoding="utf-8-sig") as f:
            state = json.load(f)

        if state.get("strategy_id") != STRATEGY_ID:
            logger.warning("状态文件 strategy_id 不匹配，使用默认状态")
            return default_state()

        if str(state.get("account_id")) != str(ACCOUNT_ID):
            logger.warning("状态文件 account_id 不匹配，使用默认状态")
            return default_state()

        logger.info("状态文件加载成功: %s", state_file)
        return merge_defaults(state)
    except Exception as exc:
        logger.exception("状态文件加载失败，使用默认状态: %s", exc)
        return default_state()


def save_state(state, logger, quiet=False, trade_date=None):
    # 原子写入：先写 tmp 再 replace，避免中途失败导致状态文件损坏
    if not os.path.exists(STATE_DIR):
        os.makedirs(STATE_DIR)

    state_file = build_state_file_path(trade_date)
    snapshot = copy.deepcopy(state)
    # 仅剥离运行时计时器；rebalance_phase 与目标持仓保留用于崩溃恢复
    snapshot.pop("sell_phase_start", None)
    snapshot["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    tmp_file = state_file + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, state_file)
        state["updated_at"] = snapshot["updated_at"]
        if not quiet:
            logger.info("状态保存成功: %s", state_file)
    except Exception as exc:
        logger.exception("状态保存失败: %s", exc)
