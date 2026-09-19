"""Web dashboard server for the existing Hyperliquid monitor."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import mimetypes
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .config import Config, load_config, normalize_address
from .hunter import _build_coin_dex_map
from .brief import cluster_open_orders, interval_stats
from .format import AMOUNT_STYLES, set_amount_style
from .monitor import AddressMonitor
from .net import build_opener
from .state import WEB_CHAT_ID, EventStore
from .whale import (
    DEFAULT_EXCLUDE_LABEL_KEYWORDS,
    DEFAULT_EXCLUDE_TAGS,
    ConcentrationReport,
    WhaleWatcher,
    build_adapters,
    is_exchange_label,
    is_native_token,
    parse_config_labels,
    resolve_token,
    scan_token,
    search_tokens,
)


STATIC_DIR = Path(__file__).with_name("web_static")
CHART_INTERVALS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}
FILL_WINDOWS = {
    5: "5分钟",
    15: "15分钟",
    60: "1小时",
    240: "4小时",
    1440: "1天",
    4320: "3天",
    10080: "1周",
}
AUTOHUNT_POSITION_CLUSTER_PCT = 0.01


def _json_safe(value):
    """把 NaN/Infinity 等非有限浮点数转成 null，保证响应是合法 JSON。"""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value

class _NoNotifications:
    def notify(self, event):
        return None


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class WebApp:
    def __init__(self, config: Config):
        self.config = config
        self.store = EventStore(str(config.db_path))
        self.monitor = AddressMonitor(
            config,
            store=self.store,
            notifier=_NoNotifications(),
        )
        self.web_chat_id = WEB_CHAT_ID
        self.chart_cache = {}
        self.chart_cache_ttl = 15.0
        self.whale_cache = {}
        self.whale_cache_ttl = 60.0
        self._holder_adapter_cache = None
        self.holder_scan_cache = {}
        self.holder_scan_ttl = 60.0
        self._config_proxy_url = config.proxy_url
        self.apply_settings()

    def close(self):
        self.store.close()

    def accounts(self):
        """仪表盘展示的账户 = config.toml 里的地址 + 所有聊天订阅的并集。

        Telegram 里的 /add 是把地址挂在各自的 chat_id 下，如果这里只看
        __web__，机器人加的地址在网页上就完全看不到。
        """
        merged = {}
        for address in self.config.addresses:
            merged[address] = {"alias": "", "chats": set(), "configured": True}
        for row in self.store.get_subscriptions(active_only=False):
            address = str(row.get("address") or "").lower()
            if not address:
                continue
            item = merged.setdefault(
                address, {"alias": "", "chats": set(), "configured": False}
            )
            item["chats"].add(str(row.get("chat_id")))
            alias = str(row.get("alias") or "").strip()
            if alias and not item["alias"]:
                item["alias"] = alias

        result = []
        for address, meta in sorted(merged.items()):
            chats = meta["chats"]
            if meta["configured"]:
                source = "config"
            elif self.web_chat_id in chats and len(chats) > 1:
                source = "both"
            elif self.web_chat_id in chats:
                source = "web"
            else:
                source = "telegram"
            result.append(
                {
                    "address": address,
                    "alias": meta["alias"],
                    "source": source,
                    "chat_count": len(chats),
                }
            )
        return result

    def account(self, raw_address):
        address = normalize_address(raw_address)
        return next((item for item in self.accounts() if item["address"] == address), None)

    def add_account(self, raw_address, alias=""):
        address = normalize_address(raw_address)
        self.monitor.api.clearinghouse_state(address)
        self.store.subscribe(self.web_chat_id, address, alias)
        return self.account(address)

    def remove_account(self, raw_address):
        address = normalize_address(raw_address)
        item = self.account(address)
        if item is None:
            raise KeyError("account not found")
        if item["source"] == "config":
            raise PermissionError("configured accounts are removed in config.toml")
        # 仪表盘看到的是全部订阅，删除时也一并清掉，否则 Telegram 那边
        # 还会继续监控，界面却显示已移除。
        removed = self.store.delete_subscriptions_by_address(address)
        item["removed_chats"] = removed
        return item

    def autohunt_processes(self):
        """Return lightweight Autohunt process metadata for selectors."""
        rows = []
        for entry in self.store.all_autohunt_configs():
            settings = entry.get("settings") or {}
            chat_id = entry["chat_id"]
            name = entry["name"]
            rows.append(
                {
                    "name": name,
                    "account_count": len(self.store.get_auto_accounts(chat_id, name)),
                    "enabled": str(settings.get("enabled")) == "1",
                    "running": str(settings.get("progress_running")) == "1",
                }
            )
        rows.sort(key=lambda row: (not row["enabled"], row["name"].lower()))
        return rows

    def overview_data(self, raw_address):
        address = normalize_address(raw_address)
        data = self.monitor.snapshot_data(address)
        positions = []
        for coin, row in data.get("positions", {}).items():
            positions.append(
                {
                    "coin": coin,
                    "szi": _num(row.get("szi")),
                    "entry": row.get("entry_px", ""),
                    "notional": abs(_num(row.get("notional"))),
                    "pnl": _num(row.get("unrealized_pnl")),
                    "leverage": row.get("leverage", ""),
                    "open_time": int(row.get("open_time_ms") or 0),
                }
            )
        positions.sort(key=lambda row: row["notional"], reverse=True)
        spot = [
            {"coin": coin, "total": _num(row.get("total")), "hold": _num(row.get("hold"))}
            for coin, row in data.get("spot_balances", {}).items()
            if abs(_num(row.get("total"))) > 0
        ]
        spot.sort(key=lambda row: row["total"], reverse=True)
        return {
            "type": "overview",
            "address": address,
            "summary": data.get("summary", {}),
            "positions": positions,
            "spot": spot,
            "generated_at": int(time.time() * 1000),
        }

    def fills_data(self, raw_address, raw_window="1440"):
        address = normalize_address(raw_address)
        try:
            window_min = int(raw_window)
        except (TypeError, ValueError):
            window_min = 1440
        if window_min not in FILL_WINDOWS:
            window_min = 1440

        now_ms = int(time.time() * 1000)
        start_ms = now_ms - window_min * 60_000
        raw_fills = self.monitor.api.user_fills_by_time(address, start_ms, now_ms + 1000)
        fills = sorted(
            raw_fills or [],
            key=lambda row: int(row.get("time") or 0),
            reverse=True,
        )[:5000]

        by_coin = {}
        buy_value = 0.0
        sell_value = 0.0
        realized = 0.0
        for fill in fills:
            coin = str(fill.get("coin") or "?")
            size = abs(_num(fill.get("sz")))
            price = _num(fill.get("px"))
            notional = size * price
            pnl = _num(fill.get("closedPnl"))
            realized += pnl
            side = str(fill.get("side") or "").upper()
            if side == "B":
                buy_value += notional
            elif side == "A":
                sell_value += notional

            stats = by_coin.setdefault(
                coin,
                {"coin": coin, "count": 0, "notional": 0.0, "buy": 0.0, "sell": 0.0, "pnl": 0.0},
            )
            stats["count"] += 1
            stats["notional"] += notional
            stats["pnl"] += pnl
            if side == "B":
                stats["buy"] += notional
            elif side == "A":
                stats["sell"] += notional

        recent = []
        for fill in fills[:100]:
            size = abs(_num(fill.get("sz")))
            price = _num(fill.get("px"))
            recent.append(
                {
                    "time": int(fill.get("time") or 0),
                    "coin": str(fill.get("coin") or "?"),
                    "dir": str(fill.get("dir") or ""),
                    "side": str(fill.get("side") or ""),
                    "size": size,
                    "price": price,
                    "notional": size * price,
                    "closed_pnl": _num(fill.get("closedPnl")),
                    "fee": _num(fill.get("fee")),
                }
            )

        coins = sorted(by_coin.values(), key=lambda row: row["notional"], reverse=True)
        return {
            "type": "fills",
            "address": address,
            "window_min": window_min,
            "window_label": FILL_WINDOWS[window_min],
            "count": len(fills),
            "notional": buy_value + sell_value,
            "buy": buy_value,
            "sell": sell_value,
            "realized_pnl": realized,
            "coins": coins,
            "recent": recent,
            "generated_at": now_ms,
        }

    def report_data(self, report_type, raw_address, level="auto"):
        address = normalize_address(raw_address)
        if report_type == "orders":
            if level not in {"fine", "auto", "coarse"}:
                level = "auto"
            html = self.monitor.open_orders_report(address, level=level)
        elif report_type == "tpsl":
            html = self.monitor.tpsl_report(address)
        elif report_type == "history":
            html = self.monitor.history_report(address)
        else:
            raise ValueError("unknown report type")
        return {
            "type": "report",
            "report_type": report_type,
            "address": address,
            "level": level,
            "html": html,
            "generated_at": int(time.time() * 1000),
        }


    def chart_data(self, raw_address, raw_coin, raw_interval="15m", fill_window_min=1440, whale=False, proc="", merge=1.0, whale_orders=True, whale_fills=True, whale_positions=False):
        address = normalize_address(raw_address)
        coin = str(raw_coin or "BTC").strip()
        interval = str(raw_interval or "15m").strip()
        if interval not in CHART_INTERVALS:
            interval = "15m"
        try:
            fill_window_min = int(fill_window_min)
        except (TypeError, ValueError):
            fill_window_min = 1440
        fill_window_min = min(max(fill_window_min, 60), 10080)
        try:
            merge = float(merge)
        except (TypeError, ValueError):
            merge = 1.0
        merge = min(max(merge, 0.25), 4.0)
        cache_key = (
            address, coin, interval, fill_window_min, bool(whale), str(proc or ""),
            round(merge, 3), bool(whale_orders), bool(whale_fills), bool(whale_positions),
        )
        cached = self.chart_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < self.chart_cache_ttl:
            return cached[1]
        now_ms = int(time.time() * 1000)
        candle_start = now_ms - CHART_INTERVALS[interval] * 500
        try:
            candles = self.monitor.api._post(
                {
                    "type": "candleSnapshot",
                    "req": {
                        "coin": coin,
                        "interval": interval,
                        "startTime": candle_start,
                        "endTime": now_ms + 1000,
                    },
                }
            ) or []
        except Exception:
            candles = []

        theme = self.settings_values()
        up_color = theme.get("up_color") or "#1d8f70"
        down_color = theme.get("down_color") or "#b54848"

        candle_rows = []
        volume_rows = []
        for row in candles:
            open_time = int(row.get("t") or 0)
            open_px = _num(row.get("o"))
            high_px = _num(row.get("h"))
            low_px = _num(row.get("l"))
            close_px = _num(row.get("c"))
            volume = _num(row.get("v"))
            if not open_time or min(open_px, high_px, low_px, close_px) <= 0:
                continue
            timestamp = open_time // 1000
            candle_rows.append(
                {"time": timestamp, "open": open_px, "high": high_px, "low": low_px, "close": close_px}
            )
            volume_rows.append(
                {
                    "time": timestamp,
                    "value": volume,
                    "color": up_color if close_px >= open_px else down_color,
                }
            )

        mids = {}
        try:
            mids = self.monitor.api.all_mids() or {}
        except Exception:
            pass
        try:
            current_price = float(mids.get(coin) or 0)
        except (TypeError, ValueError):
            current_price = 0.0

        state = {}
        try:
            state = self.monitor.api.clearinghouse_state(address) or {}
        except Exception:
            pass
        position = None
        for item in state.get("assetPositions") or []:
            info = item.get("position") or item
            if str(info.get("coin")) != coin:
                continue
            position = {
                "side": "做多" if _num(info.get("szi")) > 0 else "做空",
                "size": abs(_num(info.get("szi"))),
                "entry": _num(info.get("entryPx")),
                "notional": abs(_num(info.get("positionValue"))),
                "pnl": _num(info.get("unrealizedPnl")),
                "leverage": (info.get("leverage") or {}).get("value") if isinstance(info.get("leverage"), dict) else info.get("leverage"),
            }

        orders = []
        try:
            orders = self.monitor.api.frontend_open_orders(address) or []
        except Exception:
            pass
        coin_orders = [order for order in orders if str(order.get("coin")) == coin]
        normal_orders = [
            order for order in coin_orders
            if not (order.get("isTrigger") or order.get("isPositionTpsl"))
        ]
        tpsl_orders = self.monitor._extract_tpsl_orders(coin_orders)

        order_zones = []
        for cluster in cluster_open_orders(normal_orders, max_gap_pct=0.25, width_multiplier=3.0, scale=merge):
            stats = interval_stats(cluster)
            order_zones.append(
                {
                    **stats,
                    "kind": "order",
                    "side_raw": "B" if str(cluster[0].get("side")).upper() == "B" else "A",
                }
            )

        tpsl_lines = []
        for order in tpsl_orders:
            price = _num(order.get("triggerPx"))
            if price <= 0:
                continue
            size = _num(order.get("sz")) or _num(order.get("origSz"))
            tpsl_lines.append(
                {
                    "price": price,
                    "side": "卖出" if str(order.get("side")).upper() == "A" else "买入",
                    "label": "止盈" if "Take Profit" in str(order.get("orderType")) else "止损",
                    "size": abs(size),
                    "notional": abs(size) * current_price if size and current_price else 0.0,
                    "position_tpsl": bool(order.get("isPositionTpsl")),
                }
            )

        fills = None
        for attempt in range(3):
            try:
                fills = self.monitor.api.user_fills_by_time(
                    address, now_ms - fill_window_min * 60_000, now_ms + 1000
                ) or []
                break
            except Exception:
                fills = None
                time.sleep(0.4 * (attempt + 1))
        fills_ok = fills is not None
        if not fills_ok:
            fills = []
        coin_fills = [fill for fill in fills if str(fill.get("coin")) == coin]

        fill_zones = []
        groups = {}
        for fill in coin_fills:
            side = str(fill.get("side") or "").upper()
            if side not in {"B", "A"}:
                continue
            direction = str(fill.get("dir") or "")
            groups.setdefault((side, direction), []).append(fill)
        for (side, direction), group in groups.items():
            group = sorted(group, key=lambda row: _num(row.get("px")))
            clusters = []
            current = []
            for fill in group:
                price = _num(fill.get("px"))
                if current:
                    last_price = _num(current[-1].get("px"))
                    first_price = _num(current[0].get("px"))
                    gap_pct = (price - last_price) / last_price * 100 if last_price else 0
                    width_pct = (price - first_price) / first_price * 100 if first_price else 0
                    if gap_pct > 0.25 or width_pct > 0.75:
                        clusters.append(current)
                        current = []
                current.append(fill)
            if current:
                clusters.append(current)

            for cluster in clusters:
                prices = [_num(row.get("px")) for row in cluster]
                sizes = [abs(_num(row.get("sz"))) for row in cluster]
                total_size = sum(sizes)
                total_value = sum(p * s for p, s in zip(prices, sizes))
                last_time = max(int(row.get("time") or 0) for row in cluster)
                if len(cluster) == 1 and last_time < now_ms - 15 * 60_000:
                    continue
                fill_zones.append(
                    {
                        "kind": "fill",
                        "side": "买入" if side == "B" else "卖出",
                        "side_raw": side,
                        "dir": direction,
                        "dir_counts": {direction: len(cluster)},
                        "count": len(cluster),
                        "min_px": min(prices),
                        "max_px": max(prices),
                        "avg_px": total_value / total_size if total_size else (min(prices) + max(prices)) / 2,
                        "total_sz": total_size,
                        "total_value": total_value,
                        "first_time": min(int(row.get("time") or 0) for row in cluster),
                        "last_time": last_time,
                    }
                )

        symbols = [coin]
        for item in state.get("assetPositions") or []:
            info = item.get("position") or item
            symbol = str(info.get("coin") or "")
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        for order in orders:
            symbol = str(order.get("coin") or "")
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        symbols = symbols[:40]

        result = {
            "type": "chart",
            "address": address,
            "coin": coin,
            "interval": interval,
            "fill_window_min": fill_window_min,
            "symbols": symbols,
            "candles": candle_rows,
            "volumes": volume_rows,
            "current_price": current_price,
            "position": position,
            "order_zones": sorted(order_zones, key=lambda row: row["total_value"], reverse=True),
            "fill_zones": sorted(fill_zones, key=lambda row: row["last_time"], reverse=True),
            "tpsl_lines": tpsl_lines,
            "generated_at": now_ms,
            "whale_process": "",
            "whale_account_count": 0,
            "whale_zones": [],
            "whale_order_zones": [],
            "whale_fill_zones": [],
            "whale_positions": [],
        }
        if whale:
            try:
                whale_data = self.whale_zones(
                    proc, coin, merge, fill_window_min,
                    include_orders=bool(whale_orders),
                    include_fills=bool(whale_fills),
                    include_positions=bool(whale_positions),
                )
            except Exception as exc:
                print(f"[web] whale zones failed: {exc}")
                whale_data = None
            if whale_data:
                result["whale_process"] = whale_data["process"]
                result["whale_account_count"] = whale_data["account_count"]
                result["whale_zones"] = whale_data["order_zones"]
                result["whale_order_zones"] = whale_data["order_zones"]
                result["whale_fill_zones"] = whale_data["fill_zones"]
                result["whale_positions"] = whale_data["positions"]
        if fills_ok:
            self.chart_cache[cache_key] = (time.monotonic(), result)
        return result

    def _autohunt_account_positions(self, address):
        state = self.monitor.api.clearinghouse_state(address) or {}
        rows = []
        for item in state.get("assetPositions") or []:
            if not isinstance(item, dict):
                continue
            position = item.get("position") or item
            coin = str(position.get("coin") or "").strip()
            szi = _num(position.get("szi"))
            if not coin or abs(szi) <= 0:
                continue
            leverage = position.get("leverage") or {}
            if isinstance(leverage, dict):
                leverage = leverage.get("value")
            rows.append(
                {
                    "coin": coin,
                    "side": "做多" if szi > 0 else "做空",
                    "szi": szi,
                    "size": abs(szi),
                    "entry": _num(position.get("entryPx")),
                    "notional": abs(_num(position.get("positionValue", position.get("notional")))),
                    "pnl": _num(position.get("unrealizedPnl")),
                    "leverage": _num(leverage),
                    "margin": _num(position.get("marginUsed")),
                }
            )
        return rows

    @staticmethod
    def _cluster_autohunt_positions(rows):
        groups = []
        ordered = sorted(
            rows,
            key=lambda row: (
                str(row.get("coin") or ""),
                str(row.get("side") or ""),
                _num(row.get("entry")),
            ),
        )
        for row in ordered:
            coin = str(row.get("coin") or "")
            side = str(row.get("side") or "")
            entry = _num(row.get("entry"))
            weight = abs(_num(row.get("szi"))) or 1.0
            match = None
            for group in reversed(groups):
                if group["coin"] != coin or group["side"] != side:
                    continue
                anchor = group["entry_total"] / group["weight"] if group["weight"] else 0.0
                if not anchor or abs(entry - anchor) / abs(anchor) <= AUTOHUNT_POSITION_CLUSTER_PCT:
                    match = group
                    break
                if group["entry"] < entry:
                    break
            if match is None:
                match = {
                    "coin": coin,
                    "side": side,
                    "entry": entry,
                    "entry_total": 0.0,
                    "weight": 0.0,
                    "szi": 0.0,
                    "notional": 0.0,
                    "pnl": 0.0,
                    "leverage_total": 0.0,
                    "leverage_weight": 0.0,
                    "margin": 0.0,
                    "accounts": set(),
                }
                groups.append(match)
            match["entry_total"] += entry * weight
            match["weight"] += weight
            match["szi"] += _num(row.get("szi"))
            match["notional"] += abs(_num(row.get("notional")))
            match["pnl"] += _num(row.get("pnl"))
            notional = abs(_num(row.get("notional")))
            leverage = _num(row.get("leverage"))
            match["leverage_total"] += leverage * notional
            match["leverage_weight"] += notional
            match["margin"] += _num(row.get("margin"))
            account = str(row.get("account") or "").strip()
            if account:
                match["accounts"].add(account)

        result = []
        for group in groups:
            accounts = sorted(group["accounts"])
            result.append(
                {
                    "coin": group["coin"],
                    "side": group["side"],
                    "szi": group["szi"],
                    "size": abs(group["szi"]),
                    "entry": group["entry_total"] / group["weight"] if group["weight"] else 0.0,
                    "notional": group["notional"],
                    "pnl": group["pnl"],
                    "leverage": group["leverage_total"] / group["leverage_weight"] if group["leverage_weight"] else 0.0,
                    "margin": group["margin"],
                    "account_count": len(accounts),
                    "accounts": accounts,
                }
            )
        result.sort(key=lambda row: row["notional"], reverse=True)
        return result
    def autohunt_data(self):
        now_ms = int(time.time() * 1000)
        processes = []
        for entry in self.store.all_autohunt_configs():
            chat_id = entry["chat_id"]
            name = entry["name"]
            settings = entry["settings"]

            coins = []
            raw_coins = settings.get("coins")
            if raw_coins:
                try:
                    parsed = json.loads(raw_coins)
                    if isinstance(parsed, list) and parsed:
                        coins = sorted({str(c).upper() for c in parsed})
                except (TypeError, ValueError):
                    coins = []

            def as_int(field, default):
                try:
                    return int(float(str(settings.get(field, default))))
                except (TypeError, ValueError):
                    return default

            def as_float(field, default):
                try:
                    return float(str(settings.get(field, default)))
                except (TypeError, ValueError):
                    return default

            limit = max(1, as_int("limit", 20))
            interval_h = max(1.0, as_float("interval_h", 6.0))
            last_run = max(0, as_int("last_run", 0))
            enabled = str(settings.get("enabled")) == "1"
            running = str(settings.get("progress_running")) == "1"
            done = max(0, as_int("progress_done", 0))
            total = max(0, as_int("progress_total", 0))
            accounts = self.store.get_auto_accounts(chat_id, name)
            next_run = 0
            if enabled and not running and last_run:
                next_run = last_run + int(interval_h * 3600000)

            processes.append(
                {
                    "name": name,
                    "chat_id": chat_id,
                    "coins": coins,
                    "limit": limit,
                    "interval_h": interval_h,
                    "enabled": enabled,
                    "running": running,
                    "last_run": last_run,
                    "next_run": next_run,
                    "progress_done": done,
                    "progress_total": total,
                    "account_count": len(accounts),
                    "accounts": accounts,
                }
            )

        addresses = sorted(
            {
                str(account.get("address") or "").lower()
                for process in processes
                for account in process.get("accounts") or []
                if account.get("address")
            }
        )

        def fetch_positions(address):
            try:
                return address, self._autohunt_account_positions(address)
            except Exception as exc:
                print(f"[web] autohunt positions failed for {address}: {exc}")
                return address, []

        positions_by_address = {}
        if addresses:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(addresses))) as pool:
                for address, positions in pool.map(fetch_positions, addresses):
                    positions_by_address[address] = positions

        for process in processes:
            enriched = []
            for account in process.get("accounts") or []:
                address = str(account.get("address") or "").lower()
                owner = str(account.get("alias") or "").strip() or address[:6] + "..." + address[-4:]
                for position in positions_by_address.get(address, []):
                    row = dict(position)
                    row["account"] = owner
                    enriched.append(row)
            process["positions"] = self._cluster_autohunt_positions(enriched)
            process["position_count"] = len(enriched)
        processes.sort(key=lambda row: (not row["enabled"], -row["last_run"], row["name"]))
        return {
            "type": "autohunt",
            "processes": processes,
            "collected": self.store.get_collected_accounts(),
            "generated_at": now_ms,
        }
    def whale_zones(self, proc_name, coin, merge=1.0, fill_window_min=1440, include_orders=True, include_fills=True, include_positions=False, kind="all"):
        """聚合 autohunt 收集账户在该币种上的普通挂单区间。"""
        configs = self.store.all_autohunt_configs()
        if not configs:
            return None
        kind = str(kind or "all").lower()
        if kind not in {"orders", "fills", "positions", "all"}:
            kind = "all"
        include_orders = bool(include_orders) and kind in {"orders", "all"}
        include_fills = bool(include_fills) and kind in {"fills", "all"}
        include_positions = bool(include_positions) and kind in {"positions", "all"}
        picked = None
        wanted = str(proc_name or "").strip().lower()
        if wanted:
            picked = next((c for c in configs if c["name"].lower() == wanted), None)
        picked = picked or configs[0]
        name = picked["name"]
        chat_id = picked["chat_id"]

        cache_key = (
            name, coin, round(float(merge), 3), int(fill_window_min),
            bool(include_orders), bool(include_fills), bool(include_positions),
        )
        cached = self.whale_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < self.whale_cache_ttl:
            return cached[1]

        accounts = self.store.get_auto_accounts(chat_id, name)[:40]
        addresses = [str(a.get("address") or "") for a in accounts if a.get("address")]
        api = self.monitor.api
        account_labels = {
            str(account.get("address") or "").lower(): (
                str(account.get("alias") or "").strip()
                or str(account.get("address") or "")[:6]
                + "..."
                + str(account.get("address") or "")[-4:]
            )
            for account in accounts
        }

        dexes = set()
        try:
            dex_map = _build_coin_dex_map(api)
            dexes.update(dex_map.get(str(coin).upper(), set()))
        except Exception:
            pass
        if not dexes:
            dexes.add("")

        now_ms = int(time.time() * 1000)
        fill_start = now_ms - max(60, int(fill_window_min)) * 60_000

        def fetch(address):
            collected_orders = []
            collected_fills = []
            positions = []
            if include_orders:
                for dex in sorted(dexes):
                    try:
                        orders = (
                            api.frontend_open_orders(address)
                            if dex == ""
                            else api.frontend_open_orders(address, dex)
                        )
                    except Exception:
                        orders = []
                    collected_orders.extend(orders or [])

            if include_fills:
                try:
                    collected_fills = api.user_fills_by_time(
                        address, fill_start, now_ms + 1000
                    ) or []
                except Exception:
                    collected_fills = []

            if include_positions:
                try:
                    positions = self._autohunt_account_positions(address)
                except Exception:
                    positions = []
            return collected_orders, collected_fills, positions

        flat = []
        fill_flat = []
        position_rows = []
        if addresses:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(addresses))) as pool:
                for address, result in zip(addresses, pool.map(fetch, addresses)):
                    orders, account_fills, account_positions = result
                    for fill in account_fills or []:
                        fill["_account"] = address
                        fill_flat.append(fill)
                    for position in account_positions or []:
                        raw_coin = str(position.get("coin") or "")
                        symbol = (
                            raw_coin.rsplit(":", 1)[-1].upper()
                            if ":" in raw_coin else raw_coin.upper()
                        )
                        if symbol != str(coin).upper():
                            continue
                        item = dict(position)
                        item["account"] = account_labels.get(
                            str(address).lower(), str(address)[:6] + "..." + str(address)[-4:]
                        )
                        position_rows.append(item)

                    for order in orders:
                        if order.get("isTrigger") or order.get("isPositionTpsl"):
                            continue
                        raw_coin = str(order.get("coin") or "")
                        symbol = raw_coin.rsplit(":", 1)[-1].upper() if ":" in raw_coin else raw_coin.upper()
                        if symbol != str(coin).upper():
                            continue
                        try:
                            px = float(order.get("limitPx") or 0)
                            size = float(order.get("sz") or 0)
                        except (TypeError, ValueError):
                            continue
                        if px <= 0 or size <= 0:
                            continue
                        item = dict(order)
                        item["coin"] = symbol
                        item["_account"] = address
                        flat.append(item)

        rows = []
        for cluster in cluster_open_orders(flat, max_gap_pct=0.25, width_multiplier=3.0, scale=merge):
            stats = interval_stats(cluster)
            accounts_in = {str(o.get("_account") or "") for o in cluster}
            if len(cluster) < 3 and len(accounts_in) < 2 and stats["total_value"] < 200_000:
                continue
            rows.append(
                {
                    "kind": "whale",
                    "side": stats["side"],
                    "side_raw": "B" if str(cluster[0].get("side")).upper() == "B" else "A",
                    "count": len(cluster),
                    "accounts": len(accounts_in),
                    "min_px": stats["min_px"],
                    "max_px": stats["max_px"],
                    "avg_px": stats["avg_px"],
                    "total_sz": stats["total_sz"],
                    "total_value": stats["total_value"],
                }
            )
        fill_groups = {}
        for fill in fill_flat:
            raw_coin = str(fill.get("coin") or "")
            symbol = raw_coin.rsplit(":", 1)[-1].upper() if ":" in raw_coin else raw_coin.upper()
            if symbol != str(coin).upper():
                continue
            side = str(fill.get("side") or "").upper()
            direction = str(fill.get("dir") or "")
            try:
                px = float(fill.get("px") or 0)
                size = float(fill.get("sz") or 0)
            except (TypeError, ValueError):
                continue
            if side not in {"B", "A"} or px <= 0 or size <= 0:
                continue
            item = dict(fill)
            item["_px"] = px
            item["_account"] = str(fill.get("_account") or "")
            item["_size"] = size
            fill_groups.setdefault((side, direction), []).append(item)

        fill_zones = []
        for (side, direction), group in fill_groups.items():
            group = sorted(group, key=lambda row: row["_px"])
            clusters = []
            current = []
            for row in group:
                px = row["_px"]
                if current:
                    last_px = current[-1]["_px"]
                    first_px = current[0]["_px"]
                    gap_pct = (px - last_px) / last_px * 100 if last_px else 0
                    width_pct = (px - first_px) / first_px * 100 if first_px else 0
                    if gap_pct > 0.25 * merge or width_pct > 0.75 * merge:
                        clusters.append(current)
                        current = []
                current.append(row)
            if current:
                clusters.append(current)

            for cluster in clusters:
                prices = [row["_px"] for row in cluster]
                sizes = [row["_size"] for row in cluster]
                total_size = sum(sizes)
                total_value = sum(p * s for p, s in zip(prices, sizes))
                accounts_in = {str(row.get("_account") or "") for row in cluster}
                if len(cluster) < 3 and len(accounts_in) < 2 and total_value < 200_000:
                    continue
                dir_counts = {direction: len(cluster)}
                fill_zones.append(
                    {
                        "kind": "whale_fill",
                        "side": "买入" if side == "B" else "卖出",
                        "side_raw": side,
                        "dir": direction,
                        "dir_counts": dir_counts,
                        "count": len(cluster),
                        "accounts": len(accounts_in),
                        "min_px": min(prices),
                        "max_px": max(prices),
                        "avg_px": total_value / total_size if total_size else (min(prices) + max(prices)) / 2,
                        "total_sz": total_size,
                        "total_value": total_value,
                        "last_time": max(int(row.get("time") or 0) for row in cluster),
                    }
                )
        fill_zones.sort(key=lambda item: (item["accounts"], item["total_value"]), reverse=True)
        fill_zones = fill_zones[:30]
        positions = (
            self._cluster_autohunt_positions(position_rows)
            if include_positions else []
        )
        rows.sort(key=lambda item: (item["accounts"], item["total_value"]), reverse=True)
        rows = rows[:20]
        result = {
            "process": name,
            "account_count": len(addresses),
            "zones": rows,
            "order_zones": rows,
            "fill_zones": fill_zones,
            "positions": positions,
        }
        self.whale_cache[cache_key] = (time.monotonic(), result)
        return result
    def chart_overlay_data(self, kind, raw_coin, raw_fill_window_min="1440", raw_proc="", raw_merge="1"):
        """按单一叠加类型返回 Autohunt 数据，便于前端渐进渲染。"""
        kind = str(kind or "all").lower()
        if kind not in {"orders", "fills", "positions"}:
            kind = "all"
        try:
            fill_window_min = int(raw_fill_window_min)
        except (TypeError, ValueError):
            fill_window_min = 1440
        fill_window_min = min(max(fill_window_min, 60), 10080)
        try:
            merge = float(raw_merge)
        except (TypeError, ValueError):
            merge = 1.0
        merge = min(max(merge, 0.25), 4.0)
        result = self.whale_zones(
            str(raw_proc or ""),
            str(raw_coin or "BTC").strip(),
            merge,
            fill_window_min,
            include_orders=kind in {"orders", "all"},
            include_fills=kind in {"fills", "all"},
            include_positions=kind in {"positions", "all"},
            kind=kind,
        )
        if not result:
            return {
                "type": "chart_overlays",
                "kind": kind,
                "process": "",
                "account_count": 0,
                "order_zones": [],
                "fill_zones": [],
                "positions": [],
                "generated_at": int(time.time() * 1000),
            }
        result["type"] = "chart_overlays"
        result["kind"] = kind
        return result
    def recent_events(self, raw_address=None, limit=50):
        address = normalize_address(raw_address) if raw_address else None
        rows = self.store.recent_events(limit)
        if address:
            rows = [row for row in rows if row.get("address") == address]
        return {
            "type": "events",
            "address": address,
            "events": rows[:limit],
            "generated_at": int(time.time() * 1000),
        }


    # ---------------------------------------------------------------- 设置

    COLOR_KEYS = (
        "accent_color",
        "up_color",
        "down_color",
        "bg_color",
        "panel_color",
    )

    def default_settings(self):
        """默认值始终以启动时的 config.toml 为基准。"""
        return {
            "site_title": "Hyperliquid Monitor",
            "amount_format": "compact",
            "accent_color": "#38d1a7",
            "up_color": "#1d8f70",
            "down_color": "#b54848",
            "bg_color": "#181818",
            "panel_color": "#202020",
            "proxy_enabled": "1" if self._config_proxy_url else "0",
            "whale_monitor_transactions": (
                "1" if self.config.whales.monitor_transactions else "0"
            ),
            "proxy_url": self._config_proxy_url or "",
        }

    def settings_values(self):
        values = self.default_settings()
        stored = self.store.get_app_settings()
        for key in values:
            if key in stored:
                values[key] = stored[key]
        return values

    def public_settings(self):
        """首屏就要应用的设置：标题与配色。"""
        values = self.settings_values()
        return {
            "site_title": values["site_title"],
            "amount_format": values["amount_format"],
            "accent_color": values["accent_color"],
            "up_color": values["up_color"],
            "down_color": values["down_color"],
            "bg_color": values["bg_color"],
            "panel_color": values["panel_color"],
        }

    def settings_data(self):
        return {
            "type": "settings",
            "values": self.settings_values(),
            "defaults": self.default_settings(),
            "runtime": {
                "effective_proxy": self.config.proxy_url or "",
                "network": self.config.network,
                "info_url": self.config.info_url,
            },
            "generated_at": int(time.time() * 1000),
        }

    def apply_settings(self):
        """把已保存的设置同步到运行时（代理与金额显示风格）。"""
        values = self.settings_values()
        set_amount_style(values.get("amount_format"))
        enabled = values.get("proxy_enabled") == "1"
        url = str(values.get("proxy_url") or "").strip()
        target = url if (enabled and url) else None
        if target != self.config.proxy_url:
            self.config.proxy_url = target
            # REST 客户端与链上适配器都按新代理重建；WebSocket 需重启进程。
            self.monitor.api.opener = build_opener(target)
            self._holder_adapter_cache = None
            self.holder_scan_cache.clear()
        return values

    def update_settings(self, payload):
        defaults = self.default_settings()
        merged = dict(self.settings_values())
        clean = {}
        for key, raw in (payload or {}).items():
            if key not in defaults:
                continue
            if key in self.COLOR_KEYS:
                text = str(raw).strip()
                if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
                    raise ValueError(f"{key} 需要是 #RRGGBB 格式的颜色")
                clean[key] = text.lower()
            elif key == "amount_format":
                text = str(raw).strip().lower()
                if text not in AMOUNT_STYLES:
                    raise ValueError(
                        "amount_format 只能是 " + "、".join(AMOUNT_STYLES)
                    )
                clean[key] = text
            elif key in {"proxy_enabled", "whale_monitor_transactions"}:
                enabled = str(raw).strip().lower() in {"1", "true", "yes", "on"}
                clean[key] = "1" if enabled else "0"
            elif key == "proxy_url":
                clean[key] = str(raw).strip()[:300]
            elif key == "site_title":
                text = str(raw).strip()[:80]
                clean[key] = text or defaults[key]
        if not clean:
            raise ValueError("没有可保存的设置")

        merged.update(clean)
        if merged.get("proxy_enabled") == "1" and not merged.get("proxy_url"):
            raise ValueError("启用代理时必须填写代理地址")

        self.store.set_app_settings(clean, int(time.time() * 1000))
        self.apply_settings()
        return self.settings_data()

    def reset_settings(self):
        self.store.set_app_settings(
            {key: None for key in self.default_settings()},
            int(time.time() * 1000),
        )
        self.apply_settings()
        return self.settings_data()

    # ---------------------------------------------------------------- 链上筹码

    def holder_adapters(self):
        if self._holder_adapter_cache is None:
            self._holder_adapter_cache = build_adapters(
                self.config.whales, proxy_url=self.config.proxy_url
            )
        return self._holder_adapter_cache

    def _holder_exclude_tags(self):
        extra = {
            str(item).lower() for item in (self.config.whales.exclude_tags or [])
        }
        return set(DEFAULT_EXCLUDE_TAGS) | extra

    def _holder_exclude_keywords(self):
        extra = tuple(
            str(item).lower()
            for item in (self.config.whales.exclude_label_keywords or [])
        )
        return tuple(DEFAULT_EXCLUDE_LABEL_KEYWORDS) + extra

    def whale_chains(self):
        return [
            {
                "id": chain,
                "name": adapter.name,
                "scan": bool(adapter.supports_scan()),
                "kind": adapter.kind,
                "tx": bool(adapter.supports_transactions()),
            }
            for chain, adapter in sorted(self.holder_adapters().items())
        ]

    def whale_data(self):
        whales = self.config.whales
        # 展示所有聊天订阅的并集；chat_ids 保留下来供操作定位。
        watches = self.store.all_whale_watches_merged()
        tokens = self.store.all_whale_tokens_merged()
        return {
            "type": "whale",
            "enabled": bool(whales.enabled),
            "chains": self.whale_chains(),
            "watches": [
                {
                    "chain": row["chain"],
                    "token": row["token"],
                    "address": row["address"],
                    "symbol": row["symbol"],
                    "label": row["label"],
                    "balance": row["last_balance"],
                    "error": row["last_error"],
                    "checked_ms": row["last_checked_ms"],
                    "interval_minutes": round(row["interval_s"] / 60.0, 1),
                    "min_delta_pct": row["min_delta_pct"],
                "chat_ids": row["chat_ids"],
                    "last_tx_ms": row["last_tx_ms"],
                    "tx_error": row["tx_error"],
                }
                for row in watches
            ],
            "transactions": self.store.recent_whale_txs(None, 40),
            "monitor_transactions": self.whale_tx_enabled(),
            "tokens": [
                {
                    "chain": row["chain"],
                    "token": row["token"],
                    "symbol": row["symbol"],
                    "label": row["label"],
                    "top_pct": row["last_top_pct"],
                    "score": row["last_score"],
                    "scanned_ms": row["last_scan_ms"],
                    "error": row["last_error"],
                    "interval_hours": round(row["interval_s"] / 3600.0, 2),
                    "chat_ids": row["chat_ids"],
                }
                for row in tokens
            ],
            "defaults": {
                "scan_limit": whales.scan_limit,
                "max_rows": whales.max_rows,
                "watch_interval_minutes": whales.watch_interval_minutes,
                "scan_interval_hours": whales.scan_interval_hours,
                "min_delta_pct": whales.min_delta_pct,
            },
            "generated_at": int(time.time() * 1000),
        }

    def whale_scan(self, chain, token, limit=None, force=False):
        chain = str(chain or "").strip().lower()
        query = str(token or "").strip()
        if not chain or not query:
            raise ValueError("需要提供链和代币")
        adapter = self.holder_adapters().get(chain)
        if adapter is None:
            raise ValueError(f"不支持的链 {chain}")
        if not adapter.supports_scan():
            raise ValueError(
                f"{adapter.name} 没有免费的持仓榜接口，只能监控已知地址"
            )
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = self.config.whales.scan_limit
        limit = max(5, min(200, limit))

        cache_key = (chain, query.lower(), limit)
        now = time.monotonic()
        if not force:
            cached = self.holder_scan_cache.get(cache_key)
            if cached and now - cached[0] < self.holder_scan_ttl:
                return cached[1]

        # 允许直接填符号（例如 ARB），解析成合约地址后再扫。
        resolution = resolve_token(adapter, query)
        if not resolution.ok:
            message = (
                f"“{query}”匹配到多个代币，请选择具体的合约地址"
                if resolution.ambiguous
                else f"没有找到代币“{query}”，可以换合约地址或更完整的名称"
            )
            empty = ConcentrationReport(
                chain=chain,
                token=query,
                scanned_ms=int(time.time() * 1000),
                error=message,
            )
            result = {
                "type": "whale_scan",
                "chain": chain,
                "token": query,
                "query": query,
                "limit": limit,
                "report": empty.to_dict(),
                "resolved": resolution.to_dict(),
                "previous": None,
                "history": [],
                "generated_at": int(time.time() * 1000),
            }
            self.holder_scan_cache[cache_key] = (now, result)
            return result

        resolved = resolution.address
        previous = self.store.get_whale_scan(chain, resolved)
        report = scan_token(
            adapter,
            resolved,
            limit=limit,
            exclude_tags=self._holder_exclude_tags(),
            exclude_addresses=self.config.whales.exclude_addresses,
            exclude_keywords=self._holder_exclude_keywords(),
        )
        if not report.error:
            self.store.save_whale_scan(report)
            self.store.record_whale_history(report)
        result = {
            "type": "whale_scan",
            "chain": chain,
            "token": resolved,
            "query": query,
            "limit": limit,
            "report": report.to_dict(),
            "resolved": resolution.to_dict(),
            "previous": previous,
            "history": self.store.get_whale_history(chain, resolved, limit=30),
            "generated_at": int(time.time() * 1000),
        }
        self.holder_scan_cache[cache_key] = (now, result)
        return result

    def whale_search(self, chain, query, limit=10):
        text = str(query or "").strip()
        if len(text) < 2:
            raise ValueError("关键词至少 2 个字符")
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 10
        return {
            "type": "whale_search",
            "query": text,
            "chain": str(chain or "").strip().lower(),
            "results": search_tokens(
                self.holder_adapters(),
                text,
                chain=str(chain or "").strip().lower() or None,
                limit=max(1, min(30, limit)),
            ),
            "generated_at": int(time.time() * 1000),
        }

    TX_WINDOWS = {
        "24h": 24 * 3600 * 1000,
        "3d": 3 * 24 * 3600 * 1000,
        "7d": 7 * 24 * 3600 * 1000,
        "30d": 30 * 24 * 3600 * 1000,
        "90d": 90 * 24 * 3600 * 1000,
    }

    def whale_tx_analysis(self, asset=None, window="30d", chain=None,
                          watched_address=None):
        """按币种汇总一段时间内的转账，并聚合对手方。"""
        window_ms = self.TX_WINDOWS.get(str(window or "30d"))
        if window_ms is None:
            raise ValueError(
                "window 只支持 " + "、".join(sorted(self.TX_WINDOWS))
            )
        now_ms = int(time.time() * 1000)
        since_ms = now_ms - window_ms
        asset = str(asset or "").strip()
        if not asset:
            raise ValueError("需要指定代币符号")
        chain_filter = str(chain).strip().lower() if chain else None
        watched_filter = str(watched_address).strip() if watched_address else None
        rows = self.store.whale_txs_in_range(
            asset=asset,
            chain=chain_filter,
            watched_address=watched_filter,
            since_ms=since_ms,
            limit=5000,
        )

        ins = [r for r in rows if r["direction"] == "in"]
        outs = [r for r in rows if r["direction"] == "out"]
        selfs = [r for r in rows if r["direction"] == "self"]

        # 按天分桶，供前端画趋势
        daily = {}
        for row in rows:
            day = int((row["time"] or 0) // 86400000) * 86400000
            bucket = daily.setdefault(
                day, {"in": 0.0, "out": 0.0, "count": 0}
            )
            bucket["count"] += 1
            if row["direction"] == "in":
                bucket["in"] += float(row.get("value") or 0)
            elif row["direction"] == "out":
                bucket["out"] += float(row.get("value") or 0)
        series = [
            {"day": day, "in": b["in"], "out": b["out"], "count": b["count"]}
            for day, b in sorted(daily.items())
        ]

        watched_breakdown = {}
        for row in rows:
            key = (str(row.get("address") or "").lower(), row.get("chain"))
            item = watched_breakdown.setdefault(
                key,
                {
                    "address": row.get("address"),
                    "chain": row.get("chain"),
                    "count": 0,
                    "in": 0.0,
                    "out": 0.0,
                },
            )
            item["count"] += 1
            if row["direction"] == "in":
                item["in"] += float(row.get("value") or 0)
            elif row["direction"] == "out":
                item["out"] += float(row.get("value") or 0)

        peers = self.store.whale_tx_counterparties(
            asset=asset,
            chain=chain_filter,
            watched_address=watched_filter,
            since_ms=since_ms,
            limit=200,
        )
        # 同一个对手方把 in/out 合并一行，方便看净流。
        peers_merged = {}
        for peer in peers:
            key = peer["counterparty"].lower()
            item = peers_merged.setdefault(
                key,
                {
                    "counterparty": peer["counterparty"],
                    "in": {"count": 0, "value": 0.0},
                    "out": {"count": 0, "value": 0.0},
                    "first_ms": peer["first_ms"],
                    "last_ms": peer["last_ms"],
                    "chains": [],
                    "watched_accounts": [],
                },
            )
            bucket = item[peer["direction"]]
            bucket["count"] += peer["count"]
            bucket["value"] += peer["value"]
            item["first_ms"] = min(item["first_ms"], peer["first_ms"])
            item["last_ms"] = max(item["last_ms"], peer["last_ms"])
            for c in peer["chains"]:
                if c not in item["chains"]:
                    item["chains"].append(c)
            for a in peer["watched_accounts"]:
                if a not in item["watched_accounts"]:
                    item["watched_accounts"].append(a)
        peer_rows = sorted(
            peers_merged.values(),
            key=lambda p: (
                p["in"]["value"] + p["out"]["value"], p["in"]["count"] + p["out"]["count"]
            ),
            reverse=True,
        )

        # 给对手方贴标签：手工配置优先，其次是成交时攒下来的 Blockscout 标签。
        labels = self.store.get_address_labels()
        for item in parse_config_labels(self.config.whales.address_labels):
            labels[(item["chain"], item["address"].lower())] = {
                "label": item["label"],
                "category": item["category"],
                "source": "config",
            }
        exchange_deposit = 0.0
        exchange_withdraw = 0.0
        exchange_peers = 0
        for p in peer_rows:
            p["net"] = p["in"]["value"] - p["out"]["value"]
            label = ""
            category = ""
            for chain_name in p["chains"]:
                meta = labels.get((str(chain_name).lower(), p["counterparty"].lower()))
                if meta:
                    label = meta.get("label") or ""
                    category = meta.get("category") or ""
                    break
            p["label"] = label
            p["category"] = category
            p["is_exchange"] = is_exchange_label(label, category)
            if p["is_exchange"]:
                exchange_peers += 1
                # out = 我们把币打进交易所，in = 交易所打给我们。
                exchange_deposit += p["out"]["value"]
                exchange_withdraw += p["in"]["value"]

        # 最近交易也返回，最多 100 条。
        recent = rows[:100]

        return {
            "type": "whale_tx_analysis",
            "asset": asset,
            "window": window,
            "since_ms": since_ms,
            "until_ms": now_ms,
            "chain": str(chain).strip().lower() or None,
            "watched_address": str(watched_address).strip() or None,
            "summary": {
                "count": len(rows),
                "in_count": len(ins),
                "out_count": len(outs),
                "self_count": len(selfs),
                "in_value": sum(float(r["value"] or 0) for r in ins),
                "out_value": sum(float(r["value"] or 0) for r in outs),
                "net_value": sum(float(r["value"] or 0) for r in ins)
                - sum(float(r["value"] or 0) for r in outs),
                "watched_count": len(watched_breakdown),
                "peer_count": len(peer_rows),
                "exchange_count": exchange_peers,
                "exchange_deposit": exchange_deposit,
                "exchange_withdraw": exchange_withdraw,
                "exchange_net": exchange_withdraw - exchange_deposit,
            },
            "daily": series,
            "watched": sorted(
                watched_breakdown.values(),
                key=lambda w: (w["in"] + w["out"]),
                reverse=True,
            ),
            "counterparties": peer_rows[:50],
            "recent": recent,
            "generated_at": now_ms,
        }

    def whale_mutate(self, kind, payload):
        """kind = watch | token，action = add | remove。"""
        action = str(payload.get("action") or "add").strip().lower()
        chain = str(payload.get("chain") or "").strip().lower()
        token = str(payload.get("token") or "").strip()
        if not chain or not token:
            raise ValueError("缺少链或代币")
        now_ms = int(time.time() * 1000)

        if kind == "watch":
            address = str(payload.get("address") or "").strip()
            if not address:
                raise ValueError("缺少地址")
            if action == "remove":
                removed = self.store.remove_whale_watch(
                    self.web_chat_id,
                    chain,
                    token,
                    address,
                    all_chats=bool(payload.get("all_chats")),
                )
                return {"removed": bool(removed)}
            whales = self.config.whales
            self.store.upsert_whale_watch(
                self.web_chat_id,
                {
                    "chain": chain,
                    "token": token,
                    "address": address,
                    "symbol": str(payload.get("symbol") or token),
                    "label": str(payload.get("label") or ""),
                    "decimals": payload.get("decimals"),
                    "interval_s": whales.watch_interval_minutes * 60.0,
                    "min_delta_pct": whales.min_delta_pct,
                    "min_delta_abs": whales.min_delta_abs,
                },
                now_ms,
            )
            return {"added": True}

        if action == "remove":
            removed = self.store.remove_whale_token(
                self.web_chat_id,
                chain,
                token,
                all_chats=bool(payload.get("all_chats")),
            )
            return {"removed": bool(removed)}
        whales = self.config.whales
        self.store.upsert_whale_token(
            self.web_chat_id,
            {
                "chain": chain,
                "token": token,
                "symbol": str(payload.get("label") or payload.get("symbol") or token),
                "label": str(payload.get("label") or ""),
                "interval_s": whales.scan_interval_hours * 3600.0,
            },
            now_ms,
        )
        return {"added": True}

    def whale_tx_assets(self):
        """一段时间内出现过的代币符号，供成交分析页选择。"""
        return [
            {
                "asset": row["asset"],
                "count": row["count"],
                "last_ms": row["last_ms"],
            }
            for row in self.store.whale_tx_asset_summary(days=90)
        ]

    def whale_tx_enabled(self):
        return self.settings_values().get("whale_monitor_transactions") == "1"

    def _holder_watcher(self):
        return WhaleWatcher(
            self.holder_adapters(),
            self.store,
            interval=self.config.whales.watch_interval_minutes * 60.0,
            exclude_tags=self._holder_exclude_tags(),
            exclude_addresses=self.config.whales.exclude_addresses,
            exclude_keywords=self._holder_exclude_keywords(),
            concentration_threshold=self.config.whales.concentration_threshold,
            monitor_transactions=self.whale_tx_enabled(),
            tx_limit=self.config.whales.tx_limit,
        )

    def whale_check(self, targets=None):
        """刷新监控地址余额。

        targets 为 [{"chain","token","address"}] 时只刷这些（单条或单组），
        不传则全刷。用完整三元组定位，避免同地址跨链时误刷。
        """
        wanted = None
        if targets is not None:
            if not isinstance(targets, (list, tuple)) or not targets:
                raise ValueError("targets 需要是非空数组")
            wanted = set()
            for item in targets:
                if not isinstance(item, dict):
                    raise ValueError("targets 每一项都应该是对象")
                chain = str(item.get("chain") or "").strip().lower()
                token = str(item.get("token") or "").strip()
                address = str(item.get("address") or "").strip()
                if not chain or not address:
                    raise ValueError("targets 每一项都需要 chain 和 address")
                wanted.add((chain, token, address))
        self._holder_watcher().check_addresses(force=True, targets=wanted)
        return self.whale_data()

    def whale_rescan(self, chain, token):
        """复扫单个订阅代币的筹码结构。"""
        chain = str(chain or "").strip().lower()
        token = str(token or "").strip()
        if not chain or not token:
            raise ValueError("缺少链或代币")
        self._holder_watcher().check_tokens(force=True, tokens={(chain, token)})
        return self.whale_data()


class WebRequestHandler(BaseHTTPRequestHandler):
    server_version = "hlmonitor-web/" + __version__
    app: WebApp

    def log_message(self, fmt, *args):
        return

    def _send_json(self, status, payload):
        body = json.dumps(_json_safe(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 1_000_000:
            raise ValueError("invalid request body")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON object expected")
        return data

    def _static(self, path):
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._send_json(404, {"error": "not found"})
            return
        if not target.is_file():
            self._send_json(404, {"error": "not found"})
            return
        content_type, _ = mimetypes.guess_type(str(target))
        if content_type in {"text/html", "text/css", "application/javascript", "text/javascript"}:
            content_type += "; charset=utf-8"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        address = (query.get("address") or [None])[0]
        try:
            if path == "/api/state":
                self._send_json(
                    200,
                    {
                        "network": self.app.config.network,
                        "version": __version__,
                        "accounts": self.app.accounts(),
                        "autohunt_processes": self.app.autohunt_processes(),
                        "settings": self.app.public_settings(),
                    },
                )
            elif path == "/api/overview":
                self._send_json(200, self.app.overview_data(address))
            elif path == "/api/fills":
                self._send_json(200, self.app.fills_data(address, (query.get("window_min") or ["1440"])[0]))
            elif path == "/api/orders":
                self._send_json(200, self.app.report_data("orders", address, (query.get("level") or ["auto"])[0]))
            elif path == "/api/tpsl":
                self._send_json(200, self.app.report_data("tpsl", address))
            elif path == "/api/history":
                self._send_json(200, self.app.report_data("history", address))
            elif path == "/api/chart/overlay":
                self._send_json(
                    200,
                    self.app.chart_overlay_data(
                        (query.get("kind") or ["all"])[0],
                        (query.get("coin") or ["BTC"])[0],
                        (query.get("fill_window_min") or ["1440"])[0],
                        (query.get("proc") or [""])[0],
                        (query.get("merge") or ["1"])[0],
                    ),
                )
            elif path == "/api/chart":
                self._send_json(
                    200,
                    self.app.chart_data(
                        address,
                        (query.get("coin") or ["BTC"])[0],
                        (query.get("interval") or ["15m"])[0],
                        (query.get("fill_window_min") or ["1440"])[0],
                        (query.get("whale") or ["0"])[0] == "1",
                        (query.get("proc") or [""])[0],
                        (query.get("merge") or ["1"])[0],
                        (query.get("whale_orders") or ["1"])[0] == "1",
                        (query.get("whale_fills") or ["1"])[0] == "1",
                        (query.get("whale_positions") or ["0"])[0] == "1",
                    ),
                )
            elif path == "/api/settings":
                self._send_json(200, self.app.settings_data())
            elif path == "/api/whale/tx/assets":
                self._send_json(200, {"assets": self.app.whale_tx_assets()})
            elif path == "/api/whale/tx/analysis":
                self._send_json(
                    200,
                    self.app.whale_tx_analysis(
                        asset=(query.get("asset") or [""])[0],
                        window=(query.get("window") or ["30d"])[0],
                        chain=(query.get("chain") or [""])[0],
                        watched_address=(query.get("address") or [""])[0],
                    ),
                )
            elif path == "/api/whale":
                self._send_json(200, self.app.whale_data())
            elif path == "/api/whale/search":
                self._send_json(
                    200,
                    self.app.whale_search(
                        (query.get("chain") or [""])[0],
                        (query.get("q") or [""])[0],
                        (query.get("limit") or ["10"])[0],
                    ),
                )
            elif path == "/api/whale/scan":
                self._send_json(
                    200,
                    self.app.whale_scan(
                        (query.get("chain") or [""])[0],
                        (query.get("token") or [""])[0],
                        (query.get("limit") or [""])[0],
                        (query.get("force") or ["0"])[0] == "1",
                    ),
                )
            elif path == "/api/autohunt":
                self._send_json(200, self.app.autohunt_data())
            elif path == "/api/events":
                limit = min(200, max(1, int((query.get("limit") or [100])[0])))
                self._send_json(200, self.app.recent_events(address, limit))
            elif path.startswith("/api/"):
                self._send_json(404, {"error": "API not found"})
            else:
                self._static(path)
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        try:
            data = self._read_json()
            if path == "/api/accounts":
                item = self.app.add_account(data.get("address", ""), data.get("alias", ""))
                self._send_json(200, {"account": item})
            elif path == "/api/settings":
                if data.get("reset"):
                    self._send_json(200, self.app.reset_settings())
                else:
                    self._send_json(
                        200, self.app.update_settings(data.get("values") or {})
                    )
            elif path == "/api/whale/watch":
                self._send_json(200, self.app.whale_mutate("watch", data))
            elif path == "/api/whale/token":
                self._send_json(200, self.app.whale_mutate("token", data))
            elif path == "/api/whale/check":
                self._send_json(
                    200, self.app.whale_check(data.get("targets"))
                )
            elif path == "/api/whale/rescan":
                self._send_json(
                    200,
                    self.app.whale_rescan(data.get("chain"), data.get("token")),
                )
            else:
                self._send_json(404, {"error": "API not found"})
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})

    def do_DELETE(self):
        path = urlparse(self.path).path.rstrip("/")
        match = re.fullmatch(r"/api/accounts/(0x[0-9a-fA-F]{40})", path)
        if not match:
            self._send_json(404, {"error": "API not found"})
            return
        try:
            self._send_json(200, {"account": self.app.remove_account(match.group(1))})
        except Exception as exc:
            if isinstance(exc, KeyError):
                status = 404
            elif isinstance(exc, PermissionError):
                status = 403
            else:
                status = 400
            self._send_json(status, {"error": str(exc)})


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m hlmonitor.web",
        description="Run the Hyperliquid monitor web dashboard.",
    )
    parser.add_argument("--config", help="Path to TOML config")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    config_path = args.config
    if not config_path and Path("config.toml").exists():
        config_path = "config.toml"
    app = WebApp(load_config(config_path))
    WebRequestHandler.app = app
    server = ThreadingHTTPServer((args.host, args.port), WebRequestHandler)
    server.daemon_threads = True
    print(f"Hyperliquid Web dashboard: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == "__main__":
    main()