# -*- coding: utf-8 -*-
"""测试项目配置：与正式策略分离，按需改路径与账号。"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

XTQUANT_PATH = r"D:\迅投极速交易终端 睿智融科版\bin.x64\Lib\site-packages"
QMT_PATH = r"D:\迅投极速交易终端 睿智融科版\userdata_mini"  # 须与 miniQMT 里「数据目录」一致

# 模拟盘请改为终端里看到的模拟资金账号
ACCOUNT_ID = "2064890"
ACCOUNT_TYPE = "STOCK"

STRATEGY_ID = "trade_api_test"
MIN_ORDER_VOLUME = 100
