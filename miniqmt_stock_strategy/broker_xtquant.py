# -*- coding: utf-8 -*-

import datetime as dt
import json
import os
import sys
import time

import numpy as np
import pandas as pd

from config import (
    ACCOUNT_ID,
    ACCOUNT_TYPE,
    BUY_SLIPPAGE_BUFFER,
    FACTOR_FILE_PATTERN,
    INDEX_CODE,
    ORDER_TIMEOUT_SECONDS,
    QMT_PATH,
    SIMULATION_MODE,
    STOCK_POOL_FILE,
    STRATEGY_ID,
    USE_DATA_FILE_FALLBACK,
    XTQUANT_PATH,
)

# 指数代码 -> 板块/别名候选（get_index_stocks 会先试规范指数代码，再合并下列名称）
INDEX_STOCK_LIST_SECTOR_CANDIDATES = {
    "000905.SH": ["000905.SH", "中证500"],
    "000300.SH": ["000300.SH", "沪深300"],
    "000852.SH": ["000852.SH", "中证1000"],
}

sys.path.append(XTQUANT_PATH)

from xtquant import xtconstant, xtdata, xttrader  # noqa: E402
from xtquant.xttype import StockAccount  # noqa: E402


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


def is_active_status(status):
    return str(status or "").lower() in ("pending", "submitted", "partial_filled", "canceling", "partial_canceling", "unknown")


def _parse_get_full_tick_result(result):
    """
    兼容 get_full_tick 返回 dict 或 JSON str 的情况。
    返回 dict: { stock_code -> tick_dict }
    """
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


class QmtBroker:
    def __init__(self, logger, state=None):
        self.logger = logger
        self.state = state or {}
        self.trader = None
        self.account = None

    def connect(self):
        session_id = int(time.time())
        self.trader = xttrader.XtQuantTrader(QMT_PATH, session_id)
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
        positions = self.trader.query_stock_positions(self.account) or []
        result = {}
        for pos in positions:
            code = normalize_stock_code(getattr(pos, "stock_code", ""))
            volume = int(getattr(pos, "volume", 0) or 0)
            can_use = int(getattr(pos, "can_use_volume", volume) or 0)
            market_value = float(getattr(pos, "market_value", 0) or 0)
            if code and volume > 0:
                result[code] = {"shares": volume, "can_use": can_use, "value": market_value}
        return result

    def positions_dict(self):
        return self.query_positions()

    def query_orders(self):
        return self.trader.query_stock_orders(self.account) or []

    def get_total_asset(self):
        asset = self.query_asset()
        if asset is None:
            return None
        value = getattr(asset, "total_asset", getattr(asset, "m_dTotalAsset", None))
        return float(value) if value is not None else None

    def get_cash(self):
        asset = self.query_asset()
        if asset is None:
            return None
        cash = getattr(asset, "cash", getattr(asset, "m_dCash", None))
        return float(cash) if cash is not None else None

    def print_account_snapshot(self):
        asset = self.query_asset()
        if asset is None:
            self.logger.warning("资产查询失败")
            return
        total_asset = getattr(asset, "total_asset", getattr(asset, "m_dTotalAsset", 0))
        cash = getattr(asset, "cash", getattr(asset, "m_dCash", 0))
        market_value = float(total_asset or 0) - float(cash or 0)
        self.logger.info("资产: total_asset=%s cash=%s market_value=%s", total_asset, cash, market_value)
        self.logger.info("持仓数量: %s", len(self.query_positions()))

    def is_trading_day(self, trade_date=None):
        date_text = trade_date or dt.datetime.now().strftime("%Y-%m-%d")
        return dt.datetime.strptime(date_text, "%Y-%m-%d").weekday() < 5

    def get_close_history(self, stock_list, count, end_date=None):
        end_time = (end_date or "").replace("-", "")
        norm_list = [normalize_stock_code(s) for s in stock_list if s]
        if not norm_list:
            return {}
        try:
            data = xtdata.get_market_data(
                field_list=["close"],
                stock_list=norm_list,
                period="1d",
                count=count,
                end_time=end_time,
                dividend_type="none",
                fill_data=True,
            )
            if not isinstance(data, dict) or "close" not in data:
                return {}
            block = data["close"]
            out = {}
            for s in norm_list:
                try:
                    if hasattr(block, "index") and s in block.index:
                        out[s] = block.loc[s]
                    elif hasattr(block, "columns") and s in block.columns:
                        out[s] = block[s]
                except Exception:
                    continue
            if out:
                return out
            if isinstance(data, dict):
                return {normalize_stock_code(k): v for k, v in data.items()}
            return {}
        except Exception as exc:
            self.logger.error("获取历史行情失败: %s", exc)
            return {}

    def get_latest_price(self, stock, require_tick=False):
        stock = normalize_stock_code(stock)
        # 先下载和订阅，让 tick 数据能过来
        try:
            sub = getattr(xtdata, "subscribe_quote", None)
            if sub:
                try:
                    sub(stock, period="1d", count=-1, dividend_type="none")
                except Exception:
                    pass
                try:
                    sub(stock, period="tick", count=-1)
                except Exception:
                    pass
        except Exception:
            pass

        # 优先轮询 tick lastPrice
        for i in range(5):
            try:
                tick_raw = xtdata.get_full_tick([stock])
                tick = _parse_get_full_tick_result(tick_raw)
                if stock in tick:
                    t = tick[stock]
                    if isinstance(t, dict):
                        for key in ("lastPrice", "last_price", "newPrice", "price"):
                            if key in t and t[key] not in (None, "", 0):
                                try:
                                    v = float(t[key])
                                    if v > 0:
                                        return v
                                except (TypeError, ValueError):
                                    pass
            except Exception:
                pass
            time.sleep(0.2)

        if require_tick:
            return 0

        # tick 没拿到的话，再试合约 lastClose
        try:
            tick_raw = xtdata.get_full_tick([stock])
            tick = _parse_get_full_tick_result(tick_raw)
            if stock in tick:
                t = tick[stock]
                if isinstance(t, dict):
                    for key in ("lastClose", "preClose", "last_close", "prev_close"):
                        if key in t and t[key] not in (None, "", 0):
                            try:
                                v = float(t[key])
                                if v > 0:
                                    return v
                            except (TypeError, ValueError):
                                pass
        except Exception:
            pass

        # 再试历史日线
        raw = self.get_close_history([stock], 1).get(stock)
        if raw is not None:
            try:
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
                pass

        # 最后试合约 PreClose
        gi = getattr(xtdata, "get_instrument_detail", None)
        if gi:
            try:
                d = gi(stock, False)
                if isinstance(d, dict):
                    pc = d.get("PreClose") or d.get("preClose")
                    if pc not in (None, "", 0):
                        v = float(pc)
                        if v > 0:
                            return v
            except Exception:
                pass
        return 0

    def has_active_order(self, stock, side=None):
        stock = normalize_stock_code(stock)
        for key, order in self.state.get("order_book", {}).items():
            if order.get("stock") != stock:
                continue
            if side and order.get("side") != side:
                continue
            if is_active_status(order.get("status")):
                return key, order
        return None, None

    def sync_orders(self):
        changed = False
        book = self.state.setdefault("order_book", {})
        for order in self.query_orders():
            oid = str(getattr(order, "order_id", "") or "")
            if not oid:
                continue
            status = str(getattr(order, "order_status", "unknown") or "unknown")
            rec = book.setdefault(oid, {})
            before = dict(rec)
            rec.update(
                {
                    "order_id": oid,
                    "stock": normalize_stock_code(getattr(order, "stock_code", "")),
                    "side": "buy" if int(getattr(order, "order_type", 0) or 0) == xtconstant.STOCK_BUY else "sell",
                    "volume": int(getattr(order, "order_volume", 0) or 0),
                    "filled": int(getattr(order, "traded_volume", 0) or 0),
                    "status": status,
                    "last_sync_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            if rec != before:
                changed = True
        return changed

    def cancel_stale_orders(self):
        now = dt.datetime.now()
        changed = False
        for key, order in list(self.state.get("order_book", {}).items()):
            if not is_active_status(order.get("status")):
                continue
            created = order.get("created_at") or order.get("last_sync_time")
            try:
                created_dt = dt.datetime.strptime(created, "%Y-%m-%d %H:%M:%S")
                elapsed = (now - created_dt).total_seconds()
            except Exception:
                elapsed = ORDER_TIMEOUT_SECONDS + 1
            if elapsed < ORDER_TIMEOUT_SECONDS:
                continue
            if self.cancel_order(key, order):
                changed = True
        return changed

    def cancel_order(self, key, order):
        try:
            order_id = int(order.get("order_id") or key)
            ret = self.trader.cancel_order_stock(self.account, order_id)
            order["cancel_requested"] = True
            if ret == 0:
                self.logger.info("撤单提交成功: order_id=%s stock=%s", order_id, order.get("stock"))
                return True
            self.logger.warning("撤单返回非0: order_id=%s ret=%s", order_id, ret)
            return False
        except Exception as exc:
            self.logger.warning("撤单异常: %s", exc)
            return False

    def order(self, side, stock, volume, remark):
        stock = normalize_stock_code(stock)
        volume = int(volume / 100) * 100
        if volume < 100:
            return None
        active, _ = self.has_active_order(stock, side)
        if active:
            return None

        order_type = xtconstant.STOCK_BUY if side == "buy" else xtconstant.STOCK_SELL

        if SIMULATION_MODE:
            # ========== 模拟盘模式：FIX_PRICE + get_latest_price 保底 ==========
            price = self.get_latest_price(stock)
            if price <= 0:
                self.logger.error("[模拟盘] 获取价格失败，跳过下单: side=%s stock=%s", side, stock)
                return None
            oid = self.trader.order_stock(
                self.account, stock, order_type, volume,
                xtconstant.FIX_PRICE, price,
                STRATEGY_ID, remark[:24],
            )
            self.logger.info("[模拟盘] 下单: side=%s stock=%s vol=%s price=%s FIX_PRICE", side, stock, volume, price)
        else:
            # ========== 实盘模式：文档标准写法 ==========
            if side == "buy":
                # 买入：FIX_PRICE + tick lastPrice（官方示例第909行）
                full_tick = xtdata.get_full_tick([stock])
                if not isinstance(full_tick, dict) or stock not in full_tick:
                    self.logger.error("[实盘] get_full_tick 无数据，跳过买入: stock=%s", stock)
                    return None
                price = float(full_tick[stock].get("lastPrice", 0))
                if price <= 0:
                    self.logger.error("[实盘] lastPrice 无效，跳过买入: stock=%s", stock)
                    return None
                oid = self.trader.order_stock(
                    self.account, stock, order_type, volume,
                    xtconstant.FIX_PRICE, price,
                    STRATEGY_ID, remark[:24],
                )
                self.logger.info("[实盘] 买入: stock=%s vol=%s price=%s FIX_PRICE", stock, volume, price)
            else:
                # 卖出：LATEST_PRICE + -1（官方示例第922行）
                oid = self.trader.order_stock(
                    self.account, stock, order_type, volume,
                    xtconstant.LATEST_PRICE, -1,
                    STRATEGY_ID, remark[:24],
                )
                self.logger.info("[实盘] 卖出: stock=%s vol=%s LATEST_PRICE", stock, volume)

        if oid is None or int(oid) <= 0:
            self.logger.error("下单失败: side=%s stock=%s volume=%s", side, stock, volume)
            return None
        self.state.setdefault("order_book", {})[str(oid)] = {
            "order_id": str(oid),
            "stock": stock,
            "side": side,
            "volume": volume,
            "filled": 0,
            "status": "submitted",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "remark": remark,
        }
        self.logger.info("下单提交成功: order_id=%s", oid)
        return str(oid)

    # ===== 多因子数据入口 =====
    def get_index_bars(self, code, count, fields, end_date):
        end_time = (end_date or "").replace("-", "")
        data = xtdata.get_market_data(
            field_list=list(fields),
            stock_list=[code],
            period="1d",
            count=count,
            end_time=end_time,
        )
        result = {}
        for field in fields:
            raw = data.get(field)
            if raw is None:
                result[field] = np.array([])
                continue
            try:
                if hasattr(raw, "columns") and code in raw.columns:
                    values = raw[code].values
                else:
                    values = raw.values if hasattr(raw, "values") else raw
                arr = np.asarray(values, dtype=float).reshape(-1)
                arr = arr[~np.isnan(arr)]
                result[field] = arr
            except Exception:
                result[field] = np.array([])
        return result

    def _load_stocks_from_file(self):
        if not os.path.exists(STOCK_POOL_FILE):
            return []
        stocks = []
        with open(STOCK_POOL_FILE, "r", encoding="utf-8-sig") as f:
            for line in f:
                s = normalize_stock_code(line.strip())
                if s:
                    stocks.append(s)
        return list(dict.fromkeys(stocks))

    def get_index_stocks(self, index_code, trade_date):
        """优先 xtdata.get_stock_list_in_sector；先试规范化后的指数代码，再试板块中文名等。"""
        _ = trade_date
        index_code = normalize_stock_code(index_code or INDEX_CODE)
        prefix = [index_code]
        if "." in index_code:
            bare = index_code.split(".", 1)[0]
            if bare and bare != index_code:
                prefix.append(bare)
        preset = INDEX_STOCK_LIST_SECTOR_CANDIDATES.get(index_code, [])
        candidates = list(dict.fromkeys(prefix + list(preset)))
        stocks = []
        fn = getattr(xtdata, "get_stock_list_in_sector", None)
        if fn:
            for sec in candidates:
                try:
                    raw = fn(sec)
                    if not raw:
                        continue
                    stocks = [normalize_stock_code(x) for x in raw if x]
                    if stocks:
                        self.logger.info("股票池来自 xtdata.get_stock_list_in_sector(%s) count=%s", sec, len(stocks))
                        break
                except Exception as exc:
                    self.logger.warning("get_stock_list_in_sector(%s) 异常: %s", sec, exc)
        if not stocks:
            self.logger.warning(
                "xtdata 未能取得指数成分 index=%s，已试 sector=%s。若无数据请先终端下载板块/指数权重。",
                index_code,
                candidates,
            )
            if USE_DATA_FILE_FALLBACK:
                stocks = self._load_stocks_from_file()
                if stocks:
                    self.logger.info("股票池回退为本地文件 count=%s", len(stocks))
        return stocks

    def _series_last_per_stock(self, data_dict, field, stock):
        """从 get_market_data 返回的 dict 中取某字段、某标的最新值。"""
        block = data_dict.get(field)
        if block is None:
            return np.nan
        try:
            if hasattr(block, "columns") and stock in block.columns:
                ser = block[stock]
                arr = np.asarray(ser.values if hasattr(ser, "values") else ser, dtype=float).reshape(-1)
                arr = arr[~np.isnan(arr)]
                return float(arr[-1]) if len(arr) else np.nan
        except Exception:
            pass
        return np.nan

    def _fetch_factor_frame_from_xtdata(self, stocks, trade_date):
        """用 xtdata.get_market_data 拉估值类字段，拼装 pe/pb/roe/market_cap。"""
        if not stocks:
            return None
        end_time = (trade_date or "").replace("-", "")
        field_groups = [
            ["pe_ttm", "pb_lf", "roe_avg", "total_market_value"],
            ["pe_ttm", "pb_mrq", "roe_ttm", "total_market_value"],
            ["pe_ttm", "pb_lf", "roe_ttm", "circulating_market_value"],
        ]
        rows = []
        chunk = 400
        for i in range(0, len(stocks), chunk):
            part = stocks[i : i + chunk]
            last_err = None
            data = None
            used_fields = None
            for fields in field_groups:
                try:
                    data = xtdata.get_market_data(
                        field_list=fields,
                        stock_list=part,
                        period="1d",
                        count=1,
                        end_time=end_time,
                    )
                    if not isinstance(data, dict):
                        continue
                    used_fields = fields
                    break
                except Exception as exc:
                    last_err = exc
                    data = None
            if data is None or used_fields is None:
                if last_err:
                    self.logger.warning("get_market_data 估值字段拉取失败 chunk=%s: %s", i, last_err)
                continue
            pe_field = used_fields[0]
            pb_field = used_fields[1]
            roe_field = used_fields[2]
            cap_field = used_fields[3]
            for stk in part:
                pe = self._series_last_per_stock(data, pe_field, stk)
                pb = self._series_last_per_stock(data, pb_field, stk)
                roe = self._series_last_per_stock(data, roe_field, stk)
                cap = self._series_last_per_stock(data, cap_field, stk)
                rows.append(
                    {
                        "code": normalize_stock_code(stk),
                        "pe": pe,
                        "pb": pb,
                        "roe": roe,
                        "market_cap": cap,
                    }
                )
        if not rows:
            return None
        df = pd.DataFrame(rows).set_index("code")
        return df

    def _load_factors_from_file(self, stocks, trade_date):
        date_tag = (trade_date or "").replace("-", "")
        file_path = FACTOR_FILE_PATTERN.format(date=date_tag)
        if not os.path.exists(file_path):
            self.logger.warning("因子文件不存在: %s", file_path)
            return None
        try:
            df = pd.read_csv(file_path)
            if "code" not in df.columns:
                self.logger.error("因子文件缺少 code 列: %s", file_path)
                return None
            df["code"] = df["code"].apply(normalize_stock_code)
            df = df[df["code"].isin(stocks)].copy()
            if df.empty:
                return None
            return df.set_index("code")
        except Exception as exc:
            self.logger.error("读取因子文件失败: %s", exc)
            return None

    def _finalize_factor_frame(self, df, stocks, trade_date):
        """统一派生 ep/bp/size，必要时补 lowvol。"""
        if df is None or df.empty:
            return None
        df = df.copy()
        if "ep" not in df.columns and "pe" in df.columns:
            df["ep"] = np.where(df["pe"] > 0, 1.0 / df["pe"], np.nan)
        if "bp" not in df.columns and "pb" in df.columns:
            df["bp"] = np.where(df["pb"] > 0, 1.0 / df["pb"], np.nan)
        if "size" not in df.columns and "market_cap" in df.columns:
            df["size"] = np.where(df["market_cap"] > 0, 1.0 / np.log(df["market_cap"]), np.nan)

        if "lowvol" not in df.columns:
            lowvol = {}
            for stk in df.index.tolist():
                if stk not in stocks:
                    continue
                raw = self.get_close_history([stk], 61, trade_date).get(stk)
                if raw is None:
                    lowvol[stk] = np.nan
                    continue
                try:
                    values = raw.values if hasattr(raw, "values") else raw
                    close = np.asarray(values, dtype=float).reshape(-1)
                    close = close[~np.isnan(close)]
                    if len(close) < 61:
                        lowvol[stk] = np.nan
                        continue
                    rets = np.diff(close) / close[:-1]
                    vol = np.std(rets) * np.sqrt(252)
                    lowvol[stk] = 1.0 / vol if vol > 0 else np.nan
                except Exception:
                    lowvol[stk] = np.nan
            df["lowvol"] = pd.Series(lowvol)
        return df

    def get_factor_frame(self, stocks, trade_date):
        """优先 xtdata 行情估值字段；失败或缺列且允许时读 CSV。"""
        df = self._fetch_factor_frame_from_xtdata(stocks, trade_date)
        if (df is None or df.empty) and USE_DATA_FILE_FALLBACK:
            self.logger.info("xtdata 因子表为空，尝试本地 CSV")
            file_df = self._load_factors_from_file(stocks, trade_date)
            if file_df is not None:
                df = file_df
        if df is None:
            return None
        df = df[df.index.isin(stocks)] if len(df.index) else df
        return self._finalize_factor_frame(df, stocks, trade_date)

