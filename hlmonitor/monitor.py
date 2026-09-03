"""High-level address monitor: WebSocket events plus periodic REST snapshots."""

from __future__ import annotations

import html
import json
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .alerts import build_notifier
from .api import HyperliquidAPI
from .brief import (
    build_open_orders_summaries,
    format_position_brief,
    format_position_brief_html,
    format_open_orders_intervals_html,
    format_tpsl_report_html,
)
from .config import Config
from .format import (
    fmt_dir,
    fmt_side,
    fmt_szi,
    fmt_time,
    fmt_usd,
    fmt_usd_cn,
    short_addr,
)
from .state import EventStore
from .ws import WebSocketMonitor


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


MERGE_LEVELS = {
    "fine": {"scale": 0.5, "ladder_detection": False, "label": "细"},
    "auto": {"scale": 1.0, "ladder_detection": True, "label": "自动"},
    "coarse": {"scale": 2.0, "ladder_detection": True, "label": "粗"},
}


class AddressMonitor:
    def __init__(self, config: Config, store=None, notifier=None):
        self.config = config
        self.api = HyperliquidAPI(
            config.info_url,
            timeout=15,
            proxy_url=config.proxy_url,
        )
        self._owns_store = store is None
        self.store = store or EventStore(str(config.db_path))
        self.notifier = notifier or build_notifier(
            config.alerts,
            proxy_url=config.proxy_url,
        )
        self._address_lock = threading.RLock()
        self._ws_lock = threading.RLock()
        self.addresses = list(config.addresses)
        self._ws_monitors: list[WebSocketMonitor] = []
        self._stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._started = False
        self._open_time_cache: dict[str, tuple[int, dict[str, int]]] = {}
        self._realized_pnl_cache: dict[str, tuple[float, float]] = {}
        self._spot_meta_cache: dict[str, str] = {}
        self._spot_meta_at = 0.0
        self._vol_cache: dict[str, tuple[float, float | None]] = {}

    def start(self):
        if self.addresses:
            print(f"[monitor] 监控 {len(self.addresses)} 个地址：")
            for address in self.addresses:
                print(f"  - {address}")
        else:
            print("[monitor] 当前没有监控地址，等待 Telegram 添加。")
        print(f"[monitor] 网络: {self.config.network}")
        print(f"[monitor] 数据文件: {self.config.db_path}")

        for address in self.addresses:
            ws = WebSocketMonitor(
                self.config.ws_url,
                address,
                self._on_ws_message,
                max_silence=self.config.ws_max_silence,
                proxy_url=self.config.proxy_url,
            )
            ws.start()
            with self._ws_lock:
                self._ws_monitors.append(ws)

        self._started = True
        if self.config.poll_on_start and self.addresses:
            self.poll_once()

        if self.config.poll_interval > 0:
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="hl-poll",
                daemon=True,
            )
            self._poll_thread.start()

    def run_forever(self):
        try:
            while not self._stop.is_set():
                self._stop.wait(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        if self._stop.is_set():
            return
        self._stop.set()
        self._started = False
        with self._ws_lock:
            ws_monitors = list(self._ws_monitors)
            self._ws_monitors = []
        for ws in ws_monitors:
            ws.stop()
        if self._owns_store:
            self.store.close()
        print("[monitor] 已停止")

    def poll_once(self):
        with self._address_lock:
            addresses = list(self.addresses)
        for address in addresses:
            try:
                state = self._fetch_clearinghouse_state(address)
                spot_state = None
                try:
                    spot_state = self._fetch_spot_state(address)
                except Exception as exc:
                    print(f"[poll] 现货状态拉取失败 ({short_addr(address)}): {exc}")
                self._process_state(address, state, spot_state)
            except Exception as exc:
                print(f"[poll] 拉取失败 ({short_addr(address)}): {exc}")

    def snapshot_report(self, address, sort_mode=None, html=False):
        data = self.snapshot_data(address)
        formatter = format_position_brief_html if html else format_position_brief
        return formatter(
            data["address"],
            data["summary"],
            data["positions"],
            spot_balances=data["spot_balances"],
            sort_mode=sort_mode or self.config.position_sort,
            title="持仓简报",
            include_spot=True,
        )

    def snapshot_data(self, address):
        """Fetch current state and return data for live brief editing."""
        address = address.lower()
        state = self._fetch_clearinghouse_state(address)
        spot_state = None
        try:
            spot_state = self._fetch_spot_state(address)
        except Exception:
            pass

        margin = state.get("marginSummary") or state.get("crossMarginSummary") or {}
        account_value = _num(margin.get("accountValue"))
        total_ntl_pos = _num(margin.get("totalNtlPos"))
        withdrawable = _num(state.get("withdrawable"))
        positions = self._extract_positions(state)
        spot_balances = self._extract_spot_balances(spot_state)
        previous_positions = self.store.get_positions(address)
        positions = self._attach_open_times(address, positions, previous_positions)

        summary = {
            "account_value": account_value,
            "total_ntl_pos": total_ntl_pos,
            "withdrawable": withdrawable,
        }
        self._add_pnl_summary(address, summary, positions)
        return {
            "address": address,
            "summary": summary,
            "positions": positions,
            "spot_balances": spot_balances,
            "changes": {},
            "closed_positions": [],
            "title": "持仓简报",
            "include_spot": True,
        }

    def history_report(self, address, limit=20):
        """Reconstruct historical holdings from the recent fill history."""
        address = address.lower()
        state = self._fetch_clearinghouse_state(address)
        current_positions = self._extract_positions(state)
        fills = self._fetch_fill_history(address)
        history = self._reconstruct_position_history(fills, current_positions)

        ordered = sorted(
            history.items(),
            key=lambda item: item[1].get("max_notional", 0),
            reverse=True,
        )
        blocks = [
            "\n".join(
                [
                    f"<b>📜 持仓历史 · {html.escape(short_addr(address))}</b>",
                    "数据来源: 最近成交记录（最多约 1 万笔）",
                ]
            )
        ]

        shown = 0
        for coin, info in ordered:
            if info.get("currently_held"):
                continue
            if not info.get("open_time") or not info.get("close_time"):
                continue
            if shown >= limit:
                break
            side = "多头" if info.get("side") and info["side"] > 0 else "空头"
            body = "\n".join(
                [
                    html.escape(f"开仓: {fmt_time(info.get('open_time'))}"),
                    html.escape(f"平仓: {fmt_time(info.get('close_time'))}"),
                    html.escape(f"峰值: {fmt_usd_cn(info.get('max_notional', 0))}"),
                    "杠杆: -",
                ]
            )
            blocks.append(
                f"<b>{html.escape(coin)}</b> · {side}\n"
                f"<blockquote expandable>{body}</blockquote>"
            )
            shown += 1

        if not shown:
            blocks.append("<blockquote>暂无已平仓记录</blockquote>")
        elif len(ordered) - shown > 0:
            blocks.append("... 其余记录因时间未知已省略")
        return "\n\n".join(blocks)

    def tpsl_report(self, address, limit=60):
        """Fetch current open take-profit / stop-loss orders (HTML report)."""
        address = address.lower()
        orders = self.api.frontend_open_orders(address)
        tpsl_orders = self._extract_tpsl_orders(orders)
        mids = {}
        try:
            mids = self.api.all_mids() or {}
        except Exception as exc:
            print(f"[tpsl] 行情拉取失败，金额列将省略: {exc}")
        position_notionals = {}
        try:
            state = self._fetch_clearinghouse_state(address)
            position_notionals = {
                coin: abs(_num(pos.get("notional")))
                for coin, pos in self._extract_positions(state).items()
            }
        except Exception as exc:
            print(f"[tpsl] 持仓拉取失败，跟随仓位金额将省略: {exc}")
        return format_tpsl_report_html(
            address,
            tpsl_orders,
            mids=mids,
            position_notionals=position_notionals,
            limit=limit,
        )

    def open_orders_data(self, address):
        """Fetch current open normal orders plus mids and spot names."""
        address = address.lower()
        orders = self.api.frontend_open_orders(address)
        normal_orders = self._extract_normal_orders(orders)
        mids = {}
        try:
            mids = self.api.all_mids() or {}
        except Exception as exc:
            print(f"[orders] 行情拉取失败，金额列将省略: {exc}")
        gap_by_coin = self._gap_by_coin(normal_orders)
        return {
            "address": address,
            "orders": normal_orders,
            "mids": mids,
            "spot_names": self._spot_name_map(),
            "gap_by_coin": gap_by_coin,
        }

    def open_orders_report(self, address, coin=None, level="auto", limit=100):
        """Fetch current open normal orders as aggregated intervals (HTML)."""
        data = self.open_orders_data(address)
        params = MERGE_LEVELS.get(level, MERGE_LEVELS["auto"])
        return format_open_orders_intervals_html(
            data["address"],
            data["orders"],
            coin=coin,
            mids=data["mids"],
            spot_names=data["spot_names"],
            gap_by_coin=data.get("gap_by_coin") or {},
            base_gap_pct=self.config.order_merge.base_gap_pct,
            width_multiplier=self.config.order_merge.width_multiplier,
            scale=params["scale"],
            ladder_detection=params["ladder_detection"],
            ladder_min_orders=self.config.order_merge.ladder_min_orders,
            ladder_max_cv=self.config.order_merge.ladder_max_cv,
            level=params["label"],
            limit=limit,
        )

    def open_orders_coin_summaries(self, address):
        """Coin-level summaries for the orders coin-selection menu."""
        data = self.open_orders_data(address)
        return build_open_orders_summaries(
            data["orders"],
            spot_names=data["spot_names"],
        )

    def _gap_by_coin(self, orders):
        """为每个有挂单的币种计算自适应合并阈值。"""
        coins = []
        for order in orders or []:
            coin = str(order.get("coin") or "?")
            if coin not in coins:
                coins.append(coin)
        if not coins:
            return {}
        results = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self._merge_gap_pct, coin): coin
                for coin in coins
            }
            for future in futures:
                coin = futures[future]
                try:
                    results[coin] = future.result()
                except Exception:
                    results[coin] = self.config.order_merge.base_gap_pct
        return results

    def _merge_gap_pct(self, coin):
        """币种合并阈值 = max(基础阈值, 典型小时波动中位数 × 倍数)，带 5 分钟缓存。"""
        config = self.config.order_merge
        now = time.time()
        cached_at, cached = self._vol_cache.get(coin, (0.0, None))
        if now - cached_at > 300:
            vol = self._coin_volatility(coin)
            self._vol_cache[coin] = (now, vol)
            cached = vol
        if not cached:
            return config.base_gap_pct
        return min(
            config.max_gap_pct,
            max(config.base_gap_pct, config.vol_multiplier * cached),
        )

    def _coin_volatility(self, coin):
        """估算币种最近 N 小时的典型小时波动（绝对收益率中位数，百分比）。"""
        config = self.config.order_merge
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - config.vol_lookback_hours * 3_600_000
        try:
            candles = self.api._post(
                {
                    "type": "candleSnapshot",
                    "req": {
                        "coin": coin,
                        "interval": "1h",
                        "startTime": start_ms,
                        "endTime": now_ms,
                    },
                }
            )
        except Exception:
            return None
        closes = []
        for candle in candles or []:
            try:
                value = float(candle.get("c"))
            except (TypeError, ValueError):
                continue
            if value > 0:
                closes.append(value)
        if len(closes) < 2:
            return None
        returns = []
        for prev, current in zip(closes, closes[1:]):
            if prev > 0:
                returns.append(abs(current - prev) / prev * 100)
        return statistics.median(returns) if returns else None

    @staticmethod
    def _extract_normal_orders(orders):
        """从 frontendOpenOrders 返回里挑出普通挂单（非止盈止损）。"""
        return [
            order
            for order in orders or []
            if not (order.get("isTrigger") or order.get("isPositionTpsl"))
        ]

    def _spot_name_map(self):
        """现货 token 编号 -> 币种名，带 5 分钟缓存。"""
        now = time.time()
        if self._spot_meta_cache and now - self._spot_meta_at < 300:
            return self._spot_meta_cache
        try:
            data = self.api._post({"type": "spotMeta"})
            names = {}
            for token in data.get("tokens") or []:
                index = token.get("index")
                name = token.get("name")
                if index is not None and name:
                    names[str(index)] = str(name)
            self._spot_meta_cache = names
            self._spot_meta_at = now
            return names
        except Exception as exc:
            print(f"[orders] 现货币种名拉取失败: {exc}")
            return {}

    @staticmethod
    def _extract_tpsl_orders(orders):
        """从 frontendOpenOrders 返回里挑出止盈止损单，包括括号单的子单。"""
        seen = set()
        result = []
        for order in orders or []:
            candidates = list(order.get("children") or [])
            if order.get("isTrigger") or order.get("isPositionTpsl"):
                candidates.append(order)
            for candidate in candidates:
                if not (candidate.get("isTrigger") or candidate.get("isPositionTpsl")):
                    continue
                oid = candidate.get("oid")
                if oid in seen:
                    continue
                seen.add(oid)
                result.append(candidate)
        return result

    @staticmethod
    def _reconstruct_position_history(fills, current_positions):
        grouped = {}
        for fill in fills:
            coin = fill.get("coin", "")
            if not coin or coin.startswith("@"):
                continue
            grouped.setdefault(coin, []).append(fill)

        history = {}
        for coin, coin_fills in grouped.items():
            coin_fills.sort(key=lambda item: int(item.get("time") or 0))
            position = 0.0
            current_open = None
            current_side = None
            last_open = None
            last_close = None
            last_side = None
            max_notional = 0.0

            for fill in coin_fills:
                start = _num(fill.get("startPosition"))
                size = _num(fill.get("sz"))
                price = _num(fill.get("px"))
                side = str(fill.get("side", "")).upper()
                if side == "B":
                    position = start + size
                elif side == "A":
                    position = start - size
                else:
                    position = start

                if abs(position) > 1e-12:
                    if current_open is None:
                        current_open = fill.get("time")
                        current_side = 1 if position > 0 else -1
                    max_notional = max(
                        max_notional,
                        abs(position) * price,
                    )
                elif current_open is not None:
                    last_open = current_open
                    last_close = fill.get("time")
                    last_side = current_side
                    current_open = None

            currently_held = coin in current_positions
            if currently_held and current_open is None and coin_fills:
                current_open = coin_fills[0].get("time")

            history[coin] = {
                "currently_held": currently_held,
                "open_time": current_open if currently_held else last_open,
                "close_time": None if currently_held else last_close,
                "side": None if currently_held else last_side,
                "max_notional": max_notional,
            }
            if currently_held:
                current = current_positions.get(coin, {})
                max_notional = max(
                    max_notional,
                    abs(_num(current.get("notional"))),
                )
                history[coin]["max_notional"] = max_notional

        return history

    def set_addresses(self, addresses):
        """Start monitoring new addresses and stop removed ones in place."""
        normalized = []
        for address in addresses:
            address = address.lower()
            if address not in normalized:
                normalized.append(address)

        with self._address_lock:
            old = list(self.addresses)
            self.addresses = normalized
        with self._ws_lock:
            current_ws = {ws.address: ws for ws in self._ws_monitors}

        with self._ws_lock:
            for address in old:
                if address not in normalized:
                    ws = current_ws.get(address)
                    if ws is not None:
                        ws.stop()
                        if ws in self._ws_monitors:
                            self._ws_monitors.remove(ws)

        for address in normalized:
            if address not in current_ws:
                ws = WebSocketMonitor(
                    self.config.ws_url,
                    address,
                    self._on_ws_message,
                    max_silence=self.config.ws_max_silence,
                    proxy_url=self.config.proxy_url,
                )
                ws.start()
                with self._ws_lock:
                    self._ws_monitors.append(ws)

        if (
            self._started
            and not self._stop.is_set()
            and self.config.poll_on_start
            and normalized
        ):
            # Refresh snapshot immediately after the set changes.
            self.poll_once()

    def _poll_loop(self):
        while not self._stop.is_set():
            self._stop.wait(self.config.poll_interval)
            if not self._stop.is_set():
                self.poll_once()

    def _fetch_clearinghouse_state(self, address):
        response = self.api.clearinghouse_state(address)
        if isinstance(response, dict):
            if "clearinghouseState" in response:
                response = response["clearinghouseState"]
            if "user" in response and "marginSummary" not in response:
                # Some mirrors nest the actual state under userState/state.
                nested = response.get("state") or response.get("userState")
                if isinstance(nested, dict):
                    response = nested
        return response

    def _fetch_spot_state(self, address):
        response = self.api.spot_state(address)
        if isinstance(response, dict):
            if "spotClearinghouseState" in response:
                response = response["spotClearinghouseState"]
            if "user" in response and "balances" not in response:
                nested = response.get("spotState") or response.get("state")
                if isinstance(nested, dict):
                    response = nested
        return response

    def _process_state(self, address, state, spot_state=None):
        if not isinstance(state, dict):
            return

        margin = state.get("marginSummary") or state.get("crossMarginSummary") or {}
        account_value = _num(margin.get("accountValue"))
        total_ntl_pos = _num(margin.get("totalNtlPos"))
        withdrawable = _num(state.get("withdrawable"))
        positions = self._extract_positions(state)
        spot_balances = self._extract_spot_balances(spot_state)
        now = int(time.time() * 1000)

        previous_snapshot = self.store.get_last_snapshot(address)
        previous_positions = self.store.get_positions(address)
        previous_spot_balances = self.store.get_spot_balances(address)
        positions = self._attach_open_times(address, positions, previous_positions)
        summary = {
            "account_value": account_value,
            "total_ntl_pos": total_ntl_pos,
            "withdrawable": withdrawable,
        }
        self._add_pnl_summary(address, summary, positions)

        self.store.save_positions(address, positions, now)
        self.store.save_spot_balances(address, spot_balances, now)
        self.store.save_snapshot(address, account_value, total_ntl_pos, withdrawable, now)

        print(
            f"[snapshot] {short_addr(address)} 账户净值 {fmt_usd_cn(account_value)}, "
            f"持仓名义 {fmt_usd_cn(total_ntl_pos)}, "
            f"可提取 {fmt_usd_cn(withdrawable)}, "
            f"现货币种 {len(spot_balances)}"
        )

        if previous_snapshot is None:
            return

        prev_av = _num(previous_snapshot.get("account_value"))
        if prev_av != 0:
            change_pct = abs(account_value - prev_av) / abs(prev_av) * 100.0
            if change_pct >= self.config.rules.account_value_change_pct:
                self._emit(
                    address,
                    "account_change",
                    (
                        f"[账户] 净值变化 {fmt_usd_cn(prev_av)} -> "
                        f"{fmt_usd_cn(account_value)} "
                        f"({(account_value - prev_av):+,.2f}, {change_pct:.2f}%)"
                    ),
                    {
                        "previous_account_value": prev_av,
                        "account_value": account_value,
                        "change_pct": change_pct,
                    },
                    key=f"account:{address}:{previous_snapshot.get('time') or now}",
                )

        self._emit_position_brief_if_changed(
            address,
            previous_positions,
            positions,
            spot_balances,
            summary,
            now,
        )
        self._detect_spot_balance_changes(
            address,
            previous_spot_balances,
            spot_balances,
            now,
        )

    def _extract_positions(self, state):
        positions = {}
        for item in state.get("assetPositions") or []:
            if not isinstance(item, dict):
                continue
            position = item.get("position") or item
            coin = position.get("coin")
            if not coin:
                continue
            positions[coin] = {
                "szi": position.get("szi", "0"),
                "entry_px": position.get("entryPx", ""),
                "notional": position.get("positionValue", position.get("notional", "0")),
                "unrealized_pnl": position.get("unrealizedPnl", ""),
                "leverage": self._extract_leverage(position.get("leverage")),
            }
        return positions

    def _realized_pnl(self, address):
        """从最近成交记录累加已实现盈亏（closedPnl + 手续费），带 5 分钟缓存。"""
        cached_at, cached = self._realized_pnl_cache.get(address, (0.0, None))
        now = time.time()
        if cached_at and now - cached_at < 300:
            return cached
        fills = self._fetch_fill_history(address)
        realized = sum(
            _num(fill.get("closedPnl")) + _num(fill.get("fee"))
            for fill in fills
        )
        self._realized_pnl_cache[address] = (now, realized)
        return realized

    def _add_pnl_summary(self, address, summary, positions):
        summary["unrealized_pnl"] = sum(
            _num(pos.get("unrealized_pnl")) for pos in positions.values()
        )
        try:
            summary["realized_pnl"] = self._realized_pnl(address)
        except Exception as exc:
            print(f"[pnl] 拉取已实现盈亏失败 ({short_addr(address)}): {exc}")
            summary["realized_pnl"] = None
        return summary

    @staticmethod
    def _extract_leverage(leverage):
        if isinstance(leverage, dict):
            return leverage.get("value", "")
        return leverage or ""

    @staticmethod
    def _extract_spot_balances(state):
        balances = {}
        if not isinstance(state, dict):
            return balances
        for item in state.get("balances") or []:
            if not isinstance(item, dict):
                continue
            coin = item.get("coin")
            if not coin:
                continue
            balances[coin] = {
                "total": item.get("total", "0"),
                "hold": item.get("hold", "0"),
            }
        return balances

    def _attach_open_times(self, address, positions, previous_positions):
        now_ms = int(time.time() * 1000)
        cached_at, cached = self._open_time_cache.get(address, (0, {}))
        previous_set = set(previous_positions)
        current_set = set(positions)

        if (
            cached_at
            and now_ms - cached_at < 300_000
            and current_set == previous_set
        ):
            metadata = cached
        else:
            metadata = self._compute_position_metadata_for_address(address, positions)
            self._open_time_cache[address] = (now_ms, metadata)

        for coin, pos in positions.items():
            coin_meta = metadata.get(coin, {})
            pos["open_time_ms"] = coin_meta.get("open_time_ms")
            if not pos["open_time_ms"]:
                pos["open_time_ms"] = previous_positions.get(coin, {}).get(
                    "open_time_ms"
                )
            if not pos["open_time_ms"]:
                pos["open_time_ms"] = 0
            pos["peak_notional"] = coin_meta.get("peak_notional")
            if not pos["peak_notional"]:
                pos["peak_notional"] = previous_positions.get(coin, {}).get(
                    "peak_notional"
                )
            if not pos["peak_notional"]:
                pos["peak_notional"] = pos.get("notional", 0)
        return positions

    def _fetch_fill_history(self, address, lookback_days=180):
        now = int(time.time() * 1000)
        start = now - int(lookback_days) * 86400000
        end = now + 1000
        fills = []
        for _ in range(8):
            batch = None
            last_exc = None
            for attempt in range(3):
                try:
                    batch = self.api.user_fills_by_time(address, start, end) or []
                    break
                except Exception as exc:
                    last_exc = exc
                    time.sleep(0.8 * (attempt + 1))
            if batch is None:
                print(
                    f"[fills] 拉取成交历史失败 ({short_addr(address)}): {last_exc}"
                )
                break
            if not batch:
                break
            fills.extend(batch)
            if len(batch) < 2000 or len(fills) >= 10000:
                break
            times = [int(item.get("time", 0)) for item in batch if item.get("time")]
            if not times:
                break
            end = min(times) - 1
            if end <= 0:
                break
        return fills

    def _position_metadata_from_fills(self, fills, positions):
        grouped = {}
        for fill in fills:
            coin = fill.get("coin", "")
            if not coin or coin.startswith("@"):
                continue
            grouped.setdefault(coin, []).append(fill)

        for coin, fills_for_coin in grouped.items():
            grouped[coin] = sorted(
                fills_for_coin,
                key=lambda item: int(item.get("time") or 0),
            )

        metadata = {}
        for coin, pos in positions.items():
            target_sign = 1 if _num(pos.get("szi")) > 0 else -1
            coin_fills = grouped.get(coin, [])
            open_ts = None
            peak_notional = 0.0
            for fill in coin_fills:
                start = _num(fill.get("startPosition"))
                size = _num(fill.get("sz"))
                price = _num(fill.get("px"))
                side = str(fill.get("side", "")).upper()
                if side == "B":
                    new_pos = start + size
                elif side == "A":
                    new_pos = start - size
                else:
                    new_pos = start

                old_sign = 0 if abs(start) < 1e-12 else (1 if start > 0 else -1)
                new_sign = 0 if abs(new_pos) < 1e-12 else (1 if new_pos > 0 else -1)
                if new_sign == target_sign and old_sign != target_sign:
                    open_ts = fill.get("time")
                elif new_sign != target_sign:
                    open_ts = None
                if new_sign == target_sign:
                    peak_notional = max(
                        peak_notional,
                        abs(new_pos) * price,
                    )

            if open_ts is None and coin_fills:
                open_ts = coin_fills[0].get("time")
            metadata[coin] = {
                "open_time_ms": int(open_ts) if open_ts else 0,
                "peak_notional": peak_notional
                or abs(_num(pos.get("notional"))),
            }
        return metadata

    def _compute_position_metadata_for_address(self, address, positions):
        fills = self._fetch_fill_history(address)
        return self._position_metadata_from_fills(fills, positions)

    def _emit_position_brief_if_changed(
        self,
        address,
        previous,
        current,
        spot_balances,
        summary,
        now,
    ):
        changes = {}
        notional_changed = False
        for coin, pos in current.items():
            if coin not in previous:
                changes[coin] = (
                    f"开仓 {fmt_usd_cn(abs(_num(pos.get('notional'))))}"
                )
                continue
            prev = previous[coin]
            prev_szi = _num(prev.get("szi"))
            cur_szi = _num(pos.get("szi"))
            prev_notional = _num(prev.get("notional"))
            cur_notional = _num(pos.get("notional"))
            delta_szi = cur_szi - prev_szi
            delta_notional = cur_notional - prev_notional
            if abs(delta_szi) > 1e-9:
                if abs(cur_szi) > abs(prev_szi):
                    changes[coin] = f"加仓 {fmt_usd_cn(abs(delta_notional))}"
                else:
                    changes[coin] = f"减仓 {fmt_usd_cn(abs(delta_notional))}"
            elif abs(delta_notional) >= self.config.rules.position_delta_min_usd:
                notional_changed = True

        closed_positions = []
        for coin, prev in previous.items():
            if coin not in current:
                prev_szi = _num(prev.get("szi"))
                side_cn = "多" if prev_szi > 0 else ("空" if prev_szi < 0 else "")
                closed_positions.append(
                    (
                        coin,
                        f"平{side_cn}仓 {fmt_usd_cn(abs(_num(prev.get('notional'))))}",
                    )
                )

        if not changes and not closed_positions and not notional_changed:
            return

        text = format_position_brief(
            address,
            summary,
            current,
            spot_balances=spot_balances,
            sort_mode=self.config.position_sort,
            title="持仓变动简报",
            changes=changes,
            closed_positions=closed_positions,
            include_spot=False,
        )
        self._emit(
            address,
            "position_brief",
            text,
            {
                "summary": summary,
                "positions": current,
                "spot_balances": spot_balances,
                "changes": changes,
                "closed_positions": closed_positions,
                "title": "持仓变动简报",
                "include_spot": False,
            },
            key=f"posbrief:{address}:{now}",
        )

    def _detect_spot_balance_changes(self, address, previous, current, now):
        for coin, balance in current.items():
            if coin not in previous:
                if _num(balance.get("total")) != 0:
                    self._emit(
                        address,
                        "spot_balance_open",
                        f"[现货] 新余额 {coin}: {balance.get('total')}",
                        balance,
                        key=f"spotopen:{address}:{coin}:{now}",
                    )
                continue

            prev = previous[coin]
            if abs(_num(balance.get("total")) - _num(prev.get("total"))) > 1e-9:
                self._emit(
                    address,
                    "spot_balance_change",
                    (
                        f"[现货] {coin} {prev.get('total')} -> "
                        f"{balance.get('total')}"
                    ),
                    {"previous": prev, "current": balance},
                    key=f"spotchg:{address}:{coin}:{now}",
                )

        for coin, balance in previous.items():
            if coin not in current and _num(balance.get("total")) != 0:
                self._emit(
                    address,
                    "spot_balance_close",
                    f"[现货] 余额归零 {coin}",
                    balance,
                    key=f"spotclose:{address}:{coin}:{now}",
                )

    def _on_ws_message(self, address, channel, data):
        try:
            if channel == "userFills":
                self._handle_fills(address, data)
            elif channel in ("user", "userEvents"):
                self._handle_user_events(address, data)
            elif channel == "userNonFundingLedgerUpdates":
                self._handle_ledger_updates(address, data)
        except Exception as exc:
            print(f"[monitor] 处理 WebSocket 消息失败 ({short_addr(address)}): {exc}")

    def _handle_fills(self, address, data):
        if isinstance(data, dict) and data.get("isSnapshot") and self.config.rules.ignore_ws_snapshots:
            return
        for fill in self._iter_fills(data):
            self._handle_fill(address, fill)

    def _iter_fills(self, data):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            fills = data.get("fills")
            if isinstance(fills, list):
                return fills
            if data.get("coin"):
                return [data]
        return []

    def _handle_fill(self, address, fill):
        if not isinstance(fill, dict):
            return
        coin = fill.get("coin", "?")
        side = fmt_side(fill.get("side"))
        direction = fmt_dir(fill.get("dir"))
        size = fmt_szi(fill.get("sz"))
        price = fill.get("px", "-")
        notional = abs(_num(size) * _num(price))
        text = (
            f"[成交] {coin} {side} {size} @ {price}，"
            f"{direction}，成交额约 {fmt_usd_cn(notional)}"
        )
        self._emit(
            address,
            "fill",
            text,
            fill,
            key=self._fill_key(address, fill),
            ts=_num(fill.get("time"), time.time() * 1000),
        )

    @staticmethod
    def _fill_key(address, fill):
        tid = fill.get("tid")
        if tid is not None:
            return f"fill:{address}:{tid}"
        return (
            f"fill:{address}:{fill.get('hash', '')}:{fill.get('coin', '')}:"
            f"{fill.get('time', '')}:{fill.get('startPosition', '')}"
        )

    def _handle_user_events(self, address, data):
        if isinstance(data, dict) and data.get("isSnapshot") and self.config.rules.ignore_ws_snapshots:
            return
        if isinstance(data, list):
            for item in data:
                self._handle_user_event_item(address, item)
            return
        self._handle_user_event_item(address, data)

    def _handle_user_event_item(self, address, item):
        if not isinstance(item, dict):
            return
        if "liquidation" in item:
            event = item["liquidation"]
            lid = event.get("lid")
            self._emit(
                address,
                "liquidation",
                (
                    f"[清算] lid={lid}，清算持仓名义 "
                    f"{event.get('liquidated_ntl_pos', '-')}，"
                    f"账户价值 {event.get('liquidated_account_value', '-')}"
                ),
                event,
                key=f"liquidation:{address}:{lid}",
            )
        elif "funding" in item:
            if not self.config.rules.alert_funding:
                return
            event = item["funding"]
            coin = event.get("coin", "?")
            self._emit(
                address,
                "funding",
                (
                    f"[资金费] {coin} {fmt_usd_cn(event.get('usdc', 0))} USDC，"
                    f"持仓 {fmt_szi(event.get('szi', '0'))}，"
                    f"费率 {event.get('fundingRate', '-')}"
                ),
                event,
                key=(
                    f"funding:{address}:{event.get('time', '')}:"
                    f"{coin}:{event.get('szi', '')}"
                ),
                ts=_num(event.get("time"), time.time() * 1000),
            )
        elif "nonUserCancel" in item:
            for order in item["nonUserCancel"] or []:
                if not isinstance(order, dict):
                    continue
                self._emit(
                    address,
                    "order_cancel",
                    f"[撤单] {order.get('coin', '?')} oid={order.get('oid', '-')}",
                    order,
                    key=f"cancel:{address}:{order.get('coin', '')}:{order.get('oid', '')}",
                )
        # `fills` inside userEvents are intentionally ignored because userFills
        # is subscribed separately, avoiding duplicate alerts.

    def _handle_ledger_updates(self, address, data):
        if isinstance(data, dict) and data.get("isSnapshot") and self.config.rules.ignore_ws_snapshots:
            return
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (
                data.get("nonFundingLedgerUpdates")
                or data.get("updates")
                or [data]
            )
        else:
            items = []

        for index, item in enumerate(items or []):
            if not isinstance(item, dict):
                continue
            delta = item.get("delta") or item
            self._emit(
                address,
                "ledger",
                self._ledger_text(delta),
                item,
                key=(
                    f"ledger:{address}:{item.get('time', '')}:"
                    f"{item.get('hash', '')}:{delta.get('type', '')}:{index}"
                ),
                ts=_num(item.get("time"), time.time() * 1000),
            )

    @staticmethod
    def _ledger_text(delta):
        if not isinstance(delta, dict):
            return f"[资金流] {delta}"
        kind = delta.get("type", "update")
        if kind == "deposit":
            return f"[资金流] 充值 {fmt_usd_cn(delta.get('usdc', 0))} USDC"
        if kind == "withdraw":
            return (
                f"[资金流] 提现 {fmt_usd_cn(delta.get('usdc', 0))} USDC"
                f"（手续费 {fmt_usd_cn(delta.get('fee', 0))}）"
            )
        if kind == "internalTransfer":
            return (
                f"[资金流] 内部转账 {fmt_usd_cn(delta.get('usdc', 0))} USDC -> "
                f"{delta.get('destination', '-')}"
            )
        if kind == "subAccountTransfer":
            return (
                f"[资金流] 子账户转账 {fmt_usd_cn(delta.get('usdc', 0))} USDC -> "
                f"{delta.get('destination', '-')}"
            )
        if kind == "liquidation":
            positions = ", ".join(
                f"{p.get('coin', '?')} {fmt_szi(p.get('szi', '0'))}"
                for p in (delta.get("liquidatedPositions") or [])
            )
            return (
                f"[资金流] 清算，账户价值 {fmt_usd_cn(delta.get('accountValue', 0))}，"
                f"清算持仓: {positions or '-'}"
            )
        if kind == "spotTransfer":
            return (
                f"[资金流] 现货转账 {delta.get('amount', '0')} "
                f"{delta.get('token', '?')} -> {delta.get('destination', '-')}"
            )
        if kind == "send":
            return (
                f"[资金流] 发送 {delta.get('amount', '0')} "
                f"{delta.get('token', '?')} -> {delta.get('destination', '-')}"
                f"（约 {fmt_usd_cn(delta.get('usdcValue', 0))}）"
            )
        if kind == "vaultDeposit":
            return f"[资金流] 存入金库 {fmt_usd_cn(delta.get('usdc', 0))} USDC"
        if kind == "vaultWithdraw":
            return (
                f"[资金流] 金库提现 {fmt_usd_cn(delta.get('netWithdrawnUsd', 0))} USDC，"
                f"请求 {fmt_usd_cn(delta.get('requestedUsd', 0))}"
            )
        if kind == "accountClassTransfer":
            direction = "现货转合约" if delta.get("toPerp") else "合约转现货"
            return f"[资金流] 账户类型划转 {fmt_usd_cn(delta.get('usdc', 0))} USDC（{direction}）"
        if kind == "spotGenesis":
            return f"[资金流] 现货生成 {delta.get('amount', '0')} {delta.get('token', '?')}"
        if kind == "rewardsClaim":
            return f"[资金流] 领取奖励 {fmt_usd_cn(delta.get('amount', 0))}"
        return f"[资金流] {kind}: {json.dumps(delta, ensure_ascii=False)}"

    def _emit(self, address, kind, text, data, key=None, ts=None):
        event_time = int(ts or time.time() * 1000)
        if key:
            is_new = self.store.save_event(
                key,
                event_time,
                address,
                kind,
                text,
                data,
            )
            if not is_new:
                return
        self.notifier.notify(
            {
                "time": event_time,
                "address": address,
                "kind": kind,
                "text": text,
                "data": data,
            }
        )
