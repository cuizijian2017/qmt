# -*- coding: utf-8 -*-

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 按你本机实际路径修改
XTQUANT_PATH = r"D:\迅投极速交易终端 睿智融科版\bin.x64\Lib\site-packages"
QMT_PATH = r"D:\迅投极速交易终端 睿智融科版\userdata_mini"

ACCOUNT_ID = "2064890"
ACCOUNT_TYPE = "STOCK"

STRATEGY_ID = "stock_strategy_v1"
STRATEGY_NAME = "STOCKSTRAT"

STATE_DIR = os.path.join(BASE_DIR, "state")
LOG_DIR = os.path.join(BASE_DIR, "logs")
DATA_DIR = os.path.join(BASE_DIR, "data")

LOOP_INTERVAL_SECONDS = 30
HEARTBEAT_INTERVAL_SECONDS = 300
LOG_LEVEL = "INFO"

# 尾盘调仓窗口
REBALANCE_START = "14:50:00"
REBALANCE_END = "14:56:00"
REBALANCE_WINDOW_START = REBALANCE_START[:5]
REBALANCE_WINDOW_END = REBALANCE_END[:5]

# 通用参数（后续策略可替换）
REBALANCE_FREQ = 19
MIN_TRADE_VALUE = 500
ORDER_TIMEOUT_SECONDS = 90
BUY_SLIPPAGE_BUFFER = 1.02

# 股票池与因子：优先 xtdata 接口；以下为接口不可用时的备用文件
STOCK_POOL_FILE = os.path.join(DATA_DIR, "stock_pool.txt")
FACTOR_FILE_PATTERN = os.path.join(DATA_DIR, "factors_{date}.csv")
# True：接口失败或为空时再读本地文件；False：仅接口（若你强制不要文件回退可改）
USE_DATA_FILE_FALLBACK = True

# 中证500多因子 v8.2（Size增强）参数
INDEX_CODE = "000905.SH"
STOCK_NUM = 40

FACTOR_WEIGHTS = {
    "ep": 0.15,
    "bp": 0.30,
    "roe": 0.20,
    "lowvol": 0.20,
    "size": 0.15,
}

DRAWDOWN_LIMIT = 0.20
PANIC_THRESHOLD = 0.15
LOCKDOWN_LENGTH = 5

ATR_PERIOD = 14
ATR_EXTREME_RATIO = 2.5
ATR_NORMAL_RATIO = 1.8

# 运行模式
SIMULATION_MODE = True  # True=模拟盘(卖出用FIX_PRICE+价格), False=实盘(卖出用LATEST_PRICE+ -1)


