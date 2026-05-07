# -*- coding: utf-8 -*-

import datetime
import logging
import os

from config import LOG_DIR, LOG_LEVEL


class StrategyCoreFilter(logging.Filter):
    CORE_KEYWORDS = (
        "今天是否交易日",
        "持仓数量",
        "资产:",
        "调仓",
        "目标持仓",
        "买入",
        "卖出",
        "补单",
        "风控",
        "回撤",
        "锁仓",
    )

    def filter(self, record):
        if record.levelno >= logging.ERROR:
            return False
        msg = record.getMessage()
        return any(k in msg for k in self.CORE_KEYWORDS)


def setup_logger():
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    today = datetime.datetime.now().strftime("%Y%m%d")
    logger = logging.getLogger("miniqmt_stock_strategy")
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    strategy_handler = logging.FileHandler(
        os.path.join(LOG_DIR, f"strategy_{today}.log"),
        encoding="utf-8",
    )
    strategy_handler.setFormatter(formatter)
    strategy_handler.addFilter(StrategyCoreFilter())
    logger.addHandler(strategy_handler)

    error_handler = logging.FileHandler(
        os.path.join(LOG_DIR, f"errors_{today}.log"),
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    return logger

