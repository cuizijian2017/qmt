# -*- coding: utf-8 -*-

import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 修改为你本机 xtquant 的上级目录，例如:
# r"D:\迅投极速交易终端 睿智融科版\bin.x64\Lib\site-packages"
XTQUANT_PATH = r"D:\迅投极速交易终端 睿智融科版\bin.x64\Lib\site-packages"

# 修改为你本机 userdata_mini 目录
QMT_PATH = r"D:\迅投极速交易终端 睿智融科版\userdata_mini"

# 修改为你的资金账号
ACCOUNT_ID = "2064890"
ACCOUNT_TYPE = "STOCK"

STRATEGY_ID = "etf_rotation_v46"
STRATEGY_NAME = "ETFROT"

STATE_DIR = os.path.join(BASE_DIR, "state")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# 主循环和日志
LOOP_INTERVAL_SECONDS = 30
ACTIVE_ORDER_INTERVAL_SECONDS = 5
HEARTBEAT_INTERVAL_SECONDS = 300
LOG_LEVEL = "INFO"

# 调仓窗口
REBALANCE_START = "14:50:00"
REBALANCE_END = "14:56:00"
REBALANCE_WINDOW_START = REBALANCE_START[:5]
REBALANCE_WINDOW_END = REBALANCE_END[:5]

# 标的池
EQUITY_ETFS = [
    "510300.SH",  # 沪深300ETF
    "159915.SZ",  # 创业板ETF
    "513100.SH",  # 纳指ETF
    "518880.SH",  # 黄金ETF
    "159985.SZ",  # 豆粕ETF
    "159388.SZ",  # 人工智能ETF
]

DEFENSE_ETFS = [
    "512890.SH",  # 红利低波ETF
    "511010.SH",  # 国债ETF
]

ALL_ETFS = EQUITY_ETFS + DEFENSE_ETFS

# 策略参数
MOMENTUM_WINDOW_SHORT = 16
MOMENTUM_WINDOW_LONG = 19
MA_WINDOW = 70
REBALANCE_FREQ = 19
MIN_HOLDINGS = 2

# 风控参数
DRAWDOWN_LIMIT = 0.20
DRAW_DOWN_LIMIT = DRAWDOWN_LIMIT
MAX_INTRADAY_DRAWDOWN = 0.15
LOCKDOWN_LENGTH = 10
LOCKDOWN_DAYS = LOCKDOWN_LENGTH
COOLING_PERIOD_DAYS = 6
VOL_LOOKBACK = 20
VOL_THRESHOLD = 0.34

# 订单参数
ORDER_TIMEOUT_SECONDS = 90
BUY_SLIPPAGE_BUFFER = 1.02
SELL_CASH_BUFFER = 0.998
MIN_TRADE_VALUE = 500

# 运行模式
SIMULATION_MODE = True  # True=模拟盘(卖出用FIX_PRICE+价格), False=实盘(卖出用LATEST_PRICE+ -1)
