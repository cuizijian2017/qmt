# -*- coding: utf-8 -*-

import datetime
import logging
import os

from config import LOG_DIR, LOG_LEVEL


class StrategyCoreFilter(logging.Filter):
    """仅保留策略核心观测日志，避免 strategy 日志被系统细节刷屏。"""

    CORE_KEYWORDS = (
        "今天是否交易日",
        "持仓数量",
        "资产:",
        "调仓",
        "目标持仓",
        "动量评分",
        "交易日计数",
        "买入",
        "卖出",
        "补单",
        "风控",
        "回撤",
        "锁仓",
        "冷却期",
        "空仓保护",
    )

    def filter(self, record):
        # ERROR 统一收敛到 errors.log + console.log，不进入 strategy 核心视图
        if record.levelno >= logging.ERROR:
            return False
        message = record.getMessage()
        return any(keyword in message for keyword in self.CORE_KEYWORDS)


def setup_logger():
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    today = datetime.datetime.now().strftime("%Y%m%d")

    logger = logging.getLogger("miniqmt_etf_strategy")
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    console_handler = logging.StreamHandler()
    # 控制台输出：保留全量运行日志，便于实时观察
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler(
        os.path.join(LOG_DIR, f"strategy_{today}.log"),
        encoding="utf-8",
    )
    # strategy 日志：仅保留策略核心日志（交易日判断、资产/持仓、调仓、风控等）
    file_handler.setFormatter(formatter)
    file_handler.addFilter(StrategyCoreFilter())
    logger.addHandler(file_handler)

    error_handler = logging.FileHandler(
        os.path.join(LOG_DIR, f"errors_{today}.log"),
        encoding="utf-8",
    )
    # error 日志：仅保留 ERROR 级别，方便快速定位故障
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    return logger
