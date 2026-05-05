# -*- coding: utf-8 -*-
# 稳健版 ETF 趋势轮动策略 v4.6 标准实盘版（时区修复+日志完善）
import numpy as np
import pandas as pd
import datetime
import json
import os
import glob

def init(C):
    # ========== 标的池 ==========
    C.equity_etfs = [
        '510300.SH',   # 沪深300ETF
        '159915.SZ',   # 创业板ETF
        '513100.SH',   # 纳指ETF
        '518880.SH',   # 黄金ETF
        '159985.SZ',   # 豆粕ETF
        '159388.SZ'    # 人工智能ETF
    ]
    C.defense_etfs = [
        '512890.SH',   # 红利低波ETF
        '511010.SH'    # 国债ETF
    ]
    C.all_etfs = C.equity_etfs + C.defense_etfs

    # ========== 核心参数 ==========
    C.momentum_window_short = 16      # 短期动量窗口
    C.momentum_window_long  = 19      # 长期动量窗口
    C.ma_window = 70                  # 均线过滤窗口
    C.rebalance_freq = 19             # 调仓频率（交易日）
    C.min_holdings = 2                # 最少持有ETF数量

    # ========== 风控参数 ==========
    C.drawdown_limit = 0.20           # 回撤止损阈值 20%
    C.watermark = None                # 账户历史最高净值
    C.in_lockdown = False             # 是否处于空仓保护期
    C.lockdown_days_left = 0          # 空仓保护剩余天数
    C.lockdown_length = 10            # 空仓保护总天数
    C.cooling_period_left = 0         # 急跌冷却剩余天数
    C.cooling_length = 6              # 冷却期总天数
    C.vol_lookback = 20               # 波动率计算窗口
    C.vol_threshold = 0.34            # 波动率阈值
    C.pos_scale = 1.0                 # 仓位缩放系数

    C.last_equity = None              # 上次总资产（用于资产异常熔断）
    C.last_cash = None                # 上次可用资金（用于缓存恢复）
    C.last_prices = {}                # 缓存最新价格
    C.target_etfs = []                # 目标持仓ETF列表
    C.target_weights = []             # 对应权重
    C.trade_day_counter = 0           # 交易日计数器
    C.pending_orders = {}             # 待补单字典 {etf: {"shares": 股数, "days": 挂单天数}}
    C.last_trade_date = ""            # 用于每日计数去重
    C.last_rebalance_date = ""        # 用于防止调仓重复触发
    C.day_start_equity = None           # 当日风控基准资产
    C.risk_check_date = ""              # 当日风控基准日期
    C.rebalance_window_minutes = 6      # 14:50 后允许触发的分钟窗口

    # ========== 工程防护 ==========
    C.order_lock = False              # 防重复下单锁
    C.order_lock_time = None          # 锁时间
    C.order_book = {}                 # 订单簿
    C.trade_log = []                  # 成交记录

    # ========== 交易账户设置 ==========
    C.account = '2064890'             # 请替换为实盘/模拟账号
    C.acct_type = 'stock'
    C.buy_code = 23
    C.sell_code = 24

    C.set_slippage(0.002)             # 千分之二滑点
    C.set_commission(0, [0, 0, 0.00012, 0.00012, 0, 0])

    # ========== 状态持久化目录 ==========
    C.state_dir = r"D:\qmt\testdata"
    if not os.path.exists(C.state_dir):
        try:
            os.makedirs(C.state_dir)
        except:
            pass

    # 加载本地持久化状态
    load_state(C)

    print('=== 稳健版ETF轮动 v4.6 最终融合修复版 初始化完成 ===')


# ==================== 交易日判断 ====================
def is_trading_time(C):
    """判断当前系统时间是否在交易时段内"""
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        return False
    morning_start = now.replace(hour=9, minute=30, second=0, microsecond=0)
    morning_end = now.replace(hour=11, minute=30, second=0, microsecond=0)
    afternoon_start = now.replace(hour=13, minute=0, second=0, microsecond=0)
    afternoon_end = now.replace(hour=15, minute=0, second=0, microsecond=0)
    return (morning_start <= now <= morning_end) or (afternoon_start <= now <= afternoon_end)


# ==================== 状态持久化 ====================
def load_state(C):
    """从本地 JSON 文件中安全恢复状态"""
    pattern = os.path.join(C.state_dir, "strategy_state_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        print('[持久化] 未找到历史状态文件，使用默认初始值')
        return
    latest_file = files[0]
    print('[持久化] 从最新文件恢复状态:', os.path.basename(latest_file))
    try:
        with open(latest_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
        C.watermark = state.get('watermark', None)
        C.last_equity = state.get('last_equity', None)
        C.last_cash = state.get('last_cash', None)
        C.in_lockdown = state.get('in_lockdown', False)
        C.lockdown_days_left = state.get('lockdown_days_left', 0)
        C.cooling_period_left = state.get('cooling_period_left', 0)
        C.trade_day_counter = state.get('trade_day_counter', 0)
        C.last_trade_date = state.get('last_trade_date', '')
        C.last_rebalance_date = state.get('last_rebalance_date', '')
        C.day_start_equity = state.get('day_start_equity', None)
        C.risk_check_date = state.get('risk_check_date', '')
        C.pos_scale = state.get('pos_scale', 1.0)
        C.pending_orders = normalize_pending_orders(state.get('pending_orders', {}))
        C.target_etfs = [normalize_stock_code(x) for x in state.get('target_etfs', [])]
        C.target_weights = state.get('target_weights', [])
        C.last_prices = state.get('last_prices', {})
        C.order_book = state.get('order_book', {})
        C.trade_log = state.get('trade_log', [])
        print('[持久化] 状态恢复成功')
    except Exception as e:
        print('[持久化] 恢复状态失败:', e)


def save_state(C):
    # 回测模式下始终允许保存，使用K线日期而非系统时间
    if getattr(C, 'do_back_test', False):
        current_date_str = get_current_date(C).replace('-', '')
    else:
        if not is_trading_time(C):
            return
        current_date_str = datetime.datetime.now().strftime('%Y%m%d')

    filename = f"strategy_state_{current_date_str}.json"
    filepath = os.path.join(C.state_dir, filename)
    state = {
        'watermark': C.watermark,
        'last_equity': C.last_equity,
        'last_cash': C.last_cash,
        'in_lockdown': C.in_lockdown,
        'lockdown_days_left': C.lockdown_days_left,
        'cooling_period_left': C.cooling_period_left,
        'trade_day_counter': C.trade_day_counter,
        'last_trade_date': C.last_trade_date,
        'last_rebalance_date': C.last_rebalance_date,
        'day_start_equity': C.day_start_equity,
        'risk_check_date': C.risk_check_date,
        'pos_scale': C.pos_scale,
        'pending_orders': C.pending_orders,
        'target_etfs': C.target_etfs,
        'target_weights': C.target_weights,
        'last_prices': C.last_prices,
        'order_book': C.order_book,
        'trade_log': C.trade_log
    }
    try:
        tmp = filepath + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, filepath)
    except Exception as e:
        print('[持久化] 保存状态失败:', e)


# ==================== 行情与账户函数 ====================
def get_current_date(C):
    """获取K线对应的日期字符串（北京时间）"""
    try:
        ts = C.get_bar_timetag(C.barpos)
        # 修复：强制转换为北京时间 (UTC+8)，避免服务器时区不一致
        dt = datetime.datetime.utcfromtimestamp(ts / 1000) + datetime.timedelta(hours=8)
        return dt.strftime('%Y-%m-%d')
    except:
        return datetime.datetime.now().strftime('%Y-%m-%d')


def normalize_stock_code(stock, exchange=None):
    """标准化 QMT 返回的证券代码，避免 SH/SSE/SHSE 等格式不一致。"""
    if stock is None:
        return ""
    code = str(stock).strip().upper()
    exch = str(exchange).strip().upper() if exchange is not None else ""

    if "." in code:
        base, suffix = code.split(".", 1)
        code = base
        if not exch:
            exch = suffix

    exchange_map = {
        "SH": "SH", "SSE": "SH", "SHSE": "SH", "XSHG": "SH",
        "SZ": "SZ", "SZSE": "SZ", "XSHE": "SZ",
    }
    if exch in exchange_map:
        return code + "." + exchange_map[exch]
    if code.startswith(("5", "6", "9")):
        return code + ".SH"
    if code.startswith(("0", "1", "2", "3")):
        return code + ".SZ"
    return code


def normalize_pending_orders(pending_orders):
    """恢复状态时同步规范化补单字典的证券代码。"""
    normalized = {}
    if not isinstance(pending_orders, dict):
        return normalized
    for etf, order in pending_orders.items():
        code = normalize_stock_code(etf)
        if code:
            normalized[code] = order
    return normalized


def in_rebalance_window(C):
    """实盘使用 14:50 后的短窗口触发，避免精确分钟错过调仓。"""
    now = datetime.datetime.now()
    start = now.replace(hour=14, minute=50, second=0, microsecond=0)
    minutes = getattr(C, 'rebalance_window_minutes', 6)
    end = start + datetime.timedelta(minutes=minutes)
    return start <= now < end


def get_current_price(C, stock):
    """获取标的最新收盘价"""
    try:
        data = C.get_market_data_ex(['close'], [stock], period='1d', count=1)
        if data and stock in data:
            arr = data[stock].values if hasattr(data[stock], 'values') else data[stock]
            if len(arr) > 0:
                price = arr[-1]
                if price is not None and not np.isnan(price) and 0 < price < 1e6:
                    return float(price)
    except:
        pass
    return 0


def get_positions(C):
    """获取当前真实持仓字典"""
    try:
        pos_list = get_trade_detail_data(C.account, C.acct_type, 'position')
    except Exception as e:
        print('[错误] 获取持仓失败:', e)
        return {}

    d = {}
    if pos_list:
        for pos in pos_list:
            try:
                if pos.m_nVolume > 0:
                    code = normalize_stock_code(pos.m_strInstrumentID, pos.m_strExchangeID)
                    price = pos.m_dLastPrice
                    if price is None or price <= 0:
                        continue
                    d[code] = {
                        "value": price * pos.m_nVolume,
                        "shares": pos.m_nVolume
                    }
            except:
                continue
    return d


def get_available_cash(C):
    """获取账户可用资金"""
    try:
        acc = get_trade_detail_data(C.account, C.acct_type, 'account')
        if not acc:
            return getattr(C, 'last_cash', 0)
        cash = acc[0].m_dAvailable
        if cash is None or np.isnan(cash) or cash < 0:
            return getattr(C, 'last_cash', 0)
        C.last_cash = cash
        return cash
    except:
        return getattr(C, 'last_cash', 0)


def get_total_value(C):
    """获取账户总资产"""
    try:
        acc = get_trade_detail_data(C.account, C.acct_type, 'account')
        if not acc:
            return getattr(C, 'last_equity', 0)
        val = acc[0].m_dBalance
        if val is None or np.isnan(val) or val <= 0 or val > 1e9:
            return getattr(C, 'last_equity', 0)
        C.last_equity = val
        return val
    except:
        return getattr(C, 'last_equity', 0)


# ==================== 统一下单入口 ====================
def get_obj_attr(obj, names, default=None):
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def normalize_order_status(raw_status, filled, total):
    status_map = {
        48: "pending",
        49: "pending",
        50: "submitted",
        51: "canceling",
        52: "partial_canceling",
        53: "partial_canceled",
        54: "canceled",
        55: "partial_filled",
        56: "filled",
        57: "rejected",
    }
    try:
        raw_int = int(raw_status)
        status = status_map.get(raw_int, str(raw_status))
    except:
        status = str(raw_status).lower() if raw_status is not None else "unknown"

    try:
        filled_num = int(filled or 0)
        total_num = int(total or 0)
    except:
        filled_num, total_num = 0, 0

    if total_num > 0 and filled_num >= total_num:
        return "filled"
    if filled_num > 0 and status in ("submitted", "pending", "unknown"):
        return "partial_filled"
    return status


def sync_order_book(C):
    """尽量同步 QMT 委托状态，避免把提交委托误认为已成交。"""
    try:
        orders = get_trade_detail_data(C.account, C.acct_type, 'order')
    except Exception as e:
        print('[订单同步] 获取委托失败:', e)
        return
    if not orders or not getattr(C, 'order_book', None):
        return

    for order in orders:
        try:
            ids = set()
            for attr in ['m_strOrderSysID', 'm_strOrderID', 'm_strOrderRef', 'm_strOrderLocalID']:
                value = get_obj_attr(order, [attr], None)
                if value not in (None, ''):
                    ids.add(str(value))

            code = normalize_stock_code(
                get_obj_attr(order, ['m_strInstrumentID', 'm_strStockCode'], ''),
                get_obj_attr(order, ['m_strExchangeID', 'm_strExchange'], '')
            )
            filled = get_obj_attr(order, ['m_nVolumeTraded', 'm_nTradedVolume', 'm_nVolumeTrade'], 0)
            total = get_obj_attr(order, ['m_nVolumeTotalOriginal', 'm_nOrderVolume', 'm_nVolumeTotal'], 0)
            raw_status = get_obj_attr(order, ['m_nOrderStatus', 'm_strOrderStatus', 'm_nStatus'], None)
            status = normalize_order_status(raw_status, filled, total)

            for order_id, record in list(C.order_book.items()):
                if str(order_id) in ids:
                    record['filled'] = int(filled or 0)
                    record['status'] = status
                    record['last_sync_time'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            print('[订单同步] 解析委托失败:', e)


def safe_order(C, side, etf, volume, remark):
    """执行交易指令并登记到订单簿中"""
    etf = normalize_stock_code(etf)
    volume = int(volume / 100) * 100
    if volume < 100:
        return None
    try:
        order_id = passorder(
            C.buy_code if side == 'buy' else C.sell_code,
            1101, C.account, etf, 14, -1.0, volume,
            remark, 2, remark, C
        )
        if order_id:
            # 订单 ID 强制转为 str，杜绝 JSON 序列化键值类型冲突
            C.order_book[str(order_id)] = {
                "etf": etf,
                "side": side,
                "volume": volume,
                "filled": 0,
                "status": "submitted",
                "remark": remark,
                "time": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        else:
            print('[下单失败] 未返回订单号:', etf, side, volume, remark)
        return order_id
    except Exception as e:
        print("[下单失败]", e)
        return None


# ==================== 选股计算 ====================
def compute_targets(C, current_date):
    """计算当前周期的最佳持仓目标"""
    needed = C.ma_window + max(C.momentum_window_short, C.momentum_window_long) + 2
    data = C.get_market_data_ex(['close'], C.all_etfs, period='1d',
                                count=needed, end_time=current_date.replace('-', ''))
    if data is None or len(data) == 0:
        print('[%s] [错误] 无法获取行情数据' % current_date)
        return [], []

    returns = {}
    valid_count = 0
    for etf in C.all_etfs:
        if etf not in data:
            continue
        raw = data[etf].values if hasattr(data[etf], 'values') else np.array(data[etf])
        close = []
        for x in raw:
            try:
                v = float(x)
                if not np.isnan(v) and v > 0:
                    close.append(v)
            except:
                continue
        if len(close) < needed:
            continue
        valid_count += 1
        close = np.array(close)
        ma = np.mean(close[-C.ma_window:])
        current_price = close[-1]
        C.last_prices[etf] = current_price

        # 双周期平均动量
        ref_short = close[-C.momentum_window_short - 1]
        ref_long  = close[-C.momentum_window_long - 1]
        mom_short = (current_price / ref_short - 1) if ref_short != 0 else 0
        mom_long  = (current_price / ref_long - 1) if ref_long != 0 else 0
        momentum = (mom_short + mom_long) / 2.0

        # 权益标的 均线择时过滤
        if etf in C.equity_etfs and current_price < ma:
            returns[etf] = -999
        else:
            returns[etf] = momentum

    if valid_count == 0:
        return [], []

    ser = pd.Series(returns).sort_values(ascending=False)
    print('[%s] 动量评分: %s' % (current_date, ser.head(3).to_dict()))

    positive = ser[ser > 0]
    if positive.empty:
        print('[%s] [无正向动量] 全配避险国债' % current_date)
        return ['511010.SH'], [1.0]

    selected = positive.head(C.min_holdings)
    total_mom = float(selected.sum())
    if total_mom <= 0:
        print('[%s] [权重异常] 全配避险国债' % current_date)
        return ['511010.SH'], [1.0]

    target_etfs = selected.index.tolist()
    target_weights = [float(m / total_mom) for m in selected.values]
    return target_etfs, target_weights


# ==================== 交易主执行 ====================
def execute_trades(C, current_date):
    """执行调仓动作，并以真实账户现金为准登记补单。"""
    now = datetime.datetime.now()
    if C.order_lock and C.order_lock_time:
        if (now - C.order_lock_time).seconds < 5:
            return
    C.order_lock = True
    C.order_lock_time = now

    try:
        sync_order_book(C)
        positions = get_positions(C)
        target_set = set(C.target_etfs)
        total_value = get_total_value(C) * C.pos_scale

        print('[%s] 正在执行调仓指令提交...' % current_date)
        traded_today = set()

        # 1. 先提交卖单，但不预支未确认成交的卖出资金。
        for etf, pos in list(positions.items()):
            price = get_current_price(C, etf)
            if price <= 0:
                continue
            vol = int(pos["shares"] / 100) * 100
            if vol < 100:
                continue

            if etf not in target_set:
                print('[%s] 卖出非目标: %s, %d 股' % (current_date, etf, vol))
                safe_order(C, 'sell', etf, vol, '清仓非目标')
                traded_today.add(etf)
                continue

            try:
                idx = C.target_etfs.index(etf)
                target_value = total_value * C.target_weights[idx]
                target_shares = int(target_value / price / 100) * 100
                delta = target_shares - pos["shares"]
                if delta < -99:
                    sell_vol = int(abs(delta) / 100) * 100
                    print('[%s] 卖出减仓: %s, %d 股' % (current_date, etf, sell_vol))
                    safe_order(C, 'sell', etf, sell_vol, '调仓卖出')
                    traded_today.add(etf)
            except Exception as e:
                print('[%s] [减仓计算失败] %s: %s' % (current_date, etf, e))

        sync_order_book(C)
        available_cash = get_available_cash(C)

        # 2. 买入目标时只使用账户真实可用资金，未成交卖单产生的资金进入后续补单。
        for i, etf in enumerate(C.target_etfs):
            if etf in traded_today and etf not in positions:
                continue

            target_value = total_value * C.target_weights[i]
            if target_value < 500:
                continue
            price = C.last_prices.get(etf, 0)
            if price <= 0:
                price = get_current_price(C, etf)
            if price <= 0:
                continue

            current_shares = positions.get(etf, {}).get("shares", 0)
            target_shares = int(target_value / price / 100) * 100
            delta = target_shares - current_shares
            if delta < 100:
                continue

            max_affordable = int(available_cash * 0.98 / price / 100) * 100
            buy_vol = min(delta, max_affordable)
            submitted_buy = 0
            if buy_vol >= 100:
                remark = '调仓买入' if buy_vol == delta else '调仓部分买入'
                print('[%s] 买入建仓: %s, %d 股' % (current_date, etf, buy_vol))
                order_id = safe_order(C, 'buy', etf, buy_vol, remark)
                if order_id:
                    submitted_buy = buy_vol
                    available_cash -= buy_vol * price * 1.02

            remaining = delta - submitted_buy
            if remaining >= 100:
                if etf in C.pending_orders:
                    C.pending_orders[etf]["shares"] += remaining
                else:
                    C.pending_orders[etf] = {"shares": remaining, "days": 0}
                print('[%s] 登记补单: %s 缺额 %d 股' % (current_date, etf, remaining))

        sync_order_book(C)
        C.last_cash = get_available_cash(C)

    finally:
        C.order_lock = False


# ==================== 补单执行 ====================
def execute_pending_orders(C, current_date):
    """每日开盘尝试处理遗留未成交补单"""
    if not C.pending_orders:
        return

    print('[%s] [补单] 检查未成交补单...' % current_date)
    available_cash = get_available_cash(C)
    expired = []

    for etf, order in list(C.pending_orders.items()):
        # 移除非目标
        if etf not in getattr(C, 'target_etfs', []):
            expired.append(etf)
            continue

        price = get_current_price(C, etf)
        if price <= 0:
            continue

        need_shares = order.get("shares", 0)
        if need_shares <= 0:
            expired.append(etf)
            continue

        cost = need_shares * price * 1.02
        if available_cash >= cost:
            print('[%s] [补单] 满足条件，补全剩余 %s, %d 股' % (current_date, etf, need_shares))
            order_id = safe_order(C, 'buy', etf, need_shares, '补单完成')
            if order_id:
                available_cash -= cost
                expired.append(etf)
        else:
            max_shares = int(available_cash * 0.98 / price / 100) * 100
            if max_shares >= 100:
                print('[%s] [补单] 资金不足，先补 %d 股' % (current_date, etf, max_shares))
                order_id = safe_order(C, 'buy', etf, max_shares, '补单部分')
                if order_id:
                    available_cash -= (max_shares * price * 1.02)
                    order["shares"] -= max_shares

                order["days"] = order.get("days", 0) + 1
                if order["days"] > 5:
                    print('[%s] [补单] %s 挂单超时废弃' % (current_date, etf))
                    expired.append(etf)

    # 统一清理过期和已完成的补单
    for etf in expired:
        C.pending_orders.pop(etf, None)

    # 同步更新资金缓存
    C.last_cash = available_cash
    save_state(C)


# ==================== 风控执行 ====================
def trigger_lockdown(C, current_date):
    """触发账户全局空仓保护"""
    positions = get_positions(C)
    print('[%s] [风控触发] 正在清空持仓进入空仓期' % current_date)
    for etf, pos in positions.items():
        price = get_current_price(C, etf)
        if price > 0:
            vol = int(pos["shares"] / 100) * 100
            if vol >= 100:
                safe_order(C, 'sell', etf, vol, '空仓保护')
    C.in_lockdown = True
    C.lockdown_days_left = C.lockdown_length
    C.pending_orders = {}


def calculate_position_scale(C, current_date):
    """根据标的指数波动率调节组合仓位"""
    data = C.get_market_data_ex(['close'], ['159915.SZ'], period='1d',
                                count=C.vol_lookback + 5, end_time=current_date.replace('-', ''))
    if data is None or '159915.SZ' not in data:
        return 1.0
    raw = data['159915.SZ'].values if hasattr(data['159915.SZ'], 'values') else data['159915.SZ']
    close = []
    for x in raw:
        try:
            v = float(x)
            if not np.isnan(v) and v > 0:
                close.append(v)
        except:
            continue
    if len(close) < C.vol_lookback + 2:
        return 1.0
    close = np.array(close[-(C.vol_lookback + 2):])
    daily_ret = (close[1:] - close[:-1]) / close[:-1]
    vol = np.std(daily_ret) * np.sqrt(252)
    if vol > C.vol_threshold:
        scale = C.vol_threshold / vol
        print('[%s] [波动率高企] 创业板年化 %.2f%%，仓位压降至 %.2f' % (current_date, vol * 100, scale))
        return scale
    return 1.0


# ==================== 主入口函数 ====================
def handlebar(C):
    current_date = get_current_date(C)
    is_backtest = getattr(C, 'do_back_test', False)

    sync_order_book(C)

    # 1. 每日资产熔断和账户最大回撤检查，每个交易日都执行。
    now_val = get_total_value(C)
    if getattr(C, 'risk_check_date', '') != current_date:
        C.risk_check_date = current_date
        C.day_start_equity = now_val if now_val and now_val > 0 else None
    elif getattr(C, 'day_start_equity', None) is None and now_val and now_val > 0:
        C.day_start_equity = now_val

    day_start_equity = getattr(C, 'day_start_equity', None)
    if day_start_equity and now_val and now_val > 0:
        if now_val < day_start_equity * 0.85:
            print('[%s] [熔断] 当日资产回撤超15%%，停止交易' % current_date)
            save_state(C)
            return

    if now_val and now_val > 100:
        if C.watermark is None or now_val > C.watermark:
            C.watermark = now_val
        dd = (now_val - C.watermark) / C.watermark if C.watermark else 0
        if dd < -C.drawdown_limit and not C.in_lockdown:
            print('[%s] [风控] 账户回撤 %.2f%% 破线，强制止损' % (current_date, dd * 100))
            trigger_lockdown(C, current_date)
            save_state(C)
            return

    # 2. 每日开盘时段状态更新与补单处理，重启后依赖持久化日期防止重复计数。
    if getattr(C, 'last_trade_date', '') != current_date:
        C.last_trade_date = current_date
        C.trade_day_counter += 1
        if not is_backtest and not C.in_lockdown and C.cooling_period_left <= 0:
            execute_pending_orders(C, current_date)
        save_state(C)

    # 3. 调仓触发条件过滤：实盘使用 14:50 后短窗口，当天只处理一次。
    if not is_backtest:
        if not in_rebalance_window(C):
            return
        if getattr(C, 'last_rebalance_date', '') == current_date:
            return
        C.last_rebalance_date = current_date
    else:
        if getattr(C, 'last_rebalance_date', '') == current_date:
            return
        C.last_rebalance_date = current_date

    # 4. 空仓锁定期检查
    if C.in_lockdown:
        C.lockdown_days_left -= 1
        if C.lockdown_days_left <= 0:
            C.in_lockdown = False
            C.watermark = get_total_value(C)
            print('[%s] [风控] 空仓期结束' % current_date)
        else:
            print('[%s] [风控] 空仓保护剩余 %d 天' % (current_date, C.lockdown_days_left))
        save_state(C)
        return

    # 5. 急跌冷却期检查（修复：添加日志输出）
    if C.cooling_period_left > 0:
        C.cooling_period_left -= 1
        print('[%s] [风控] 冷却期剩余 %d 天' % (current_date, C.cooling_period_left))
        save_state(C)
        return

    # 6. 周期调仓过滤
    if C.trade_day_counter % C.rebalance_freq != 0:
        save_state(C)
        return

    print('[%s] --- 进入周期调仓流程 ---' % current_date)

    # 7. 仓位管理与调仓执行
    C.pos_scale = calculate_position_scale(C, current_date)
    C.target_etfs, C.target_weights = compute_targets(C, current_date)

    if not C.target_etfs:
        save_state(C)
        return

    C.pending_orders = {}  # 调仓日清空上一个周期的挂单缓存
    execute_trades(C, current_date)
    save_state(C)
    print('[%s] --- 周期调仓已完成 ---' % current_date)
