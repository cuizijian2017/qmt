# -*- coding: utf-8 -*-

import datetime as dt
import sys
import time

from config import ACCOUNT_ID, ACCOUNT_TYPE, ORDER_TIMEOUT_SECONDS, QMT_PATH, STRATEGY_ID, XTQUANT_PATH

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


class QmtBroker:
    def __init__(self, logger, state):
        self.logger = logger
        self.state = state
        self.trader = None
        self.account = None

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
        try:
            end_time = (end_date or "").replace("-", "")
            data = xtdata.get_market_data(
                field_list=["close"],
                stock_list=stock_list,
                period="1d",
                count=count,
                end_time=end_time,
            )
            if isinstance(data, dict) and "close" in data and hasattr(data["close"], "columns"):
                return {stock: data["close"][stock] for stock in data["close"].columns}
            if isinstance(data, dict):
                return data
            return {}
        except Exception as exc:
            self.logger.error("获取历史行情失败: %s", exc)
            return {}

    def get_latest_price(self, stock):
        history = self.get_close_history([stock], 1)
        raw = history.get(normalize_stock_code(stock)) or history.get(stock)
        if raw is None:
            return 0
        try:
            values = raw.values if hasattr(raw, "values") else raw
            import numpy as np

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
                return 0
        return 0

    def sync_orders(self):
        changed = False
        order_book = self.state.setdefault("order_book", {})

        for order in self.query_orders():
            order_id = str(getattr(order, "order_id", "") or "")
            remark = str(getattr(order, "order_remark", "") or "")
            key = remark or order_id
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
        etf = order.get("etf")
        if etf not in self.state.get("target_etfs", []):
            return
        volume = int(order.get("volume", 0) or 0)
        filled = int(order.get("filled", 0) or 0)
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
        self.logger.info("终态买单剩余转补单: key=%s etf=%s remaining=%s", order_key, etf, remaining)

    def archive_final_orders(self, state=None):
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
        order_id = self.trader.order_stock(
            self.account,
            etf,
            order_type,
            volume,
            xtconstant.LATEST_PRICE,
            0,
            STRATEGY_ID,
            remark,
        )
        if order_id is None or int(order_id) <= 0:
            self.logger.error("下单提交失败: side=%s etf=%s volume=%s remark=%s order_id=%s", side, etf, volume, remark, order_id)
            return None

        key = remark or str(order_id)
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
        self.logger.info("下单提交: order_id=%s side=%s etf=%s volume=%s remark=%s", order_id, side, etf, volume, remark)
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
                key = remark or order_id
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
