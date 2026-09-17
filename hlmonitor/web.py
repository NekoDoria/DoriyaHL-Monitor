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
from .monitor import AddressMonitor
from .state import EventStore


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
        self.web_chat_id = "__web__"
        self.chart_cache = {}
        self.chart_cache_ttl = 15.0
        self.whale_cache = {}
        self.whale_cache_ttl = 60.0

    def close(self):
        self.store.close()

    def accounts(self):
        configured = {
            address: {"source": "config", "alias": ""}
            for address in self.config.addresses
        }
        for row in self.store.get_subscriptions(self.web_chat_id, active_only=False):
            item = configured.setdefault(
                row["address"],
                {"source": "web", "alias": row.get("alias", "")},
            )
            if item.get("source") != "config":
                item["alias"] = row.get("alias", "")
                item["source"] = "web"
        return [
            {
                "address": address,
                "alias": meta.get("alias", ""),
                "source": meta.get("source", "web"),
            }
            for address, meta in sorted(configured.items())
        ]

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
        self.store.unsubscribe(self.web_chat_id, address)
        return item

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


    def chart_data(self, raw_address, raw_coin, raw_interval="15m", fill_window_min=1440, whale=False, proc="", merge=1.0):
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
        cache_key = (address, coin, interval, fill_window_min, bool(whale), str(proc or ""), round(merge, 3))
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
                    "color": "#1d8f70" if close_px >= open_px else "#b54848",
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
        }
        if whale:
            try:
                whale_data = self.whale_zones(proc, coin, merge)
            except Exception as exc:
                print(f"[web] whale zones failed: {exc}")
                whale_data = None
            if whale_data:
                result["whale_process"] = whale_data["process"]
                result["whale_account_count"] = whale_data["account_count"]
                result["whale_zones"] = whale_data["zones"]
        if fills_ok:
            self.chart_cache[cache_key] = (time.monotonic(), result)
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

        processes.sort(key=lambda row: (not row["enabled"], -row["last_run"], row["name"]))
        return {
            "type": "autohunt",
            "processes": processes,
            "collected": self.store.get_collected_accounts(),
            "generated_at": now_ms,
        }
    def whale_zones(self, proc_name, coin, merge=1.0):
        """聚合 autohunt 收集账户在该币种上的普通挂单区间。"""
        configs = self.store.all_autohunt_configs()
        if not configs:
            return None
        picked = None
        wanted = str(proc_name or "").strip().lower()
        if wanted:
            picked = next((c for c in configs if c["name"].lower() == wanted), None)
        picked = picked or configs[0]
        name = picked["name"]
        chat_id = picked["chat_id"]

        cache_key = (name, coin, round(float(merge), 3))
        cached = self.whale_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < self.whale_cache_ttl:
            return cached[1]

        accounts = self.store.get_auto_accounts(chat_id, name)[:40]
        addresses = [str(a.get("address") or "") for a in accounts if a.get("address")]
        api = self.monitor.api

        dexes = set()
        try:
            dex_map = _build_coin_dex_map(api)
            dexes.update(dex_map.get(str(coin).upper(), set()))
        except Exception:
            pass
        if not dexes:
            dexes.add("")

        def fetch(address):
            collected = []
            for dex in sorted(dexes):
                try:
                    orders = (
                        api.frontend_open_orders(address)
                        if dex == ""
                        else api.frontend_open_orders(address, dex)
                    )
                except Exception:
                    continue
                collected.extend(orders or [])
            return collected

        flat = []
        if addresses:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(addresses))) as pool:
                for address, orders in zip(addresses, pool.map(fetch, addresses)):
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
        rows.sort(key=lambda item: (item["accounts"], item["total_value"]), reverse=True)
        rows = rows[:20]
        result = {
            "process": name,
            "account_count": len(addresses),
            "zones": rows,
        }
        self.whale_cache[cache_key] = (time.monotonic(), result)
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