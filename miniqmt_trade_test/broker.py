# -*- coding: utf-8 -*-

import datetime as dt
import json
import os
import sys
import time

from config import (
    ACCOUNT_ID,
    ACCOUNT_TYPE,
    MIN_ORDER_VOLUME,
    QMT_PATH,
    STRATEGY_ID,
    XTQUANT_PATH,
)

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


def bare_stock_code(stock_code):
    """
    对于这个版本的 xtquant，很多接口只接受不带后缀的 "600000"，
    而不是带后缀的 "600000.SH"
    """
    code = normalize_stock_code(stock_code)
    if "." in code:
        return code.split(".", 1)[0]
    return code


def order_status_str(order):
    return str(getattr(order, "order_status", "") or "")


def order_is_cancellable(order):
    vol = int(getattr(order, "order_volume", 0) or 0)
    traded = int(getattr(order, "traded_volume", 0) or 0)
    if vol <= 0:
        return False
    if traded >= vol:
        return False
    st = order_status_str(order).lower()
    for done in (
        "filled",
        "cancel",
        "reject",
        "invalid",
        "已成",
        "已撤",
        "废单",
        "部撤",
        "拒绝",
    ):
        if done in st:
            return False
    return True


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


class TradeTestBroker:
    def __init__(self, log):
        self.log = log
        self.trader = None
        self.account = None

    def connect(self):
        session_id = int(time.time())
        self.trader = xttrader.XtQuantTrader(QMT_PATH, session_id)
        self.trader.start()
        ret = self.trader.connect()
        self.log.info("XtQuantTrader.connect => %s", ret)
        if ret != 0:
            raise RuntimeError("miniQMT 连接失败，请先登录终端")

        self.account = StockAccount(ACCOUNT_ID, ACCOUNT_TYPE)
        sub = self.trader.subscribe(self.account)
        self.log.info("subscribe(%s, %s) => %s", ACCOUNT_ID, ACCOUNT_TYPE, sub)
        if sub != 0:
            raise RuntimeError("账户订阅失败")

        if os.path.isdir(QMT_PATH) and hasattr(xtdata, "data_dir"):
            try:
                xtdata.data_dir = QMT_PATH
                self.log.info("xtdata.data_dir => %s", QMT_PATH)
            except Exception as exc:
                self.log.debug("设置 xtdata.data_dir: %s", exc)
        recon = getattr(xtdata, "reconnect", None)
        if recon:
            try:
                self.log.info("xtdata.reconnect => %s", recon())
            except Exception as exc:
                self.log.debug("xtdata.reconnect: %s", exc)

    def stop(self):
        if self.trader:
            self.trader.stop()
            self.trader = None

    def query_asset(self):
        return self.trader.query_stock_asset(self.account)

    def query_positions(self):
        return self.trader.query_stock_positions(self.account) or []

    def query_orders(self):
        return self.trader.query_stock_orders(self.account) or []

    def get_total_asset(self):
        asset = self.query_asset()
        if asset is None:
            return None
        v = getattr(asset, "total_asset", getattr(asset, "m_dTotalAsset", None))
        return float(v) if v is not None else None

    def get_cash(self):
        asset = self.query_asset()
        if asset is None:
            return None
        v = getattr(asset, "cash", getattr(asset, "m_dCash", None))
        return float(v) if v is not None else None

    def positions_dict(self):
        result = {}
        for pos in self.query_positions():
            code = normalize_stock_code(getattr(pos, "stock_code", ""))
            volume = int(getattr(pos, "volume", 0) or 0)
            can_use = int(getattr(pos, "can_use_volume", volume) or 0)
            market_value = float(getattr(pos, "market_value", 0) or 0)
            if code and volume > 0:
                result[code] = {"shares": volume, "can_use": can_use, "value": market_value}
        return result

    def snapshot(self):
        asset = self.query_asset()
        if asset is None:
            self.log.warning("query_stock_asset 返回 None")
        else:
            total = getattr(asset, "total_asset", getattr(asset, "m_dTotalAsset", None))
            cash = getattr(asset, "cash", getattr(asset, "m_dCash", None))
            self.log.info("总资产 total_asset=%s  现金 cash=%s", total, cash)
        pos = self.positions_dict()
        self.log.info("持仓数量: %s", len(pos))
        for c, p in sorted(pos.items()):
            self.log.info("  %s  vol=%s can_use=%s mv=%s", c, p["shares"], p["can_use"], p["value"])

    def dump_orders(self):
        orders = self.query_orders()
        self.log.info("委托条数: %s", len(orders))
        for o in orders:
            oid = getattr(o, "order_id", "")
            code = normalize_stock_code(getattr(o, "stock_code", ""))
            ot = int(getattr(o, "order_type", 0) or 0)
            side = "buy" if ot == xtconstant.STOCK_BUY else "sell"
            vol = int(getattr(o, "order_volume", 0) or 0)
            traded = int(getattr(o, "traded_volume", 0) or 0)
            st = order_status_str(o)
            self.log.info(
                "  id=%s %s %s vol=%s traded=%s status=%s",
                oid,
                side,
                code,
                vol,
                traded,
                st,
            )
        return orders

    def _xtdata_prepare_stock(self, stock):
        """下载并订阅日线、再订阅 tick（优先拿最新价），最后等一小会儿。"""
        stock = normalize_stock_code(stock)
        bare = bare_stock_code(stock)
        dl2 = getattr(xtdata, "download_history_data2", None)
        if dl2:
            try:
                dl2([bare], "1d", "", "")
            except TypeError:
                try:
                    dl2(stock_list=[bare], period="1d")
                except Exception as exc:
                    self.log.debug("download_history_data2 %s: %s", bare, exc)
            except Exception as exc:
                self.log.debug("download_history_data2 %s: %s", bare, exc)
        dl = getattr(xtdata, "download_history_data", None)
        if dl:
            try:
                dl(bare, period="1d", incrementally=True)
            except TypeError:
                try:
                    dl(bare, "1d", incrementally=True)
                except Exception as exc:
                    self.log.debug("download_history_data %s: %s", bare, exc)
            except Exception as exc:
                self.log.debug("download_history_data %s: %s", bare, exc)
        sub = getattr(xtdata, "subscribe_quote", None)
        if sub:
            try:
                sub(bare, period="1d", count=-1, dividend_type="none")
            except TypeError:
                try:
                    sub(bare, period="1d", count=-1)
                except Exception as exc:
                    self.log.debug("subscribe_quote 1d %s: %s", bare, exc)
            except Exception as exc:
                self.log.debug("subscribe_quote 1d %s: %s", bare, exc)
            try:
                sub(bare, period="tick", count=-1)
            except TypeError:
                try:
                    sub(stock_list=[bare], period="tick", count=-1)
                except Exception as exc:
                    self.log.debug("subscribe_quote tick %s: %s", bare, exc)
            except Exception as exc:
                self.log.debug("subscribe_quote tick %s: %s", bare, exc)
        time.sleep(0.8)

    def _last_close_from_market_dict(self, data, stock):
        """解析 get_market_data / get_local_data 返回：index 一般为股票，columns 为时间。"""
        if not isinstance(data, dict) or "close" not in data:
            return None
        block = data["close"]
        if block is None:
            return None
        ser = None
        try:
            if hasattr(block, "index") and stock in block.index:
                ser = block.loc[stock]
            elif hasattr(block, "columns") and stock in block.columns:
                ser = block[stock]
        except Exception:
            ser = None
        if ser is None:
            return None
        try:
            vals = ser.values if hasattr(ser, "values") else ser
            if hasattr(vals, "__iter__") and not isinstance(vals, (str, bytes)):
                seq = list(vals)
            else:
                seq = [vals]
        except Exception:
            return None
        for x in reversed(seq):
            try:
                v = float(x)
                if v == v and v > 0:
                    return v
            except Exception:
                continue
        return None

    def dump_quote(self, stock):
        """打印 xtdata 常用取价入口，便于对照 miniQMT（不是玩笑，接口名都在这里）。"""
        stock = normalize_stock_code(stock)
        bare = bare_stock_code(stock)
        self.log.info("=== 行情探测 %s (bare=%s) ===", stock, bare)
        self._xtdata_prepare_stock(stock)
        gi = getattr(xtdata, "get_instrument_detail", None)
        if gi:
            try:
                d = gi(bare, False)
                if isinstance(d, dict):
                    self.log.info(
                        "get_instrument_detail(False): PreClose=%s UpStop=%s DownStop=%s PriceTick=%s",
                        d.get("PreClose"),
                        d.get("UpStopPrice"),
                        d.get("DownStopPrice"),
                        d.get("PriceTick"),
                    )
            except Exception as exc:
                self.log.warning("get_instrument_detail: %s", exc)
        try:
            tick_raw = xtdata.get_full_tick([bare])
            tick = _parse_get_full_tick_result(tick_raw)
            self.log.info("get_full_tick keys: %s", list(tick.keys()))
            t = tick.get(bare) or tick.get(stock)
            if isinstance(t, dict):
                self.log.info(
                    "get_full_tick: lastPrice=%s preClose=%s upperLimit=%s lowerLimit=%s",
                    t.get("lastPrice"),
                    t.get("preClose"),
                    t.get("upperLimit"),
                    t.get("lowerLimit"),
                )
            else:
                self.log.info("get_full_tick: 无该标的字典 (raw type=%s)", type(tick_raw))
        except Exception as exc:
            self.log.warning("get_full_tick: %s", exc)
        # 日线最后一价（与股票/ETF策略 get_close_history 思路一致）
        px = None
        try:
            data = xtdata.get_market_data(
                field_list=["close"],
                stock_list=[bare],
                period="1d",
                count=3,
                end_time="",
                dividend_type="none",
                fill_data=True,
            )
            px = self._last_close_from_market_dict(data, bare)
            if not px:
                px = self._last_close_from_market_dict(data, stock)
            self.log.info("get_market_data(1d.close 末值): %s", px if px else "无效")
        except Exception as exc:
            self.log.warning("get_market_data: %s", exc)
        ref = self.get_latest_close(stock, require_tick=False)
        self.log.info("get_latest_close(封装顺序 tick→日K→本地): %s", ref if ref else "无效")

    def get_latest_close(self, stock, require_tick=True):
        """
        获取最新参考价：优先 tick.lastPrice，其次 get_instrument_detail.PreClose，
        最后日线收盘价。与官方示例「简单买卖各一笔」对齐。
        """
        stock = normalize_stock_code(stock)
        bare = bare_stock_code(stock)

        # 1. tick.lastPrice（官方示例写法）
        for i in range(3):
            try:
                tick_raw = xtdata.get_full_tick([bare])
                tick = _parse_get_full_tick_result(tick_raw)
                t = tick.get(bare) or tick.get(stock)
                if isinstance(t, dict):
                    lp = t.get("lastPrice") or t.get("last_price")
                    if lp not in (None, "", 0):
                        v = float(lp)
                        if v > 0:
                            self.log.info("参考价=tick.lastPrice %s=%.2f", stock, v)
                            return v
            except Exception:
                pass
            time.sleep(0.2)

        # 2. get_instrument_detail.PreClose（官方示例中 get_full_tick 失败后的降级）
        try:
            detail = xtdata.get_instrument_detail(stock)
            pre_close = None
            if isinstance(detail, dict):
                pre_close = detail.get("PreClose") or detail.get("preClose")
            elif detail and hasattr(detail, "PreClose"):
                pre_close = getattr(detail, "PreClose", 0)
            if pre_close and float(pre_close) > 0:
                self.log.info("参考价=PreClose %s=%.2f", stock, float(pre_close))
                return float(pre_close)
        except Exception:
            pass

        # 3. 日线收盘价
        try:
            data = xtdata.get_market_data(
                field_list=["close"],
                stock_list=[bare],
                period="1d",
                count=3,
                end_time="",
                dividend_type="none",
                fill_data=True,
            )
            px = self._last_close_from_market_dict(data, bare)
            if not px:
                px = self._last_close_from_market_dict(data, stock)
            if px and px > 0:
                self.log.info("参考价=get_market_data(1d) %s=%.2f", stock, px)
                return px
        except Exception:
            pass

        self.log.error("无法获取参考价: %s", stock)
        return 0

    def get_limit_bounds(self, stock):
        """
        返回 (跌停价, 涨停价)。优先 get_instrument_detail 官方 Up/DownStopPrice；
        其次 tick；再否则前收 ±10% 估算。
        """
        stock = normalize_stock_code(stock)
        cache = getattr(self, "_limit_bounds_cache", None)
        if cache is None:
            cache = {}
            self._limit_bounds_cache = cache
        if stock in cache:
            return cache[stock]

        self._xtdata_prepare_stock(stock)
        lo = hi = None

        gi = getattr(xtdata, "get_instrument_detail", None)
        if gi:
            try:
                for complete in (False, True):
                    d = gi(stock, complete)
                    if not isinstance(d, dict):
                        continue
                    down = d.get("DownStopPrice") or d.get("downStopPrice")
                    up = d.get("UpStopPrice") or d.get("upStopPrice")
                    if down not in (None, "", 0) and up not in (None, "", 0):
                        try:
                            lo, hi = float(down), float(up)
                            if lo > 0 and hi >= lo:
                                cache[stock] = (lo, hi)
                                self.log.info(
                                    "涨跌停来源=get_instrument_detail %s: %.2f ~ %.2f",
                                    stock,
                                    lo,
                                    hi,
                                )
                                return lo, hi
                        except (TypeError, ValueError):
                            lo = hi = None
                    pc = d.get("PreClose") or d.get("preClose")
                    if (lo is None or hi is None) and pc not in (None, "", 0):
                        try:
                            pcv = float(pc)
                            if pcv > 0:
                                lo = round(pcv * 0.9, 2)
                                hi = round(pcv * 1.1, 2)
                                self.log.info(
                                    "涨跌停来源=合约PreClose±10%% %s: 昨收=%.2f 估算 %.2f ~ %.2f",
                                    stock,
                                    pcv,
                                    lo,
                                    hi,
                                )
                                cache[stock] = (lo, hi)
                                return lo, hi
                        except (TypeError, ValueError):
                            pass
            except Exception as exc:
                self.log.debug("get_instrument_detail %s: %s", stock, exc)

        try:
            tick = xtdata.get_full_tick([stock])
            if isinstance(tick, dict) and stock in tick:
                t = tick[stock]
                if isinstance(t, dict):
                    pairs = [
                        ("lowerLimit", "upperLimit"),
                        ("lower_limit", "upper_limit"),
                        ("limitDown", "limitUp"),
                        ("downStopPrice", "upStopPrice"),
                    ]
                    for lk, hk in pairs:
                        if lk in t and hk in t:
                            try:
                                a, b = float(t[lk]), float(t[hk])
                                if a > 0 and b > 0 and b >= a:
                                    lo, hi = a, b
                                    break
                            except (TypeError, ValueError):
                                pass
                    if lo is None:
                        for k, v in t.items():
                            if v in (None, "", 0):
                                continue
                            ks = str(k)
                            try:
                                fv = float(v)
                                if fv <= 0:
                                    continue
                                if lo is None and ("跌停" in ks or "lower" in ks.lower()):
                                    lo = fv
                                if hi is None and ("涨停" in ks or "upper" in ks.lower()):
                                    hi = fv
                            except (TypeError, ValueError):
                                continue
                        if lo is not None and hi is not None and (lo > hi or lo <= 0):
                            lo, hi = None, None
        except Exception as exc:
            self.log.debug("get_limit_bounds tick %s: %s", stock, exc)
        if lo is None or hi is None:
            try:
                tick = xtdata.get_full_tick([stock])
                if isinstance(tick, dict) and stock in tick:
                    t = tick[stock]
                    if isinstance(t, dict):
                        pc = None
                        for key in ("lastClose", "preClose", "last_close", "prev_close"):
                            if key in t and t[key] not in (None, 0):
                                try:
                                    pc = float(t[key])
                                    break
                                except (TypeError, ValueError):
                                    pass
                        if pc and pc > 0:
                            lo = round(pc * 0.9, 2)
                            hi = round(pc * 1.1, 2)
                            self.log.info(
                                "涨跌停未取到精确值，暂按前收 %.2f 的 ±10%% 估算: 跌停=%s 涨停=%s",
                                pc,
                                lo,
                                hi,
                            )
            except Exception as exc:
                self.log.debug("get_limit_bounds fallback %s: %s", stock, exc)
        if lo is not None and hi is not None:
            cache[stock] = (lo, hi)
        return lo, hi

    def _clamp_price(self, side, px, stock, label="价"):
        lo, hi = self.get_limit_bounds(stock)
        if lo is None or hi is None:
            self.log.error(
                "无法取得 %s 涨跌停区间，已拒绝调整%s（避免柜台废单）。"
                "请确认 miniQMT 已登录、合约代码正确。",
                stock,
                label,
            )
            return None, (None, None)
        orig = float(px)
        c = max(lo, min(hi, orig))
        c = round(c, 2)
        if abs(c - orig) > 1e-6:
            self.log.warning(
                "%s %s 已按涨跌停钳位: %s -> %s (范围 %.2f ~ %.2f)",
                stock,
                label,
                orig,
                c,
                lo,
                hi,
            )
        return c, (lo, hi)

    def order_buy(self, stock, volume, remark="test_buy", ref_price=None):
        return self._order("buy", stock, volume, remark, ref_price=ref_price)

    def order_sell(self, stock, volume, remark="test_sell", ref_price=None):
        return self._order("sell", stock, volume, remark, ref_price=ref_price)

    def order_limit_buy(self, stock, volume, limit_price, remark="test_limit_buy"):
        """限价买入（用于悬挂单 + 撤单测试）。"""
        return self._order_fix("buy", stock, volume, float(limit_price), remark)

    def _order_fix(self, side, stock, volume, limit_price, remark):
        stock = normalize_stock_code(stock)
        volume = int(volume / 100) * 100
        if volume < MIN_ORDER_VOLUME:
            self.log.error("数量需 >= %s 且为 100 整数倍，当前: %s", MIN_ORDER_VOLUME, volume)
            return None
        try:
            raw_lp = float(limit_price)
        except (TypeError, ValueError):
            self.log.error("限价无效: %s", limit_price)
            return None
        if raw_lp <= 0:
            self.log.error("限价须为正: %s", limit_price)
            return None
        ot = xtconstant.STOCK_BUY if side == "buy" else xtconstant.STOCK_SELL
        limit_price, _ = self._clamp_price(side, raw_lp, stock, "限价")
        if limit_price is None:
            return None
        oid = self.trader.order_stock(
            self.account,
            stock,
            ot,
            volume,
            xtconstant.FIX_PRICE,
            limit_price,
            STRATEGY_ID,
            (remark or "")[:24],
        )
        try:
            ok = oid is not None and int(oid) > 0
        except (TypeError, ValueError):
            ok = False
        if not ok:
            self.log.error("限价单失败 side=%s stock=%s px=%s 返回值=%r", side, stock, limit_price, oid)
            return None
        self.log.info("限价单已提交 order_id=%s side=%s stock=%s vol=%s px=%s", oid, side, stock, volume, limit_price)
        return int(oid)

    def _order(self, side, stock, volume, remark, ref_price=None):
        """
        下单，完全对齐官方示例写法。
        买入：FIX_PRICE + ref_price（取最新价/PreClose）
        卖出：LATEST_PRICE + -1（市价）
        """
        stock = normalize_stock_code(stock)
        volume = int(volume / 100) * 100
        if volume < MIN_ORDER_VOLUME:
            self.log.error("数量需 >= %s 且为 100 整数倍，当前: %s", MIN_ORDER_VOLUME, volume)
            return None

        ref = float(ref_price) if ref_price is not None and float(ref_price) > 0 else None
        if ref is None:
            ref = self.get_latest_close(stock)
        if ref <= 0:
            self.log.error("无法取得参考价，拒绝下单: %s", stock)
            return None

        ot = xtconstant.STOCK_BUY if side == "buy" else xtconstant.STOCK_SELL

        if side == "buy":
            # 买入：限价，价格钳位到涨跌停区间
            price, _ = self._clamp_price(side, round(ref, 2), stock, "限价")
            if price is None:
                return None
            oid = self.trader.order_stock(
                self.account, stock, ot, volume,
                xtconstant.FIX_PRICE, price,
                STRATEGY_ID, (remark or "")[:24],
            )
        else:
            # 卖出：市价（官方示例写法：LATEST_PRICE + price=-1）
            oid = self.trader.order_stock(
                self.account, stock, ot, volume,
                xtconstant.LATEST_PRICE, -1,
                STRATEGY_ID, (remark or "")[:24],
            )

        try:
            ok = oid is not None and int(oid) > 0
        except (TypeError, ValueError):
            ok = False
        if not ok:
            self.log.error(
                "order_stock 失败 side=%s stock=%s vol=%s ref=%.4f 返回值=%r",
                side, stock, volume, ref, oid,
            )
            return None
        self.log.info(
            "order_stock 成功 order_id=%s side=%s stock=%s vol=%s ref=%.4f",
            oid, side, stock, volume, ref,
        )
        return int(oid)

    def cancel_order_id(self, order_id):
        try:
            ret = self.trader.cancel_order_stock(self.account, int(order_id))
            self.log.info("cancel_order_stock(%s) => %s", order_id, ret)
            return ret == 0
        except Exception as exc:
            self.log.error("撤单异常: %s", exc)
            return False

    def cancel_all_cancellable(self):
        n = 0
        for o in self.query_orders():
            if not order_is_cancellable(o):
                continue
            oid = getattr(o, "order_id", None)
            if oid is None:
                continue
            if self.cancel_order_id(oid):
                n += 1
        self.log.info("已尝试撤单 %s 笔", n)
        return n

    def plan_rebalance_equal(self, targets, total_asset=None, cash=None, slip_buffer=1.02):
        """仅打印调仓计划，不下单。targets 已规范化代码列表，等权。"""
        total_asset = total_asset if total_asset is not None else self.get_total_asset()
        cash = cash if cash is not None else self.get_cash()
        if total_asset is None or total_asset <= 0:
            self.log.error("总资产无效，无法规划")
            return
        if cash is None:
            cash = 0.0
        targets = [normalize_stock_code(t) for t in targets if t]
        targets = list(dict.fromkeys(targets))
        if not targets:
            self.log.error("目标为空")
            return
        w = 1.0 / len(targets)
        weights = [w] * len(targets)
        positions = self.positions_dict()
        target_set = set(targets)
        self.log.info("[dry] total_asset=%s cash=%s targets=%s 等权=%.4f", total_asset, cash, len(targets), w)

        self.log.info("[dry] --- 拟卖出 ---")
        for stock, pos in sorted(positions.items()):
            shares = int(pos.get("can_use", pos.get("shares", 0)) / 100) * 100
            if shares < 100:
                continue
            if stock not in target_set:
                self.log.info("  清仓非目标 sell %s vol>=%s", stock, shares)
                continue
            idx = targets.index(stock)
            price = self.get_latest_close(stock)
            if price <= 0:
                self.log.info("  调减 %s 无法取价，跳过手数计算", stock)
                continue
            target_value = total_asset * float(weights[idx])
            target_shares = int(target_value / price / 100) * 100
            delta = target_shares - int(pos.get("shares", 0))
            if delta <= -100:
                self.log.info("  调减 sell %s delta=%s (目标股数=%s)", stock, abs(delta), target_shares)

        self.log.info("[dry] --- 拟买入 ---")
        for stock, weight in zip(targets, weights):
            price = self.get_latest_close(stock)
            if price <= 0:
                self.log.info("  buy %s 无法取价", stock)
                continue
            target_value = total_asset * float(weight)
            current_shares = int(positions.get(stock, {}).get("shares", 0))
            target_shares = int(target_value / price / 100) * 100
            delta = target_shares - current_shares
            max_affordable = int(cash * 0.98 / price / 100) * 100
            buy_shares = min(delta, max_affordable) if delta > 0 else 0
            if buy_shares >= 100:
                self.log.info(
                    "  buy %s delta=%s buy_shares=%s (目标市值=%.0f)",
                    stock,
                    delta,
                    buy_shares,
                    target_value,
                )
            elif delta >= 100:
                self.log.info(
                    "  buy %s 需要 %s 股但现金仅能 %s 股",
                    stock,
                    delta,
                    max_affordable,
                )
            else:
                self.log.info("  buy %s 无需加仓 (delta=%s)", stock, delta)
