#coding:gbk
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
    C.capital_ratio = 1.0             # 资金使用比例（0~1，1=满仓，随时可改）

    # C.last_equity = None            # 已废弃：只写不读，JSON已清理
    # C.last_cash = None              # 已废弃：只写不读，JSON已清理
    C.last_prices = {}                # 缓存最新价格
    C.target_etfs = []                # 目标持仓ETF列表
    C.target_weights = []             # 对应权重
    C.trade_day_counter = 0           # 交易日计数器
    C.pending_orders = {}             # 待补单字典 {etf: {"shares": 股数, "days": 挂单天数}}
    C.last_trade_date = ""            # 用于每日计数去重
    C.last_rebalance_date = ""        # 用于防止调仓重复触发
    C.last_window_process_date = ""     # 用于窗口内非调仓流程去重
    C.day_start_equity = None           # 当日风控基准资产
    C.risk_check_date = ""              # 当日风控基准日期
    C.last_lockdown_order_date = ""     # 空仓保护清仓委托日期
    C.last_lockdown_check_date = ""     # 空仓保护计时日期
    C.rebalance_window_minutes = 6      # 14:50 后允许触发的分钟窗口

    # ========== 两阶段调仓 ==========
    C.rebalance_phase = None          # None / "selling"
    C.rebalance_targets = []
    C.rebalance_weights = []
    C.sell_phase_start = None

    # ========== 工程防护 ==========
    C.order_lock = False              # 防重复下单锁
    C.order_lock_time = None          # 锁时间
    C.order_book = {}                 # 订单簿
    # C.trade_log = []                # 已废弃：JSON已清理
    C.order_timeout_seconds = 90      # 普通委托超时撤单阈值
    C.log_backtest_orders = False      # 回测下单日志默认关闭，避免刷屏

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

    # 回测使用内存状态，避免读取/覆盖实盘持久化文件
    if getattr(C, 'do_back_test', False):
        print('[持久化] 回测模式跳过本地状态加载')
    else:
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
        C.in_lockdown = state.get('in_lockdown', False)
        C.lockdown_days_left = state.get('lockdown_days_left', 0)
        C.trade_day_counter = state.get('trade_day_counter', 0)
        C.last_trade_date = state.get('last_trade_date', '')
        C.last_rebalance_date = state.get('last_rebalance_date', '')
        C.last_window_process_date = state.get('last_window_process_date', '')
        C.day_start_equity = state.get('day_start_equity', None)
        C.risk_check_date = state.get('risk_check_date', '')
        C.last_lockdown_order_date = state.get('last_lockdown_order_date', '')
        C.last_lockdown_check_date = state.get('last_lockdown_check_date', '')
        C.pos_scale = state.get('pos_scale', 1.0)
        C.pending_orders = normalize_pending_orders(state.get('pending_orders', {}))
        C.target_etfs = [normalize_stock_code(x) for x in state.get('target_etfs', [])]
        C.target_weights = state.get('target_weights', [])
        C.last_prices = state.get('last_prices', {})
        C.order_book = state.get('order_book', {})

        print('[持久化] 状态恢复成功')
    except Exception as e:
        print('[持久化] 恢复状态失败:', e)


def save_state(C):
    # 回测模式不写本地状态，避免污染实盘/仿真状态文件
    if getattr(C, 'do_back_test', False):
        return
    else:
        if not is_trading_time(C):
            return
        current_date_str = datetime.datetime.now().strftime('%Y%m%d')

    filename = f"strategy_state_{current_date_str}.json"
    filepath = os.path.join(C.state_dir, filename)
    state = {
        'watermark': C.watermark,
        'in_lockdown': C.in_lockdown,
        'lockdown_days_left': C.lockdown_days_left,
        'trade_day_counter': C.trade_day_counter,
        'last_trade_date': C.last_trade_date,
        'last_rebalance_date': C.last_rebalance_date,
        'last_window_process_date': C.last_window_process_date,
        'day_start_equity': C.day_start_equity,
        'risk_check_date': C.risk_check_date,
        'last_lockdown_order_date': C.last_lockdown_order_date,
        'last_lockdown_check_date': C.last_lockdown_check_date,
        'pos_scale': C.pos_scale,
        'pending_orders': C.pending_orders,
        'target_etfs': C.target_etfs,
        'target_weights': C.target_weights,
        'last_prices': C.last_prices,
        'order_book': C.order_book,
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


def extract_close_values(raw):
    """兼容 QMT 返回的一维/二维数组、Series、DataFrame，提取有效收盘价序列。"""
    if raw is None:
        return []
    try:
        values = raw.values if hasattr(raw, 'values') else raw
        arr = np.asarray(values, dtype=object).reshape(-1)
    except:
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
        except:
            continue
    return close


def get_latest_valid_price(raw):
    close = extract_close_values(raw)
    return float(close[-1]) if close else 0


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
            return get_latest_valid_price(data[stock])
    except Exception as e:
        print('[行情] 获取最新价格失败 %s: %s' % (stock, e))
    return 0


def get_positions(C):
    """获取当前真实持仓字典"""
    try:
        pos_list = get_trade_detail_data(C.account, C.acct_type, 'position')
    except Exception as e:
        print('[错误] 获取持仓失败:', e)
        return None

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
    """获取账户可用资金；账户数据异常时返回 None，避免用旧缓存继续交易。"""
    try:
        acc = get_trade_detail_data(C.account, C.acct_type, 'account')
        if not acc:
            return None
        cash = acc[0].m_dAvailable
        if cash is None or np.isnan(cash) or cash < 0:
            return None
        # C.last_cash = cash  # 已废弃
        return cash
    except Exception as e:
        print('[错误] 获取可用资金失败:', e)
        return None


def get_total_value(C):
    """获取账户总资产；账户数据异常时返回 None，避免风控误判。"""
    try:
        acc = get_trade_detail_data(C.account, C.acct_type, 'account')
        if not acc:
            return None
        val = acc[0].m_dBalance
        if val is None or np.isnan(val) or val <= 0 or val > 1e9:
            return None
        # C.last_equity = val  # 已废弃
        return val
    except Exception as e:
        print('[错误] 获取账户总资产失败:', e)
        return None


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
        status = str(raw_status).strip().lower() if raw_status is not None else "unknown"
        text_status_map = {
            "已报": "submitted",
            "未成交": "submitted",
            "部成": "partial_filled",
            "部分成交": "partial_filled",
            "待撤": "canceling",
            "部成待撤": "partial_canceling",
            "已撤": "canceled",
            "部撤": "partial_canceled",
            "部分撤单": "partial_canceled",
            "已成": "filled",
            "全部成交": "filled",
            "废单": "rejected",
            "拒单": "rejected",
        }
        status = text_status_map.get(status, status)

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


def is_active_order_status(status):
    status = str(status or '').strip().lower()
    if status in ('filled', 'canceled', 'partial_canceled', 'rejected', 'expired', 'stale_unknown'):
        return False
    return status in ('submitted', 'pending', 'partial_filled', 'canceling', 'partial_canceling', 'unknown')


def is_final_order_status(status):
    status = str(status or '').lower()
    return status in ('filled', 'canceled', 'partial_canceled', 'rejected', 'expired', 'stale_unknown')


def parse_order_time(value):
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except:
        return None


def has_active_order(C, etf, side=None):
    etf = normalize_stock_code(etf)
    for order_id, order in getattr(C, 'order_book', {}).items():
        if order.get('etf') != etf:
            continue
        if side and order.get('side') != side:
            continue
        if is_active_order_status(order.get('status')):
            return str(order_id), order
    return None, None


def add_pending_order(C, etf, shares, reason, current_date, order_id=None):
    if getattr(C, 'do_back_test', False):
        return
    etf = normalize_stock_code(etf)
    shares = int(shares / 100) * 100
    if shares < 100:
        return
    if etf not in C.pending_orders:
        C.pending_orders[etf] = {
            "shares": shares,
            "days": 0,
            "reason": reason,
            "source_rebalance_date": current_date,
            "last_order_id": str(order_id) if order_id else "",
            "attempt_count": 0
        }
    else:
        C.pending_orders[etf]["shares"] += shares
        C.pending_orders[etf]["reason"] = reason
        if order_id:
            C.pending_orders[etf]["last_order_id"] = str(order_id)
    print('[%s] 登记补单: %s 缺额 %d 股，原因: %s' % (current_date, etf, shares, reason))


def archive_final_orders(C, current_date):
    """订单终态不删除，只标记归档；买单剩余部分转入补单。"""
    changed = False
    for order_id, order in list(getattr(C, 'order_book', {}).items()):
        if order.get('archived'):
            continue
        status = str(order.get('status', '')).lower()
        if not is_final_order_status(status):
            continue
        order['archived'] = True
        order['archive_time'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        changed = True

        etf = order.get('etf')
        side = order.get('side')
        volume = int(order.get('volume', 0) or 0)
        filled = int(order.get('filled', 0) or 0)
        remaining = int((volume - filled) / 100) * 100
        if side == 'buy' and remaining >= 100 and etf in getattr(C, 'target_etfs', []) and not getattr(C, 'in_lockdown', False):
            add_pending_order(C, etf, remaining, 'order_' + status, current_date, order_id)
            changed = True
    return changed


def request_cancel_order(C, order_id, order):
    """兼容不同 QMT 环境的撤单入口；找不到接口时只记录，不假装已撤。"""
    candidates = ['cancel', 'cancelorder', 'cancel_order']
    last_error = ''
    for name in candidates:
        fn = globals().get(name)
        if fn is None:
            continue
        signatures = [
            (order_id, C.account, C.acct_type, C),
            (C.account, C.acct_type, order_id, C),
            (C.account, order_id, C),
            (order_id, C),
            (order_id,)
        ]
        for args in signatures:
            try:
                result = fn(*args)
                order['cancel_requested'] = True
                order['cancel_request_time'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                order['status'] = 'canceling'
                return True
            except TypeError as e:
                last_error = str(e)
                continue
            except Exception as e:
                last_error = str(e)
                break
    order['cancel_error'] = last_error or 'cancel api not found'
    print('[撤单失败] 未能提交撤单: %s, %s, %s' % (order_id, order.get('etf'), order.get('cancel_error')))
    return False


def cancel_stale_orders(C, current_date, force=False):
    """超时未成交委托先撤单，避免后续重复下单造成超买/超卖。"""
    if getattr(C, 'do_back_test', False):
        return False
    sync_order_book(C)
    changed = archive_final_orders(C, current_date)
    now = datetime.datetime.now()
    timeout = getattr(C, 'order_timeout_seconds', 90)

    for order_id, order in list(getattr(C, 'order_book', {}).items()):
        if not is_active_order_status(order.get('status')):
            continue
        if order.get('cancel_requested') and str(order.get('status')).lower() in ('canceling', 'partial_canceling'):
            continue
        submit_time = parse_order_time(order.get('time'))
        elapsed = (now - submit_time).total_seconds() if submit_time else timeout + 1
        if not force and elapsed < timeout:
            continue
        print('[%s] [委托超时] 准备撤单: %s %s %s %s 股' % (
            current_date, order_id, order.get('side'), order.get('etf'), order.get('volume')
        ))
        if request_cancel_order(C, order_id, order):
            changed = True
    if changed:
        save_state(C)
    return changed


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
    active_id, active_order = has_active_order(C, etf, side)
    if active_id:
        print('[下单跳过] 已有活跃委托: %s %s %s %s 股' % (active_id, side, etf, active_order.get('volume')))
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
                "cancel_requested": False,
                "archived": False,
                "time": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            return order_id

        if getattr(C, 'do_back_test', False):
            # QMT 回测环境：passorder 已提交但不返回订单号，回测不依赖本地订单生命周期
            synthetic_id = 'BACKTEST_%s_%s_%s' % (side, etf, getattr(C, 'barpos', ''))
            if getattr(C, 'log_backtest_orders', False):
                print('[回测下单] 未返回订单号，按已提交处理: %s %s %d 股' % (side, etf, volume))
            return synthetic_id

        # 模拟盘：passorder 已提交但未返回订单号，生成合成 ID 登记到 order_book
        synthetic_id = 'SIM_%s_%s_%s_%s' % (side, etf, datetime.datetime.now().strftime('%H%M%S'), volume)
        C.order_book[synthetic_id] = {
            "etf": etf,
            "side": side,
            "volume": volume,
            "filled": 0,
            "status": "submitted",
            "remark": remark,
            "cancel_requested": False,
            "archived": False,
            "time": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        print('[模拟下单] 未返回订单号，已登记合成ID追踪: %s %s %s %d 股' % (synthetic_id, side, etf, volume))
        return synthetic_id
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
        close = extract_close_values(data[etf])
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


# ==================== 两阶段调仓（模拟盘） ====================
def execute_sells(C, targets, weights, pos_scale, current_date):
    """阶段一：只卖不买。"""
    cancel_stale_orders(C, current_date)
    positions = get_positions(C)
    if positions is None:
        print('[%s] [账户异常] 无法获取持仓，跳过卖单' % current_date)
        return False
    total_value_raw = get_total_value(C)
    if total_value_raw is None:
        print('[%s] [账户异常] 无法获取总资产，跳过卖单' % current_date)
        return False
    total_value = total_value_raw * pos_scale * getattr(C, 'capital_ratio', 1.0)
    target_set = set(targets)
    submitted = 0
    for etf, pos in list(positions.items()):
        price = get_current_price(C, etf)
        if price <= 0:
            continue
        shares = int(pos["shares"] / 100) * 100
        if shares < 100:
            continue
        if etf not in target_set:
            if not has_active_order(C, etf, 'sell')[0]:
                print('[%s] 卖出非目标: %s, %d 股' % (current_date, etf, shares))
                safe_order(C, 'sell', etf, shares, '清仓非目标')
                submitted += 1
            continue
        try:
            idx = targets.index(etf)
            target_value = total_value * weights[idx]
            target_shares = int(target_value / price / 100) * 100
            delta = target_shares - shares
            if delta <= -100:
                sell_vol = int(abs(delta) / 100) * 100
                if not has_active_order(C, etf, 'sell')[0]:
                    print('[%s] 卖出减仓: %s, %d 股' % (current_date, etf, sell_vol))
                    safe_order(C, 'sell', etf, sell_vol, '调仓卖出')
                    submitted += 1
        except Exception as e:
            print('[%s] [减仓计算失败] %s: %s' % (current_date, etf, e))
    sync_order_book(C)
    print('[%s] 阶段一完成：已提交 %d 笔卖单，等待成交' % (current_date, submitted))
    return True


def execute_buys(C, targets, weights, pos_scale, current_date):
    """阶段二：只买不卖。"""
    sync_order_book(C)
    positions = get_positions(C)
    if positions is None:
        return False
    total_value_raw = get_total_value(C)
    if total_value_raw is None:
        return False
    total_value = total_value_raw * pos_scale * getattr(C, 'capital_ratio', 1.0)
    available_cash = get_available_cash(C)
    if available_cash is None:
        print('[%s] [账户异常] 无法获取可用资金，跳过买单' % current_date)
        return False
    for i, etf in enumerate(targets):
        if has_active_order(C, etf, 'buy')[0]:
            continue
        target_value = total_value * weights[i]
        if target_value < 500:
            continue
        price = C.last_prices.get(etf, 0)
        if price <= 0:
            price = get_current_price(C, etf)
        if price <= 0:
            continue
        current_shares = int(positions.get(etf, {}).get("shares", 0))
        target_shares = int(target_value / price / 100) * 100
        delta = target_shares - current_shares
        if delta < 100:
            continue
        max_affordable = int(available_cash * 0.98 / price / 100) * 100
        buy_shares = min(delta, max_affordable)
        submitted_buy = 0
        if buy_shares >= 100:
            remark = '调仓买入' if buy_shares == delta else '调仓部分买入'
            print('[%s] 买入建仓: %s, %d 股' % (current_date, etf, buy_shares))
            order_id = safe_order(C, 'buy', etf, buy_shares, remark)
            if order_id:
                submitted_buy = buy_shares
                available_cash -= buy_shares * price
        remaining = delta - submitted_buy
        if remaining >= 100:
            add_pending_order(C, etf, remaining, 'cash_limited_or_unsubmitted', current_date)
    sync_order_book(C)
    print('[%s] 阶段二完成' % current_date)
    return True


def has_active_sell_orders(C):
    for key, order in getattr(C, 'order_book', {}).items():
        if order.get('side') == 'sell' and is_active_order_status(order.get('status')):
            return True
    return False


# ==================== 交易主执行（回测用，保留不变） ====================
def execute_trades(C, current_date):
    """执行调仓动作，并以真实账户现金为准登记补单。"""
    now = datetime.datetime.now()
    if C.order_lock and C.order_lock_time:
        if (now - C.order_lock_time).seconds < 5:
            return
    C.order_lock = True
    C.order_lock_time = now

    try:
        cancel_stale_orders(C, current_date)
        positions = get_positions(C)
        if positions is None:
            print('[%s] [账户异常] 无法获取持仓，跳过本次调仓' % current_date)
            return False
        target_set = set(C.target_etfs)
        total_value_raw = get_total_value(C)
        if total_value_raw is None:
            print('[%s] [账户异常] 无法获取总资产，跳过本次调仓' % current_date)
            return False
        total_value = total_value_raw * C.pos_scale * getattr(C, 'capital_ratio', 1.0)

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
                if has_active_order(C, etf, 'sell')[0]:
                    print('[%s] 已有卖出活跃委托，跳过重复清仓: %s' % (current_date, etf))
                    traded_today.add(etf)
                    continue
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
                    if has_active_order(C, etf, 'sell')[0]:
                        print('[%s] 已有卖出活跃委托，跳过重复减仓: %s' % (current_date, etf))
                        traded_today.add(etf)
                        continue
                    print('[%s] 卖出减仓: %s, %d 股' % (current_date, etf, sell_vol))
                    safe_order(C, 'sell', etf, sell_vol, '调仓卖出')
                    traded_today.add(etf)
            except Exception as e:
                print('[%s] [减仓计算失败] %s: %s' % (current_date, etf, e))

        sync_order_book(C)
        available_cash = get_available_cash(C)
        if available_cash is None:
            print('[%s] [账户异常] 无法获取可用资金，跳过买入并保留卖出委托' % current_date)
            return False

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

            if has_active_order(C, etf, 'buy')[0]:
                print('[%s] 已有买入活跃委托，跳过重复买入: %s' % (current_date, etf))
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
                    available_cash -= buy_vol * price

            remaining = delta - submitted_buy
            if remaining >= 100:
                add_pending_order(C, etf, remaining, 'cash_limited_or_unsubmitted', current_date)

        sync_order_book(C)
        latest_cash = get_available_cash(C)
        # C.last_cash = latest_cash  # 已废弃
        return True

    finally:
        C.order_lock = False


# ==================== 补单执行 ====================
def execute_pending_orders(C, current_date):
    """每日开盘尝试处理遗留未成交补单"""
    if not C.pending_orders:
        return

    cancel_stale_orders(C, current_date)
    print('[%s] [补单] 检查未成交补单...' % current_date)
    available_cash = get_available_cash(C)
    if available_cash is None:
        print('[%s] [账户异常] 无法获取可用资金，跳过补单' % current_date)
        return
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

        if has_active_order(C, etf, 'buy')[0]:
            print('[%s] [补单] 已有买入活跃委托，跳过重复补单: %s' % (current_date, etf))
            continue

        cost = need_shares * price * 1.02
        order["last_attempt_time"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        order["attempt_count"] = order.get("attempt_count", 0) + 1
        if available_cash >= cost:
            print('[%s] [补单] 满足条件，补全剩余 %s, %d 股' % (current_date, etf, need_shares))
            order_id = safe_order(C, 'buy', etf, need_shares, '补单完成')
            if order_id:
                order["last_order_id"] = str(order_id)
                available_cash -= cost
                expired.append(etf)
        else:
            max_shares = int(available_cash * 0.98 / price / 100) * 100
            if max_shares >= 100:
                print('[%s] [补单] 资金不足，先补 %d 股' % (current_date, etf, max_shares))
                order_id = safe_order(C, 'buy', etf, max_shares, '补单部分')
                if order_id:
                    order["last_order_id"] = str(order_id)
                    available_cash -= max_shares * price
                    order["shares"] -= max_shares

                order["days"] = order.get("days", 0) + 1
                if order["days"] > 5:
                    print('[%s] [补单] %s 挂单超时废弃' % (current_date, etf))
                    expired.append(etf)

    # 统一清理过期和已完成的补单
    for etf in expired:
        C.pending_orders.pop(etf, None)

    # 同步更新资金缓存
    # C.last_cash = available_cash  # 已废弃
    save_state(C)


# ==================== 风控执行 ====================
def submit_lockdown_liquidation(C, current_date):
    """空仓保护期间持续确认并提交清仓委托。"""
    cancel_stale_orders(C, current_date)
    positions = get_positions(C)
    if positions is None:
        print('[%s] [风控] 无法确认持仓，保持空仓保护并等待下次检查' % current_date)
        return True
    if not positions:
        return False
    if getattr(C, 'last_lockdown_order_date', '') == current_date:
        print('[%s] [风控] 空仓保护持仓未清，今日已提交过清仓委托' % current_date)
        return True
    print('[%s] [风控触发] 正在清空持仓进入空仓期' % current_date)
    for etf, pos in positions.items():
        price = get_current_price(C, etf)
        if price > 0:
            vol = int(pos["shares"] / 100) * 100
            if vol >= 100:
                if has_active_order(C, etf, 'sell')[0]:
                    print('[%s] [风控] 已有清仓活跃委托，跳过重复提交: %s' % (current_date, etf))
                    continue
                safe_order(C, 'sell', etf, vol, '空仓保护')
    C.last_lockdown_order_date = current_date
    return True


def trigger_lockdown(C, current_date):
    """触发账户全局空仓保护"""
    C.in_lockdown = True
    C.lockdown_days_left = C.lockdown_length
    C.pending_orders = {}
    submit_lockdown_liquidation(C, current_date)


def calculate_position_scale(C, current_date):
    """根据标的指数波动率调节组合仓位"""
    data = C.get_market_data_ex(['close'], ['159915.SZ'], period='1d',
                                count=C.vol_lookback + 5, end_time=current_date.replace('-', ''))
    if data is None or '159915.SZ' not in data:
        return 1.0
    close = extract_close_values(data['159915.SZ'])
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

    if not is_backtest:
        if getattr(C, 'rebalance_phase', None) != "selling":
            cancel_stale_orders(C, current_date)

    # 1. 账户数据异常时直接停止，避免使用旧缓存继续交易。
    now_val = get_total_value(C)
    if now_val is None:
        print('[%s] [账户异常] 无法获取账户总资产，停止本轮处理' % current_date)
        return

    # 2. 每日资产熔断和账户最大回撤检查，每个交易日都执行。
    if getattr(C, 'risk_check_date', '') != current_date:
        C.risk_check_date = current_date
        C.day_start_equity = now_val if now_val > 0 else None
    elif getattr(C, 'day_start_equity', None) is None and now_val > 0:
        C.day_start_equity = now_val

    day_start_equity = getattr(C, 'day_start_equity', None)
    if day_start_equity and now_val > 0:
        if now_val < day_start_equity * 0.85:
            print('[%s] [熔断] 当日资产回撤超15%%，暂停当日交易' % current_date)
            save_state(C)
            return

    if now_val > 100:
        if C.watermark is None or now_val > C.watermark:
            C.watermark = now_val
        dd = (now_val - C.watermark) / C.watermark if C.watermark else 0
        if dd < -C.drawdown_limit and not C.in_lockdown:
            print('[%s] [风控] 账户回撤 %.2f%% 破线，强制止损' % (current_date, dd * 100))
            trigger_lockdown(C, current_date)
            save_state(C)
            return

    # 3. 空仓锁定期优先处理：每日确认真实持仓是否已经清空。
    if C.in_lockdown:
        has_positions = submit_lockdown_liquidation(C, current_date)
        if has_positions:
            save_state(C)
            return

        if getattr(C, 'last_lockdown_check_date', '') != current_date:
            C.last_lockdown_check_date = current_date
            C.lockdown_days_left -= 1
            if C.lockdown_days_left <= 0:
                C.in_lockdown = False
                C.watermark = now_val
                print('[%s] [风控] 空仓期结束' % current_date)
            else:
                print('[%s] [风控] 空仓保护剩余 %d 天' % (current_date, C.lockdown_days_left))
        save_state(C)
        return

    # 4. 每日开盘时段状态更新与补单处理，重启后依赖持久化日期防止重复计数。
    if getattr(C, 'last_trade_date', '') != current_date:
        C.last_trade_date = current_date
        C.trade_day_counter += 1
        if not is_backtest and C.cooling_period_left <= 0:
            execute_pending_orders(C, current_date)
        save_state(C)

    # 5. 调仓触发条件过滤：实盘使用 14:50 后短窗口。
    if not is_backtest:
        if not in_rebalance_window(C):
            return
        if getattr(C, 'last_rebalance_date', '') == current_date:
            return
        if getattr(C, 'last_window_process_date', '') == current_date:
            return
    else:
        if getattr(C, 'last_rebalance_date', '') == current_date:
            return

    # 6. 急跌冷却期检查（修复：添加日志输出）
    if C.cooling_period_left > 0:
        C.cooling_period_left -= 1
        C.last_window_process_date = current_date
        print('[%s] [风控] 冷却期剩余 %d 天' % (current_date, C.cooling_period_left))
        save_state(C)
        return

    # 7. 周期调仓过滤
    if C.trade_day_counter % C.rebalance_freq != 0:
        C.last_window_process_date = current_date
        save_state(C)
        return

    # 8. 调仓执行：回测走原版，模拟盘走两阶段
    if is_backtest:
        # 回测：原有单次执行
        C.pos_scale = calculate_position_scale(C, current_date)
        C.target_etfs, C.target_weights = compute_targets(C, current_date)
        if not C.target_etfs:
            save_state(C)
            return
        C.pending_orders = {}
        trade_ok = execute_trades(C, current_date)
        if trade_ok:
            C.last_rebalance_date = current_date
            C.last_window_process_date = current_date
        save_state(C)
    else:
        # 模拟盘：两阶段调仓
        rebalance_phase = getattr(C, 'rebalance_phase', None)

        if rebalance_phase is None:
            print('[%s] --- 进入调仓流程（阶段一：卖） ---' % current_date)
            C.pos_scale = calculate_position_scale(C, current_date)
            new_targets, new_weights = compute_targets(C, current_date)
            if not new_targets:
                save_state(C)
                return
            C.rebalance_targets = new_targets
            C.rebalance_weights = new_weights
            C.target_etfs = new_targets
            C.target_weights = new_weights
            C.pending_orders = {}
            C.rebalance_phase = "selling"
            C.sell_phase_start = datetime.datetime.now()
            execute_sells(C, new_targets, new_weights, C.pos_scale, current_date)
            save_state(C)

        elif rebalance_phase == "selling":
            sync_order_book(C)
            if has_active_sell_orders(C):
                elapsed = (datetime.datetime.now() - C.sell_phase_start).total_seconds()
                if elapsed < 120:
                    return
                print('[%s] 卖单等待超时 %ds，强制进入阶段二' % (current_date, int(elapsed)))
            print('[%s] --- 卖单已成交，进入买入阶段 ---' % current_date)
            execute_buys(C, C.rebalance_targets, C.rebalance_weights, C.pos_scale, current_date)
            C.target_etfs = C.rebalance_targets
            C.target_weights = C.rebalance_weights
            C.rebalance_phase = None
            C.last_rebalance_date = current_date
            C.last_window_process_date = current_date
            print('[%s] --- 两阶段调仓已完成 ---' % current_date)
            save_state(C)