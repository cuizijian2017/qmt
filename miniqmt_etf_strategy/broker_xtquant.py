# -*- coding: utf-8 -*-

import datetime as dt
import sys
import time

from config import ACCOUNT_ID, ACCOUNT_TYPE, ORDER_TIMEOUT_SECONDS, QMT_PATH, SIMULATION_MODE, STRATEGY_ID, XTQUANT_PATH

sys.path.append(XTQUANT_PATH)

from xtquant import xtconstant, xttrader  # noqa: E402
from xtquant import xtdata  # noqa: E402
from xtquant.xttype import StockAccount  # noqa: E402


ORDER_STATUS_MAP = {
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
    255: "unknown",
}


def normalize_stock_code(stock_code):
    if not stock_code:
        return ""
    code = str(stock_code).strip().upper()
    if "." in code:
        base, suffix = code.split(".", 1)
        suffix_map = {
            "SH": "SH",
            "SSE": "SH",
            "SHSE": "SH",
            "XSHG": "SH",
            "SZ": "SZ",
            "SZSE": "SZ",
            "XSHE": "SZ",
        }
        return base + "." + suffix_map.get(suffix, suffix)
    if code.startswith(("5", "6", "9")):
        return code + ".SH"
    if code.startswith(("0", "1", "2", "3")):
        return code + ".SZ"
    return code


def order_status_name(status):
    try:
        return ORDER_STATUS_MAP.get(int(status), str(status))
    except Exception:
        return str(status).lower() if status is not None else "unknown"


def is_active_status(status):
    status = str(status or "").lower()
    return status in ("pending", "submitted", "partial_filled", "canceling", "partial_canceling", "unknown")


def is_final_status(status):
    status = str(status or "").lower()
    return status in ("filled", "canceled", "partial_canceled", "rejected")


def _normalize_trade_date_value(value):
    # 统一把不同形态日期（字符串/时间戳/datetime）归一化为 YYYYMMDD
    if value is None:
        return ""

    if isinstance(value, dt.datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, dt.date):
        return value.strftime("%Y%m%d")

    if isinstance(value, (int, float)):
        raw = str(int(value))
        if len(raw) >= 13:
            return dt.datetime.fromtimestamp(int(raw[:13]) / 1000).strftime("%Y%m%d")
        if len(raw) == 10:
            return dt.datetime.fromtimestamp(int(raw)).strftime("%Y%m%d")
        if len(raw) == 8 and raw.isdigit():
            return raw
        return ""

    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    # 兼容 xtdata 把时间戳以字符串/np.int64 形式返回：
    # 13位毫秒时间戳、10位秒时间戳都需要先转本地日期，不能直接截前8位。
    if len(digits) >= 13:
        try:
            return dt.datetime.fromtimestamp(int(digits[:13]) / 1000).strftime("%Y%m%d")
        except Exception:
            pass
    if len(digits) == 10:
        try:
            return dt.datetime.fromtimestamp(int(digits)).strftime("%Y%m%d")
        except Exception:
            pass
    if len(digits) >= 8:
        return digits[:8]
    return ""


class QmtBroker:
    def __init__(self, logger, state=None):
        self.logger = logger
        self.state = state or {}
        self.trader = None
        self.account = None
        self._normalize_order_book_keys()

    def _normalize_order_book_keys(self):
        # 历史版本可能以 remark 作为 key，这里统一回收为 order_id，避免串单
        order_book = self.state.get("order_book")
        if not isinstance(order_book, dict) or not order_book:
            return

        normalized = {}
        for old_key, record in order_book.items():
            if not isinstance(record, dict):
                continue
            order_id = str(record.get("order_id", "") or "")
            key = order_id or str(old_key)
            existing = normalized.get(key)
            if existing is None:
                normalized[key] = dict(record)
            else:
                merged = dict(existing)
                merged.update(record)
                normalized[key] = merged
        self.state["order_book"] = normalized

    def connect(self):
        session_id = int(time.time())
        self.trader = xttrader.XtQuantTrader(QMT_PATH, session_id)
        self.trader.register_callback(self._build_callback())
        self.trader.start()

        connect_result = self.trader.connect()
        self.logger.info("connect_result: %s", connect_result)
        if connect_result != 0:
            raise RuntimeError("miniQMT 连接失败")

        self.account = StockAccount(ACCOUNT_ID, ACCOUNT_TYPE)
        subscribe_result = self.trader.subscribe(self.account)
        self.logger.info("subscribe_result: %s", subscribe_result)
        if subscribe_result != 0:
            raise RuntimeError("账户订阅失败")

    def stop(self):
        if self.trader:
            self.trader.stop()

    def query_asset(self):
        return self.trader.query_stock_asset(self.account)

    def query_positions(self):
        positions = self.trader.query_stock_positions(self.account)
        result = {}
        for pos in positions or []:
            code = normalize_stock_code(getattr(pos, "stock_code", ""))
            volume = int(getattr(pos, "volume", 0) or 0)
            can_use = int(getattr(pos, "can_use_volume", volume) or 0)
            market_value = float(getattr(pos, "market_value", 0) or 0)
            if code and volume > 0:
                result[code] = {
                    "shares": volume,
                    "can_use": can_use,
                    "value": market_value,
                }
        return result

    def positions_dict(self):
        return self.query_positions()

    def query_orders(self):
        return self.trader.query_stock_orders(self.account) or []

    def query_trades(self):
        return self.trader.query_stock_trades(self.account) or []

    def get_total_asset(self):
        asset = self.query_asset()
        if asset is None:
            return None
        value = getattr(asset, "total_asset", None)
        if value is None:
            value = getattr(asset, "m_dTotalAsset", None)
        return float(value) if value is not None else None

    def get_cash(self):
        asset = self.query_asset()
        if asset is None:
            return None
        cash = getattr(asset, "cash", None)
        if cash is None:
            cash = getattr(asset, "m_dCash", None)
        return float(cash) if cash is not None else None

    def get_close_history(self, stock_list, count, end_date=None):
        # 按官方文档规范：先确保数据已下载，再 get_market_data 获取
        # end_time 指定昨天，取完整的日线（不含当天未收盘的数据）
        try:
            from datetime import datetime, timedelta
            yesterday = datetime.now() - timedelta(days=1)
            end_time = yesterday.strftime("%Y%m%d")
            if end_date:
                end_time = end_date.replace("-", "")

            norm_list = [normalize_stock_code(s) for s in stock_list if s]
            if not norm_list:
                self.logger.warning("get_close_history: empty stock_list")
                return {}

            data = xtdata.get_market_data(
                field_list=["close"],
                stock_list=norm_list,
                period="1d",
                end_time=end_time,
                count=count,
                dividend_type="none",
                fill_data=True,
            )
            if not isinstance(data, dict) or "close" not in data:
                self.logger.warning("get_close_history: no close in data, type=%s", type(data).__name__)
                return {}

            block = data["close"]
            # 文档约定: K线返回 {field: DataFrame}，index=stock_list, columns=time_list
            out = {}
            for s in norm_list:
                try:
                    if hasattr(block, "loc"):
                        if s in block.index:
                            series = block.loc[s]
                        elif s in block.columns:
                            series = block[s]
                        else:
                            # 有时 index 可能不带后缀，尝试按代码前缀匹配
                            prefix = s.split(".")[0]
                            matched = [idx for idx in block.index if str(idx).startswith(prefix)]
                            if matched:
                                series = block.loc[matched[0]]
                            else:
                                self.logger.warning("get_close_history: %s not in index or columns", s)
                                continue
                    elif isinstance(block, dict) and s in block:
                        series = block[s]
                    else:
                        continue

                    if hasattr(series, "values"):
                        arr = series.values
                    elif hasattr(series, "tolist"):
                        arr = series.tolist()
                    else:
                        arr = series

                    import numpy as np
                    vals = np.asarray(arr, dtype=float).reshape(-1).tolist()
                    vals = [v for v in vals if not np.isnan(v) and 0 < v < 1e6]
                    if vals:
                        out[s] = vals
                except Exception as exc:
                    self.logger.warning("get_close_history: skip %s: %s", s, exc)
                    continue

            if out:
                return out

            self.logger.warning(
                "get_close_history: no stocks found, block_type=%s, norm_list=%s, "
                "block_index=%s, block_cols_head=%s",
                type(block).__name__, norm_list,
                list(block.index) if hasattr(block, 'index') else "N/A",
                list(block.columns)[:5] if hasattr(block, 'columns') else "N/A"
            )
            return {}
        except Exception as exc:
            self.logger.error("获取历史行情失败: %s", exc)
            return {}

    def get_latest_price(self, stock, require_tick=False):
        """获取最新价格。
        
        require_tick=True: 仅用 get_full_tick lastPrice，拿不到返回0（实盘/强制tick场景）
        require_tick=False: tick→PreClose→日线close 三重回退，保证有值
        """
        ns = normalize_stock_code(stock)

        # 1. 优先 get_full_tick lastPrice
        try:
            tick = xtdata.get_full_tick([ns])
            if isinstance(tick, dict) and ns in tick:
                t = tick[ns]
                if isinstance(t, dict):
                    for key in ("lastPrice", "last_price", "newPrice", "price"):
                        if key in t and t[key] not in (None, "", 0):
                            v = float(t[key])
                            if v > 0:
                                return v
        except Exception:
            pass

        if require_tick:
            return 0

        # 2. get_instrument_detail PreClose（模拟盘/非交易时段保底）
        try:
            detail = xtdata.get_instrument_detail(ns, False)
            if isinstance(detail, dict):
                pc = detail.get("PreClose") or detail.get("preClose")
                if pc not in (None, "", 0):
                    v = float(pc)
                    if v > 0:
                        return v
        except Exception:
            pass

        # 3. 历史日线 close
        history = self.get_close_history([stock], 1)
        raw = history.get(ns) or history.get(stock)
        if raw is not None:
            try:
                import numpy as np
                values = raw.values if hasattr(raw, "values") else raw
                arr = np.asarray(values, dtype=object).reshape(-1)
                for x in reversed(arr):
                    try:
                        v = float(x)
                        if v > 0:
                            return v
                    except Exception:
                        continue
            except Exception:
                try:
                    return float(raw)
                except Exception:
                    pass
        return 0

    def _query_trading_day_by_xtdata(self, target):
        # 兼容不同 xtdata 版本签名，尽量拿到交易日历结果
        def _to_date_set(dates):
            normalized = set()
            if dates is None:
                return normalized
            if isinstance(dates, dict):
                iterable = dates.values()
            else:
                iterable = dates
            try:
                for item in iterable:
                    normalized.add(_normalize_trade_date_value(item))
            except Exception:
                pass
            return {x for x in normalized if x}

        calendar_calls = [
            ("SH", target, target),
            ("SH", target, target, 1),
            ("SZ", target, target),
            ("SZ", target, target, 1),
            ("SH", target.replace("-", ""), target.replace("-", "")),
            ("SZ", target.replace("-", ""), target.replace("-", "")),
        ]
        has_response = False
        collected = set()
        for args in calendar_calls:
            try:
                dates = xtdata.get_trading_dates(*args)
            except Exception:
                continue
            if dates is None:
                continue
            has_response = True
            normalized = _to_date_set(dates)
            collected.update(normalized)
            if target in normalized:
                return True, "xtdata"

        # 某些 xtdata 版本在 start=end=当天 时会返回空列表，补一次"最近N个交易日"查询兜底
        recent_calendar_calls = [
            ("SH",),
            ("SZ",),
            ("SH", 400),
            ("SZ", 400),
            ("SH", "", ""),
            ("SZ", "", ""),
            ("SH", "", "", 400),
            ("SZ", "", "", 400),
        ]
        for args in recent_calendar_calls:
            try:
                dates = xtdata.get_trading_dates(*args)
            except Exception:
                continue
            if dates is None:
                continue
            has_response = True
            normalized = _to_date_set(dates)
            collected.update(normalized)
            if target in normalized:
                return True, "xtdata_recent"

        if has_response:
            # 仅在误判风险场景打印少量诊断，帮助快速定位 xtdata 返回格式/签名差异
            try:
                sample = sorted(collected)[-5:] if collected else []
                self.logger.warning("交易日历未命中 target=%s, sample=%s", target, sample)
            except Exception:
                pass
            return False, "xtdata"
        return None, "xtdata_unavailable"

    def is_trading_day(self, trade_date=None):
        is_day, _ = self.get_trading_day_status(trade_date)
        return is_day

    def get_trading_day_status(self, trade_date=None):
        # 保守策略：交易日历不可用时默认"非交易日"，避免误下单
        target = _normalize_trade_date_value(trade_date or dt.datetime.now().strftime("%Y-%m-%d"))
        if not target:
            return False, "fallback_invalid_date"

        is_day, source = self._query_trading_day_by_xtdata(target)
        if is_day is not None:
            return is_day, source

        # Conservative fallback: if calendar API is unavailable, treat as non-trading day.
        return False, "fallback_conservative"

    def sync_orders(self):
        # 定期同步委托状态，更新 order_book 里的成交与状态字段
        changed = False
        order_book = self.state.setdefault("order_book", {})

        for order in self.query_orders():
            order_id = str(getattr(order, "order_id", "") or "")
            remark = str(getattr(order, "order_remark", "") or "")
            # Always prefer broker-assigned order_id as stable key.
            key = order_id or remark
            if not key:
                continue

            status = order_status_name(getattr(order, "order_status", None))
            record = order_book.setdefault(key, {})
            before = dict(record)
            record.update(
                {
                    "order_id": order_id,
                    "order_sysid": str(getattr(order, "order_sysid", "") or ""),
                    "remark": remark,
                    "etf": normalize_stock_code(getattr(order, "stock_code", "")),
                    "side": self._order_side(getattr(order, "order_type", None)),
                    "volume": int(getattr(order, "order_volume", 0) or 0),
                    "filled": int(getattr(order, "traded_volume", 0) or 0),
                    "status": status,
                    "status_msg": str(getattr(order, "status_msg", "") or ""),
                    "last_sync_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            if before != record:
                changed = True
                self.logger.info(
                    "委托同步: %s %s %s %s/%s status=%s",
                    key,
                    record.get("side"),
                    record.get("etf"),
                    record.get("filled"),
                    record.get("volume"),
                    status,
                )
        return changed

    def has_active_order(self, etf, side=None):
        etf = normalize_stock_code(etf)
        for key, order in self.state.get("order_book", {}).items():
            if order.get("etf") != etf:
                continue
            if side and order.get("side") != side:
                continue
            if is_active_status(order.get("status")):
                return key, order
        return None, None

    def add_pending_from_order(self, order_key, order):
        if order.get("side") != "buy":
            return
        # 只有部分成交的才补单，拒单/撤单（没成交过）不补
        filled = int(order.get("filled", 0) or 0)
        if filled <= 0:
            return
        etf = order.get("etf")
        if etf not in self.state.get("target_etfs", []):
            return
        volume = int(order.get("volume", 0) or 0)
        remaining = int((volume - filled) / 100) * 100
        if remaining < 100:
            return
        pending = self.state.setdefault("pending_orders", {})
        if etf not in pending:
            pending[etf] = {
                "shares": remaining,
                "days": 0,
                "reason": "order_" + str(order.get("status")),
                "source_rebalance_date": dt.datetime.now().strftime("%Y-%m-%d"),
                "last_order_id": str(order.get("order_id") or ""),
                "attempt_count": 0,
            }
        else:
            pending[etf]["shares"] = int(pending[etf].get("shares", 0)) + remaining
        self.logger.info("终态买单剩余转补单: key=%s etf=%s filled=%s/%s remaining=%s", order_key, etf, filled, volume, remaining)

    def archive_final_orders(self, state=None):
        # 终态订单打归档标记；买单未成交剩余转入补单池
        changed = False
        state = state or self.state
        for key, order in list(state.get("order_book", {}).items()):
            if order.get("archived"):
                continue
            if not is_final_status(order.get("status")):
                continue
            order["archived"] = True
            order["archive_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.add_pending_from_order(key, order)
            changed = True
        return changed

    def cancel_stale_orders(self, state=None):
        # 超时活跃委托自动撤单，降低卡单导致的重复下单风险
        changed = False
        state = state or self.state
        now = dt.datetime.now()
        for key, order in list(state.get("order_book", {}).items()):
            if not is_active_status(order.get("status")):
                continue
            if order.get("cancel_requested"):
                continue
            created_at = order.get("created_at") or order.get("last_sync_time")
            try:
                created_dt = dt.datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                elapsed = (now - created_dt).total_seconds()
            except Exception:
                elapsed = ORDER_TIMEOUT_SECONDS + 1
            if elapsed < ORDER_TIMEOUT_SECONDS:
                continue
            if self.cancel_order(key, order):
                changed = True
        return changed

    def order(self, side, etf, volume, remark):
        return self.submit_order(etf, side, volume, self.make_remark(side, etf, remark))

    def make_remark(self, side, etf, remark):
        ts = dt.datetime.now().strftime("%Y%m%d%H%M%S")
        base = "%s_%s_%s_%s" % (STRATEGY_ID, ts, side.upper(), normalize_stock_code(etf).replace(".", ""))
        return base[:24]

    def submit_order(self, etf, side, volume, remark):
        etf = normalize_stock_code(etf)
        volume = int(volume / 100) * 100
        if volume < 100:
            return None

        active_key, active_order = self.has_active_order(etf, side)
        if active_key:
            self.logger.warning(
                "已有活跃委托，跳过重复下单: key=%s side=%s etf=%s volume=%s",
                active_key,
                side,
                etf,
                active_order.get("volume"),
            )
            return None

        order_type = xtconstant.STOCK_BUY if side == "buy" else xtconstant.STOCK_SELL

        if SIMULATION_MODE:
            # ========== 模拟盘模式：FIX_PRICE + get_latest_price 保底 ==========
            price = self.get_latest_price(etf)
            if price <= 0:
                self.logger.error("[模拟盘] 获取价格失败，跳过下单: side=%s etf=%s", side, etf)
                return None
            order_id = self.trader.order_stock(
                self.account, etf, order_type, volume,
                xtconstant.FIX_PRICE, price,
                STRATEGY_ID, remark,
            )
            self.logger.info("[模拟盘] 下单: side=%s etf=%s vol=%s price=%s FIX_PRICE", side, etf, volume, price)
        else:
            # ========== 实盘模式：文档标准写法 ==========
            if side == "buy":
                # 买入：FIX_PRICE + tick lastPrice（官方示例第909行）
                full_tick = xtdata.get_full_tick([etf])
                if not isinstance(full_tick, dict) or etf not in full_tick:
                    self.logger.error("[实盘] get_full_tick 无数据，跳过买入: etf=%s", etf)
                    return None
                price = float(full_tick[etf].get("lastPrice", 0))
                if price <= 0:
                    self.logger.error("[实盘] lastPrice 无效，跳过买入: etf=%s", etf)
                    return None
                order_id = self.trader.order_stock(
                    self.account, etf, order_type, volume,
                    xtconstant.FIX_PRICE, price,
                    STRATEGY_ID, remark,
                )
                self.logger.info("[实盘] 买入: etf=%s vol=%s price=%s FIX_PRICE", etf, volume, price)
            else:
                # 卖出：LATEST_PRICE + -1（官方示例第922行）
                order_id = self.trader.order_stock(
                    self.account, etf, order_type, volume,
                    xtconstant.LATEST_PRICE, -1,
                    STRATEGY_ID, remark,
                )
                self.logger.info("[实盘] 卖出: etf=%s vol=%s LATEST_PRICE", etf, volume)

        if order_id is None or int(order_id) <= 0:
            self.logger.error("下单提交失败: side=%s etf=%s volume=%s remark=%s order_id=%s", side, etf, volume, remark, order_id)
            return None

        key = str(order_id)
        self.state.setdefault("order_book", {})[key] = {
            "order_id": str(order_id),
            "remark": remark,
            "etf": etf,
            "side": side,
            "volume": volume,
            "filled": 0,
            "status": "submitted",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.logger.info("下单提交成功: order_id=%s", order_id)
        return str(order_id)

    def cancel_order(self, key, order):
        order_id = order.get("order_id")
        if not order_id:
            self.logger.warning("撤单跳过: 缺少 order_id key=%s", key)
            return False
        result = self.trader.cancel_order_stock(self.account, int(order_id))
        if result == 0:
            order["status"] = "canceling"
            order["cancel_requested"] = True
            order["cancel_requested_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.logger.info("撤单提交: key=%s order_id=%s etf=%s", key, order_id, order.get("etf"))
            return True
        self.logger.error("撤单提交失败: key=%s order_id=%s result=%s", key, order_id, result)
        return False

    def print_account_snapshot(self):
        asset = self.query_asset()
        if asset:
            self.logger.info(
                "资产: total_asset=%s cash=%s market_value=%s",
                getattr(asset, "total_asset", None),
                getattr(asset, "cash", None),
                getattr(asset, "market_value", None),
            )
        else:
            self.logger.warning("资产查询为空")

        positions = self.query_positions()
        self.logger.info("持仓数量: %d", len(positions))
        for code, pos in positions.items():
            self.logger.info("持仓: %s shares=%s can_use=%s value=%s", code, pos["shares"], pos["can_use"], pos["value"])

    def _order_side(self, order_type):
        try:
            order_type = int(order_type)
        except Exception:
            return str(order_type)
        if order_type == int(xtconstant.STOCK_BUY):
            return "buy"
        if order_type == int(xtconstant.STOCK_SELL):
            return "sell"
        return str(order_type)

    def _build_callback(self):
        logger = self.logger
        state = self.state

        class Callback(xttrader.XtQuantTraderCallback):
            def on_disconnected(self):
                logger.error("miniQMT 连接断开")

            def on_stock_order(self, order):
                remark = str(getattr(order, "order_remark", "") or "")
                order_id = str(getattr(order, "order_id", "") or "")
                key = order_id or remark
                if not key:
                    return
                status = order_status_name(getattr(order, "order_status", None))
                record = state.setdefault("order_book", {}).setdefault(key, {})
                record.update(
                    {
                        "order_id": order_id,
                        "remark": remark,
                        "etf": normalize_stock_code(getattr(order, "stock_code", "")),
                        "volume": int(getattr(order, "order_volume", 0) or 0),
                        "filled": int(getattr(order, "traded_volume", 0) or 0),
                        "status": status,
                        "last_callback_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
                logger.info(
                    "委托回报: key=%s etf=%s status=%s filled=%s/%s",
                    key,
                    record.get("etf"),
                    status,
                    record.get("filled"),
                    record.get("volume"),
                )

            def on_stock_trade(self, trade):
                logger.info(
                    "成交回报: order_id=%s stock=%s volume=%s price=%s remark=%s",
                    getattr(trade, "order_id", None),
                    normalize_stock_code(getattr(trade, "stock_code", "")),
                    getattr(trade, "traded_volume", None),
                    getattr(trade, "traded_price", None),
                    getattr(trade, "order_remark", None),
                )

            def on_order_error(self, order_error):
                logger.error(
                    "下单错误: order_id=%s error_id=%s error_msg=%s remark=%s",
                    getattr(order_error, "order_id", None),
                    getattr(order_error, "error_id", None),
                    getattr(order_error, "error_msg", None),
                    getattr(order_error, "order_remark", None),
                )

            def on_cancel_error(self, cancel_error):
                logger.error(
                    "撤单错误: order_id=%s error_id=%s error_msg=%s",
                    getattr(cancel_error, "order_id", None),
                    getattr(cancel_error, "error_id", None),
                    getattr(cancel_error, "error_msg", None),
                )

        return Callback()
