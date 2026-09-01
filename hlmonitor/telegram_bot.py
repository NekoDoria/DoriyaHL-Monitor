"""Interactive Telegram bot for managing and receiving Hyperliquid alerts."""

from __future__ import annotations

import json
import html
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import Config, normalize_address
from .brief import BRIEF_PAGE_SIZE, format_position_brief_html_data, sort_positions
from .format import fmt_szi, fmt_time, fmt_usd_cn, short_addr
from .monitor import AddressMonitor
from .net import build_opener
from .state import EventStore


HELP_TEXT = """Hyperliquid 地址监控 Bot

/add 0x地址 [别名] - 添加监控地址
/name 命名 0x地址 - 给已添加的地址设置显示名称
/remove 0x地址 - 删除地址
/removeall - 删除当前聊天的全部地址
/list - 查看当前监控列表
/status [0x地址] - 查询当前账户/持仓状态
/stats [0x地址] - 打开或刷新成交统计面板
/history [0x地址] - 查看历史持仓（来自最近成交记录）
/tpsl [0x地址] - 查看当前挂着的止盈止损单
/orders [0x地址] - 查看普通挂单：先选账户，再选标的，价格相近的会合并成密集区间
/recent [条数] - 查看最近事件
/coins - 选择要接收交易通知的币种
/mute - 暂停当前聊天的告警
/unmute - 恢复当前聊天的告警
/help - 显示本帮助

告警会自动发送到添加地址时所在的聊天。
持仓简报下方有按钮，可直接切换按仓位价值或按开仓时间排序。
成交通知会自动汇总为 5/15 分钟窗口，并在同一条实时消息中刷新。"""


def address_selector_rows(subscriptions, selected_address=None, prefix="as"):
    rows = []
    row = []
    for sub in subscriptions:
        address = sub["address"]
        alias = sub.get("alias") or short_addr(address)
        label = f"✅ {alias}" if address == selected_address else alias
        row.append(
            {
                "text": label,
                "callback_data": f"{prefix}:{address}",
            }
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def brief_keyboard(
    address,
    sort_mode="value",
    page=0,
    page_count=1,
    subscriptions=None,
    selected_address=None,
):
    """Return an inline keyboard for address, sorting and paging controls."""
    rows = []
    if subscriptions:
        rows.extend(
            address_selector_rows(subscriptions, selected_address, "asb")
        )
    rows.append(
        [
            {
                "text": (
                    "✅ 按仓位价值"
                    if sort_mode == "value"
                    else "按仓位价值"
                ),
                "callback_data": f"brief:{address}:value",
            },
            {
                "text": (
                    "✅ 按开仓时间"
                    if sort_mode == "time"
                    else "按开仓时间"
                ),
                "callback_data": f"brief:{address}:time",
            },
        ]
    )
    if page_count > 1:
        nav = []
        if page > 0:
            nav.append(
                {
                    "text": "◀️ 上一页",
                    "callback_data": f"bp:{address}:{page - 1}",
                }
            )
        nav.append(
            {
                "text": f"{page + 1}/{page_count}",
                "callback_data": "ignore",
            }
        )
        if page < page_count - 1:
            nav.append(
                {
                    "text": "下一页 ▶️",
                    "callback_data": f"bp:{address}:{page + 1}",
                }
            )
        rows.append(nav)
    return {"inline_keyboard": rows}


COIN_PAGE_SIZE = 20
COIN_COLS = 5

MAIN_COINS = [
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "XRP",
    "DOGE",
    "ADA",
    "AVAX",
    "LINK",
    "LTC",
    "BCH",
    "DOT",
    "TON",
    "UNI",
    "SUI",
    "HYPE",
    "TRX",
    "NEAR",
    "APT",
    "ARB",
    "OP",
    "INJ",
    "RENDER",
    "TAO",
    "TIA",
    "ONDO",
    "JUP",
    "SEI",
    "WLD",
    "AAVE",
]

PRECIOUS_METAL_COINS = ["PAXG", "XAUT", "XAU", "XAG"]


def coin_category_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "主流币种",
                    "callback_data": "c:cat:main",
                },
                {
                    "text": "贵金属",
                    "callback_data": "c:cat:metal",
                },
            ],
            [
                {
                    "text": "其他币种",
                    "callback_data": "c:cat:other",
                }
            ],
        ]
    }


def coin_list_keyboard(coins, selected, page=0, category="main"):
    total_pages = max(1, (len(coins) + COIN_PAGE_SIZE - 1) // COIN_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * COIN_PAGE_SIZE
    page_coins = coins[start : start + COIN_PAGE_SIZE]

    rows = []
    for index in range(0, len(page_coins), COIN_COLS):
        row = []
        for coin in page_coins[index : index + COIN_COLS]:
            row.append(
                {
                    "text": f"✅ {coin}" if coin in selected else coin,
                    "callback_data": f"c:{category}:t:{page}:{coin}",
                }
            )
        rows.append(row)

    nav = []
    if page > 0:
        nav.append(
            {
                "text": "◀️ 上一页",
                "callback_data": f"c:{category}:n:{page - 1}",
            }
        )
    if page < total_pages - 1:
        nav.append(
            {
                "text": "下一页 ▶️",
                "callback_data": f"c:{category}:n:{page + 1}",
            }
        )
    if nav:
        rows.append(nav)

    rows.append(
        [
            {
                "text": "全选",
                "callback_data": f"c:{category}:a",
            },
            {
                "text": "清空",
                "callback_data": f"c:{category}:c",
            },
        ]
    )
    rows.append(
        [
            {
                "text": "返回分类",
                "callback_data": "c:back",
            }
        ]
    )
    return {"inline_keyboard": rows}


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fill_stats_keyboard(
    address,
    window_min=5,
    subscriptions=None,
    selected_address=None,
):
    rows = []
    if subscriptions:
        rows.extend(
            address_selector_rows(subscriptions, selected_address, "asf")
        )
    buttons = []
    for window in (5, 15):
        text = f"✅ {window}分钟" if window == window_min else f"{window}分钟"
        buttons.append(
            {
                "text": text,
                "callback_data": f"fs:{address}:{window}",
            }
        )
    rows.append(buttons)
    return {"inline_keyboard": rows}


def format_fill_stats_html(address, fills, window_min=5, now=None):
    now = now or int(time.time() * 1000)
    cutoff = now - window_min * 60_000
    recent = [fill for fill in fills if int(fill.get("time") or 0) >= cutoff]

    lines = [
        f"<b>📈 成交统计 · {html.escape(short_addr(address))}</b>",
        f"窗口: {window_min}分钟 | 更新时间: {html.escape(fmt_time(now))}",
    ]
    if not recent:
        lines.append("")
        lines.append("当前窗口暂无成交")
        return "\n".join(lines)

    grouped = {}
    for fill in recent:
        coin = fill.get("coin", "?")
        size = abs(_as_float(fill.get("sz")))
        price = _as_float(fill.get("px"))
        item = grouped.setdefault(
            coin,
            {
                "count": 0,
                "size": 0.0,
                "notional": 0.0,
                "buy_size": 0.0,
                "buy_notional": 0.0,
                "sell_size": 0.0,
                "sell_notional": 0.0,
                "last_time": 0,
            },
        )
        item["count"] += 1
        item["size"] += size
        value = size * price
        item["notional"] += value
        if fill.get("side") == "B":
            item["buy_size"] += size
            item["buy_notional"] += value
        else:
            item["sell_size"] += size
            item["sell_notional"] += value
        item["last_time"] = max(item["last_time"], int(fill.get("time") or 0))

    ordered = sorted(
        grouped.items(),
        key=lambda item: item[1]["notional"],
        reverse=True,
    )
    total_notional = sum(item["notional"] for _, item in ordered)
    lines.append(f"总成交额: {html.escape(fmt_usd_cn(total_notional))}")

    for coin, stat in ordered[:20]:
        net = stat["buy_notional"] - stat["sell_notional"]
        if net > 1e-9:
            direction = "净多"
        elif net < -1e-9:
            direction = "净空"
        else:
            direction = "均衡"
        body = "\n".join(
            [
                html.escape(f"笔数: {stat['count']}"),
                html.escape(
                    f"买入: {fmt_szi(stat['buy_size'])} / "
                    f"{fmt_usd_cn(stat['buy_notional'])}"
                ),
                html.escape(
                    f"卖出: {fmt_szi(stat['sell_size'])} / "
                    f"{fmt_usd_cn(stat['sell_notional'])}"
                ),
                html.escape(f"成交额: {fmt_usd_cn(stat['notional'])}"),
                html.escape(f"最近: {fmt_time(stat['last_time'])}"),
            ]
        )
        lines.append("")
        lines.append(
            f"<b>{html.escape(coin)} · {direction}</b>\n"
            f"<blockquote expandable>{body}</blockquote>"
        )
    if len(ordered) > 20:
        lines.append("")
        lines.append(f"... 其余 {len(ordered) - 20} 个标的省略")
    return "\n".join(lines)


class TelegramClient:
    def __init__(self, token, proxy_url=None, timeout=70):
        if not token:
            raise ValueError("Telegram bot token is required")
        self.token = token.strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.timeout = timeout
        self.opener, self.fallback_opener = self._build_openers(proxy_url)

    @staticmethod
    def _build_openers(proxy_url):
        if not proxy_url:
            return build_opener(None), None

        parsed = urllib.parse.urlparse(proxy_url)
        scheme = (parsed.scheme or "").lower()
        if scheme in {"socks", "socks5", "socks5h"} and parsed.hostname:
            port = parsed.port or 7890
            http_proxy = f"http://{parsed.hostname}:{port}"
            return build_opener(http_proxy), build_opener(proxy_url)

        return build_opener(proxy_url), None

    def _call(self, method, payload):
        url = f"{self.base_url}/{method}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = self.opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError:
            if self.fallback_opener is None:
                raise
            resp = self.fallback_opener.open(req, timeout=self.timeout)

        with resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError(f"Telegram API {method}: {body}")
        return body.get("result")

    def delete_webhook(self):
        return self._call("deleteWebhook", {"drop_pending_updates": True})

    def get_me(self):
        return self._call("getMe", {})

    def get_updates(self, offset=None, timeout=50):
        payload = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        return self._call("getUpdates", payload)

    def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._call("sendMessage", payload)

    def edit_message_text(
        self,
        chat_id,
        message_id,
        text,
        reply_markup=None,
        parse_mode=None,
    ):
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._call("editMessageText", payload)

    def answer_callback_query(self, callback_query_id, text=None):
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return self._call("answerCallbackQuery", payload)


class TelegramRouter:
    """Route monitor events to chats subscribed to the affected address."""

    def __init__(self, client: TelegramClient, store: EventStore, fallback_chat_id=None):
        self.client = client
        self.store = store
        self.fallback_chat_id = str(fallback_chat_id) if fallback_chat_id else None
        self._fill_buffers = {}
        self._fill_lock = threading.RLock()
        self._fill_dirty = set()
        self._fill_timer = None

    def _subscriptions_for_chat(self, chat_id):
        return self.store.get_subscriptions(chat_id=chat_id, active_only=False)

    def _get_or_create_selected_address(self, chat_id, preferred):
        subscriptions = self._subscriptions_for_chat(chat_id)
        addresses = [sub["address"] for sub in subscriptions]
        if not addresses:
            return preferred
        selected = self.store.get_chat_setting(
            chat_id,
            "selected_brief_address",
            None,
        )
        if selected in addresses:
            return selected
        selected = preferred if preferred in addresses else addresses[0]
        self.store.set_chat_setting(
            chat_id,
            "selected_brief_address",
            selected,
            int(time.time() * 1000),
        )
        return selected

    def _get_or_create_selected_fill_stats_address(self, chat_id, preferred):
        subscriptions = self._subscriptions_for_chat(chat_id)
        addresses = [sub["address"] for sub in subscriptions]
        if not addresses:
            return preferred
        selected = self.store.get_chat_setting(
            chat_id,
            "selected_fill_stats_address",
            None,
        )
        if selected in addresses:
            return selected
        selected = preferred if preferred in addresses else addresses[0]
        self.store.set_chat_setting(
            chat_id,
            "selected_fill_stats_address",
            selected,
            int(time.time() * 1000),
        )
        return selected

    def notify(self, event):
        address = event.get("address", "")
        chats = self.store.subscribed_chats(address, active_only=False)
        if not chats and self.fallback_chat_id:
            chats = [self.fallback_chat_id]

        for chat_id in dict.fromkeys(chats):
            if not self._should_notify_chat(event, chat_id):
                continue
            if event.get("kind") == "fill":
                self._ingest_fill(event, chat_id)
                continue
            if event.get("kind") == "position_brief":
                if self._is_muted(chat_id) and not self._has_live_message(
                    chat_id,
                    "live_brief_panel",
                ):
                    continue
                sort_mode = self.store.get_chat_setting(
                    chat_id,
                    "position_sort",
                    "value",
                )
                selected_address = self._get_or_create_selected_address(
                    chat_id,
                    event.get("address", ""),
                )
                if selected_address != event.get("address", ""):
                    continue
                try:
                    self._publish_position_brief(
                        chat_id,
                        event.get("address", ""),
                        event.get("data", {}),
                        sort_mode,
                        selected_address=selected_address,
                    )
                except Exception as exc:
                    print(f"[telegram] 更新实时简报失败 ({chat_id}): {exc}")
            else:
                if self._is_muted(chat_id):
                    continue
                text = self._format_for_chat(event, chat_id)
                try:
                    self.client.send_message(chat_id, text)
                except Exception as exc:
                    print(f"[telegram] 发送失败 ({chat_id}): {exc}")

    def _publish_position_brief(
        self,
        chat_id,
        address,
        data,
        sort_mode,
        force_new=False,
        target_message_id=None,
        selected_address=None,
    ):
        sorted_positions = sort_positions(data.get("positions", []), sort_mode)
        page_count = max(
            1,
            math.ceil(len(sorted_positions) / BRIEF_PAGE_SIZE),
        )
        try:
            page = int(self.store.get_chat_setting(
                chat_id,
                f"brief_page:{address}",
                0,
            ))
        except (TypeError, ValueError):
            page = 0
        page = max(0, min(page, page_count - 1))

        text = format_position_brief_html_data(
            data,
            sort_mode,
            page=page,
            page_size=BRIEF_PAGE_SIZE,
        )
        reply_markup = brief_keyboard(
            address,
            sort_mode,
            page,
            page_count,
            subscriptions=self.store.get_subscriptions(
                chat_id=chat_id,
                active_only=False,
            ),
            selected_address=selected_address or address,
        )
        key = "live_brief_panel"
        message_id = self.store.get_chat_setting(chat_id, key, None)

        if target_message_id is not None:
            try:
                self.client.edit_message_text(
                    chat_id,
                    int(target_message_id),
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
            except Exception as exc:
                print(f"[telegram] 更新指定简报失败: {exc}")
            return

        if force_new:
            message_id = None

        if message_id is not None:
            try:
                self.client.edit_message_text(
                    chat_id,
                    int(message_id),
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
                return
            except Exception as exc:
                print(f"[telegram] 实时消息已失效，重新发送: {exc}")

        result = self.client.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        new_message_id = (result or {}).get("message_id")
        if new_message_id is not None:
            self.store.set_chat_setting(
                chat_id,
                key,
                str(new_message_id),
                int(time.time() * 1000),
            )

    def _should_notify_chat(self, event, chat_id):
        if event.get("kind") != "fill":
            return True
        raw = self.store.get_chat_setting(chat_id, "notify_coins", None)
        if raw is None:
            return True
        try:
            selected = set(json.loads(raw))
        except (TypeError, ValueError):
            return True
        coin = event.get("data", {}).get("coin", "")
        return coin in selected

    def _is_muted(self, chat_id):
        return self.store.get_chat_setting(
            chat_id,
            "notifications_muted",
            "0",
        ) == "1"

    def _has_live_message(self, chat_id, key):
        return self.store.get_chat_setting(chat_id, key, None) is not None

    def _ingest_fill(self, event, chat_id):
        address = event.get("address", "")
        fill = event.get("data", {})
        if not address or not fill.get("coin"):
            return
        timestamp = int(event.get("time") or fill.get("time") or time.time() * 1000)
        key = (chat_id, address)
        with self._fill_lock:
            self._fill_buffers.setdefault(key, []).append(
                {
                    "time": timestamp,
                    "coin": fill.get("coin"),
                    "side": str(fill.get("side", "")).upper(),
                    "sz": fill.get("sz", "0"),
                    "px": fill.get("px", "0"),
                }
            )
            self._prune_fill_buffer(key)
            self._fill_dirty.add(key)
        self._schedule_fill_flush()

    def _prune_fill_buffer(self, key):
        cutoff = int(time.time() * 1000) - 15 * 60_000
        self._fill_buffers[key] = [
            fill
            for fill in self._fill_buffers.get(key, [])
            if int(fill.get("time") or 0) >= cutoff
        ]

    def _schedule_fill_flush(self):
        with self._fill_lock:
            if self._fill_timer is not None and self._fill_timer.is_alive():
                return
            timer = threading.Timer(2.0, self._flush_dirty_fills)
            timer.daemon = True
            self._fill_timer = timer
            timer.start()

    def _flush_dirty_fills(self):
        with self._fill_lock:
            dirty = list(self._fill_dirty)
            self._fill_dirty.clear()
            snapshots = {
                key: list(self._fill_buffers.get(key, []))
                for key in dirty
            }
            self._fill_timer = None

        for key, fills in snapshots.items():
            chat_id, address = key
            selected_address = self._get_or_create_selected_fill_stats_address(
                chat_id,
                address,
            )
            if selected_address != address:
                continue
            if self._is_muted(chat_id) and not self._has_live_message(
                chat_id,
                "live_fill_stats_panel",
            ):
                continue
            try:
                self._publish_fill_stats(
                    chat_id,
                    address,
                    fills,
                    selected_address=selected_address,
                )
            except Exception as exc:
                print(f"[telegram] 刷新成交统计失败 ({chat_id}): {exc}")

    def refresh_fill_stats(self, chat_id, address, force_new=False):
        with self._fill_lock:
            fills = list(self._fill_buffers.get((chat_id, address), []))
        self._publish_fill_stats(
            chat_id,
            address,
            fills,
            selected_address=address,
            force_new=force_new,
        )

    def _publish_fill_stats(
        self,
        chat_id,
        address,
        fills,
        selected_address=None,
        force_new=False,
    ):
        try:
            window_min = int(
                self.store.get_chat_setting(
                    chat_id,
                    f"fill_stats_window:{address}",
                    "5",
                )
            )
        except (TypeError, ValueError):
            window_min = 5
        if window_min not in {5, 15}:
            window_min = 5

        text = format_fill_stats_html(address, fills, window_min)
        reply_markup = fill_stats_keyboard(
            address,
            window_min,
            subscriptions=self.store.get_subscriptions(
                chat_id=chat_id,
                active_only=False,
            ),
            selected_address=selected_address or address,
        )
        key = "live_fill_stats_panel"
        message_id = self.store.get_chat_setting(chat_id, key, None)
        if force_new:
            message_id = None
        if message_id is not None:
            try:
                self.client.edit_message_text(
                    chat_id,
                    int(message_id),
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
                return
            except Exception as exc:
                print(f"[telegram] 成交统计消息已失效，重新发送: {exc}")

        result = self.client.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        new_message_id = (result or {}).get("message_id")
        if new_message_id is not None:
            self.store.set_chat_setting(
                chat_id,
                key,
                str(new_message_id),
                int(time.time() * 1000),
            )

    def _format_for_chat(self, event, chat_id):
        kind = event.get("kind", "event")
        return (
            f"{event.get('text', '')}\n\n"
            f"地址: {short_addr(event.get('address', ''))}\n"
            f"类型: {kind}\n"
            f"时间: {fmt_time(event.get('time'))}"
        )


class TelegramBot:
    def __init__(self, config: Config, client=None, store=None, monitor=None):
        self.config = config
        telegram = config.alerts.get("telegram", {})
        self.token = str(telegram.get("bot_token", "")).strip()
        self.fallback_chat_id = str(telegram.get("chat_id", "")).strip() or None
        self.allowed_chat_ids = {
            str(chat_id)
            for chat_id in (telegram.get("allowed_chat_ids") or [])
            if str(chat_id).strip()
        }

        self.client = client or TelegramClient(
            self.token,
            proxy_url=config.proxy_url,
        )
        self.store = store or EventStore(str(config.db_path))
        self.router = TelegramRouter(
            self.client,
            self.store,
            fallback_chat_id=self.fallback_chat_id,
        )
        self.monitor = monitor or AddressMonitor(
            config,
            store=self.store,
            notifier=self.router,
        )
        self._stop = threading.Event()
        self._poll_thread = None
        self._update_offset = None
        self._universe_cache = None
        self._universe_cache_at = 0

    def start(self):
        self.client.delete_webhook()
        me = self.client.get_me()
        print(f"[telegram] Bot 已启动: @{me.get('username', self.token[:8])}")

        self._seed_default_subscriptions()
        self.monitor.set_addresses(self.store.all_watched_addresses(active_only=False))
        self.monitor.start()

        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="telegram-bot-poll",
            daemon=True,
        )
        self._poll_thread.start()

    def _seed_default_subscriptions(self):
        if self.store.all_watched_addresses(active_only=False):
            return
        if not self.config.addresses or not self.fallback_chat_id:
            return
        now = int(time.time() * 1000)
        for address in self.config.addresses:
            self.store.subscribe(self.fallback_chat_id, address, ts=now)
        if self.config.addresses:
            self.store.set_chat_setting(
                self.fallback_chat_id,
                "selected_brief_address",
                self.config.addresses[0],
                now,
            )
            self.store.set_chat_setting(
                self.fallback_chat_id,
                "selected_fill_stats_address",
                self.config.addresses[0],
                now,
            )

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
        self.monitor.stop()
        self.store.close()
        print("[telegram] Bot 已停止")

    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                updates = self.client.get_updates(
                    offset=self._update_offset,
                    timeout=0,
                )
            except Exception as exc:
                print(f"[telegram] 拉取更新失败: {exc}")
                self._stop.wait(3)
                continue

            for update in updates or []:
                self._update_offset = update.get("update_id", 0) + 1
                try:
                    self._process_update(update)
                except Exception as exc:
                    print(f"[telegram] 处理更新失败: {exc}")

            self._stop.wait(0.2 if updates else 1.0)

    def _process_update(self, update):
        callback = update.get("callback_query")
        if callback:
            self._process_callback(callback)
            return

        message = update.get("message") or update.get("edited_message")
        if not message:
            return
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            return
        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            self.client.send_message(chat_id, "你没有权限使用此 Bot。")
            return

        text = (message.get("text") or "").strip()
        if not text.startswith("/"):
            return

        parts = text.split(maxsplit=1)
        command = parts[0].split("@", 1)[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""
        self._dispatch(chat_id, command, args)

    def _process_callback(self, callback):
        callback_id = callback.get("id")
        data = callback.get("data", "")
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        message_id = message.get("message_id")
        if not callback_id or not chat_id or message_id is None:
            return
        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            self.client.answer_callback_query(callback_id, "没有权限。")
            return

        if data.startswith("asb:"):
            self._handle_brief_address_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("asf:"):
            self._handle_stats_address_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("ast:"):
            self._handle_tpsl_address_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("aso:"):
            self._handle_orders_address_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("osc:"):
            self._handle_orders_coin_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("osa:"):
            self._handle_orders_all_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("obc:"):
            self._handle_orders_back_coins_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("oba:"):
            self._handle_orders_back_accounts_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("om:"):
            self._handle_orders_level_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("c:"):
            self._handle_coin_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("fs:"):
            self._handle_fill_stats_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("bp:"):
            self._handle_brief_page_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if not data.startswith("brief:"):
            self.client.answer_callback_query(callback_id)
            return

        try:
            _, address, sort_mode = data.split(":", 2)
            address = normalize_address(address)
        except (ValueError, TypeError):
            self.client.answer_callback_query(callback_id, "无效的按钮数据。")
            return

        if sort_mode not in {"value", "time"}:
            self.client.answer_callback_query(callback_id, "无效的排序方式。")
            return

        self.store.set_chat_setting(
            chat_id,
            "position_sort",
            sort_mode,
            int(time.time() * 1000),
        )
        try:
            brief_data = self.monitor.snapshot_data(address)
            self.router._publish_position_brief(
                chat_id,
                address,
                brief_data,
                sort_mode,
                target_message_id=message_id,
            )
        except Exception as exc:
            print(f"[telegram] 更新简报失败: {exc}")
            self.client.answer_callback_query(callback_id, "更新失败，请重试。")
            return

        label = "开仓时间" if sort_mode == "time" else "仓位价值"
        self.client.answer_callback_query(callback_id, f"已切换为{label}排序。")

    def _handle_fill_stats_callback(self, callback_id, chat_id, message_id, data):
        try:
            _, address, window_text = data.split(":", 2)
            address = normalize_address(address)
            window_min = int(window_text)
        except (ValueError, TypeError):
            self.client.answer_callback_query(callback_id)
            return
        if window_min not in {5, 15}:
            self.client.answer_callback_query(callback_id)
            return

        self.store.set_chat_setting(
            chat_id,
            f"fill_stats_window:{address}",
            str(window_min),
            int(time.time() * 1000),
        )
        try:
            self.router.refresh_fill_stats(chat_id, address)
        except Exception as exc:
            print(f"[telegram] 切换成交统计窗口失败: {exc}")
            self.client.answer_callback_query(callback_id, "切换失败，请重试。")
            return
        self.client.answer_callback_query(callback_id, f"已切换为{window_min}分钟窗口。")

    def _handle_brief_address_callback(self, callback_id, chat_id, message_id, data):
        try:
            address = normalize_address(data.split(":", 1)[1])
        except (ValueError, IndexError):
            self.client.answer_callback_query(callback_id)
            return

        self.store.set_chat_setting(
            chat_id,
            "selected_brief_address",
            address,
            int(time.time() * 1000),
        )
        sort_mode = self.store.get_chat_setting(
            chat_id,
            "position_sort",
            "value",
        )
        try:
            brief_data = self.monitor.snapshot_data(address)
            self.router._publish_position_brief(
                chat_id,
                address,
                brief_data,
                sort_mode,
                selected_address=address,
                target_message_id=message_id,
            )
        except Exception as exc:
            print(f"[telegram] 切换简报地址失败: {exc}")
            self.client.answer_callback_query(callback_id, "切换地址失败，请重试。")
            return
        self.client.answer_callback_query(callback_id)

    def _handle_stats_address_callback(self, callback_id, chat_id, message_id, data):
        try:
            address = normalize_address(data.split(":", 1)[1])
        except (ValueError, IndexError):
            self.client.answer_callback_query(callback_id)
            return

        self.store.set_chat_setting(
            chat_id,
            "selected_fill_stats_address",
            address,
            int(time.time() * 1000),
        )
        try:
            self.router.refresh_fill_stats(chat_id, address)
        except Exception as exc:
            print(f"[telegram] 切换成交统计地址失败: {exc}")
            self.client.answer_callback_query(callback_id, "切换地址失败，请重试。")
            return
        self.client.answer_callback_query(callback_id)

    def _handle_brief_page_callback(self, callback_id, chat_id, message_id, data):
        try:
            _, address, page_text = data.split(":", 2)
            address = normalize_address(address)
            page = int(page_text)
        except (ValueError, TypeError):
            self.client.answer_callback_query(callback_id)
            return

        self.store.set_chat_setting(
            chat_id,
            f"brief_page:{address}",
            str(page),
            int(time.time() * 1000),
        )
        sort_mode = self.store.get_chat_setting(
            chat_id,
            "position_sort",
            "value",
        )
        try:
            brief_data = self.monitor.snapshot_data(address)
            self.router._publish_position_brief(
                chat_id,
                address,
                brief_data,
                sort_mode,
                target_message_id=message_id,
            )
        except Exception as exc:
            print(f"[telegram] 切换简报页面失败: {exc}")
            self.client.answer_callback_query(callback_id, "切换页面失败，请重试。")
            return
        self.client.answer_callback_query(callback_id)

    def _handle_coin_callback(self, callback_id, chat_id, message_id, data):
        try:
            coins = self._get_coins()
        except Exception as exc:
            self.client.answer_callback_query(callback_id, f"获取币种失败: {exc}")
            return

        selected = self._get_selected_coins(chat_id, coins)
        parts = data.split(":")
        if len(parts) < 2:
            self.client.answer_callback_query(callback_id)
            return

        head = parts[1]
        if head == "back":
            self.client.edit_message_text(
                chat_id,
                message_id,
                "请选择币种分类：",
                reply_markup=coin_category_keyboard(),
            )
            self.client.answer_callback_query(callback_id)
            return

        if head == "cat" and len(parts) >= 3:
            category = parts[2]
            page = 0
        else:
            category = head
            action = parts[2] if len(parts) > 2 else ""

            if action == "t" and len(parts) >= 5:
                page = int(parts[3])
                coin = ":".join(parts[4:])
                if coin in selected:
                    selected.discard(coin)
                else:
                    selected.add(coin)
            elif action == "n" and len(parts) >= 4:
                page = int(parts[3])
            elif action == "a":
                page = 0
                selected.update(self._category_coins(category, coins))
            elif action == "c":
                page = 0
                selected.difference_update(self._category_coins(category, coins))
            else:
                self.client.answer_callback_query(callback_id)
                return

        if category not in {"main", "metal", "other"}:
            self.client.answer_callback_query(callback_id)
            return

        category_coins = self._category_coins(category, coins)
        category_selected = selected & set(category_coins)
        if not category_coins:
            text = f"{self._category_label(category)}：当前没有可用币种。"
        else:
            text = (
                f"{self._category_label(category)}："
                f"已选 {len(category_selected)}/{len(category_coins)}"
            )

        self._set_selected_coins(chat_id, selected)
        try:
            self.client.edit_message_text(
                chat_id,
                message_id,
                text,
                reply_markup=coin_list_keyboard(
                    category_coins,
                    selected,
                    page,
                    category,
                ),
            )
        except Exception as exc:
            print(f"[telegram] 更新币种菜单失败: {exc}")
            self.client.answer_callback_query(callback_id, "更新失败，请重试。")
            return
        self.client.answer_callback_query(callback_id)

    def _dispatch(self, chat_id, command, args):
        if command in {"/start", "/help"}:
            self.client.send_message(chat_id, HELP_TEXT)
        elif command == "/add":
            self._cmd_add(chat_id, args)
        elif command in {"/name", "/alias"}:
            self._cmd_name(chat_id, args)
        elif command == "/remove":
            self._cmd_remove(chat_id, args)
        elif command == "/removeall":
            self._cmd_removeall(chat_id)
        elif command == "/list":
            self._cmd_list(chat_id)
        elif command == "/status":
            self._cmd_status(chat_id, args)
        elif command == "/stats":
            self._cmd_stats(chat_id, args)
        elif command == "/history":
            self._cmd_history(chat_id, args)
        elif command == "/tpsl":
            self._cmd_tpsl(chat_id, args)
        elif command == "/orders":
            self._cmd_orders(chat_id, args)
        elif command == "/recent":
            self._cmd_recent(chat_id, args)
        elif command == "/coins":
            self._cmd_coins(chat_id)
        elif command == "/sort":
            self._cmd_sort(chat_id, args)
        elif command == "/mute":
            self.store.set_chat_setting(
                chat_id,
                "notifications_muted",
                "1",
                int(time.time() * 1000),
            )
            self.client.send_message(chat_id, "已暂停当前聊天的告警。")
        elif command == "/unmute":
            self.store.set_chat_setting(
                chat_id,
                "notifications_muted",
                "0",
                int(time.time() * 1000),
            )
            self.client.send_message(chat_id, "已恢复当前聊天的告警。")
        else:
            self.client.send_message(chat_id, "未知命令，请发送 /help 查看说明。")

    def _cmd_add(self, chat_id, args):
        parts = args.split(maxsplit=1)
        if not parts or not parts[0].strip():
            self.client.send_message(chat_id, "用法: /add 0x地址 [别名]")
            return
        try:
            address = normalize_address(parts[0])
        except ValueError as exc:
            self.client.send_message(chat_id, f"地址无效: {exc}")
            return
        alias = parts[1].strip() if len(parts) > 1 else ""
        self.store.subscribe(chat_id, address, alias=alias, ts=int(time.time() * 1000))
        self.store.set_chat_setting(
            chat_id,
            "selected_brief_address",
            address,
            int(time.time() * 1000),
        )
        self.store.set_chat_setting(
            chat_id,
            "selected_fill_stats_address",
            address,
            int(time.time() * 1000),
        )
        self.monitor.set_addresses(self.store.all_watched_addresses(active_only=False))
        label = f"（{alias}）" if alias else ""
        self.client.send_message(chat_id, f"已添加监控: {address} {label}".strip())

    def _cmd_name(self, chat_id, args):
        parts = args.strip().split(maxsplit=1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            self.client.send_message(chat_id, "用法: /name 命名 0x地址")
            return
        alias = parts[0].strip()
        try:
            address = normalize_address(parts[1].strip())
        except ValueError as exc:
            self.client.send_message(chat_id, f"地址无效: {exc}")
            return

        subscriptions = self.store.get_subscriptions(
            chat_id=chat_id,
            active_only=False,
        )
        if address not in {sub["address"] for sub in subscriptions}:
            self.client.send_message(chat_id, "该地址尚未添加，请先使用 /add。")
            return

        self.store.set_subscription_alias(
            chat_id,
            address,
            alias,
            int(time.time() * 1000),
        )
        self.client.send_message(chat_id, f"已命名: {alias} -> {address}")

    def _resolve_address(self, chat_id, token):
        token = token.strip()
        subscriptions = self.store.get_subscriptions(
            chat_id=chat_id,
            active_only=False,
        )
        for sub in subscriptions:
            if token.lower() == sub["address"].lower():
                return sub["address"]
            if sub["alias"] and token.lower() == sub["alias"].lower():
                return sub["address"]
        try:
            address = normalize_address(token)
        except ValueError:
            return None
        return address if address in {sub["address"] for sub in subscriptions} else None

    def _cmd_remove(self, chat_id, args):
        address_text = args.strip().split()[0] if args.strip() else ""
        if not address_text:
            self.client.send_message(chat_id, "用法: /remove 0x地址")
            return
        try:
            address = normalize_address(address_text)
        except ValueError as exc:
            self.client.send_message(chat_id, f"地址无效: {exc}")
            return
        self.store.unsubscribe(chat_id, address)
        self.monitor.set_addresses(self.store.all_watched_addresses(active_only=False))
        self.client.send_message(chat_id, f"已删除监控: {address}")

    def _cmd_removeall(self, chat_id):
        self.store.clear_subscriptions(chat_id)
        self.monitor.set_addresses(self.store.all_watched_addresses(active_only=False))
        self.client.send_message(chat_id, "已删除当前聊天的全部监控地址。")

    def _cmd_list(self, chat_id):
        subscriptions = self.store.get_subscriptions(chat_id=chat_id, active_only=False)
        if not subscriptions:
            self.client.send_message(chat_id, "当前没有监控地址。用 /add 添加。")
            return
        lines = ["当前监控列表:"]
        for sub in subscriptions:
            alias = sub["alias"]
            label = f"（{alias}）" if alias else ""
            status = "已暂停" if not sub["active"] else "监控中"
            lines.append(f"- {sub['address']} {label} [{status}]")
        self.client.send_message(chat_id, "\n".join(lines))

    def _cmd_status(self, chat_id, args):
        sort_mode = self.store.get_chat_setting(
            chat_id,
            "position_sort",
            "value",
        )
        if args.strip():
            address = self._resolve_address(chat_id, args.strip())
            if not address:
                self.client.send_message(chat_id, "找不到该地址或命名。")
                return
            self._send_status(chat_id, address, sort_mode)
            return

        subscriptions = self.store.get_subscriptions(chat_id=chat_id, active_only=False)
        if not subscriptions:
            self.client.send_message(chat_id, "当前没有监控地址，请用 /add 添加。")
            return
        self._send_status(chat_id, subscriptions[0]["address"], sort_mode)

    def _cmd_stats(self, chat_id, args):
        subscriptions = self.store.get_subscriptions(
            chat_id=chat_id,
            active_only=False,
        )
        if args.strip():
            address = self._resolve_address(chat_id, args.strip())
            if not address:
                self.client.send_message(chat_id, "找不到该地址或命名。")
                return
        else:
            address = self.store.get_chat_setting(
                chat_id,
                "selected_fill_stats_address",
                None,
            )
            if address not in {sub["address"] for sub in subscriptions}:
                address = subscriptions[0]["address"] if subscriptions else None
        if not address:
            self.client.send_message(chat_id, "当前没有监控地址，请用 /add 添加。")
            return

        self.store.set_chat_setting(
            chat_id,
            "selected_fill_stats_address",
            address,
            int(time.time() * 1000),
        )
        try:
            self.router.refresh_fill_stats(chat_id, address, force_new=True)
        except Exception as exc:
            self.client.send_message(
                chat_id,
                f"打开成交统计失败: {exc}",
            )

    def _cmd_history(self, chat_id, args):
        subscriptions = self.store.get_subscriptions(
            chat_id=chat_id,
            active_only=False,
        )
        if args.strip():
            address = self._resolve_address(chat_id, args.strip())
            if not address:
                self.client.send_message(chat_id, "找不到该地址或命名。")
                return
        else:
            address = self.store.get_chat_setting(
                chat_id,
                "selected_brief_address",
                None,
            )
            if address not in {sub["address"] for sub in subscriptions}:
                address = subscriptions[0]["address"] if subscriptions else None
        if not address:
            self.client.send_message(chat_id, "当前没有监控地址，请用 /add 添加。")
            return

        try:
            report = self.monitor.history_report(address)
        except Exception as exc:
            self.client.send_message(
                chat_id,
                f"查询持仓历史失败: {exc}",
            )
            return
        self.client.send_message(chat_id, report, parse_mode="HTML")

    def _cmd_tpsl(self, chat_id, args):
        subscriptions = self.store.get_subscriptions(
            chat_id=chat_id,
            active_only=False,
        )
        if args.strip():
            address = self._resolve_address(chat_id, args.strip())
            if not address:
                self.client.send_message(chat_id, "找不到该地址或命名。")
                return
        else:
            address = self.store.get_chat_setting(
                chat_id,
                "selected_brief_address",
                None,
            )
            if address not in {sub["address"] for sub in subscriptions}:
                address = subscriptions[0]["address"] if subscriptions else None
        if not address:
            self.client.send_message(chat_id, "当前没有监控地址，请用 /add 添加。")
            return
        self._send_tpsl(chat_id, address)

    def _send_tpsl(self, chat_id, address):
        try:
            report = self.monitor.tpsl_report(address)
        except Exception as exc:
            self.client.send_message(
                chat_id,
                f"查询止盈止损失败: {exc}",
            )
            return
        subscriptions = self.store.get_subscriptions(
            chat_id=chat_id,
            active_only=False,
        )
        keyboard = address_selector_rows(subscriptions, address, "ast")
        self.client.send_message(
            chat_id,
            report,
            parse_mode="HTML",
            reply_markup=(
                {"inline_keyboard": keyboard} if keyboard else None
            ),
        )

    def _handle_tpsl_address_callback(
        self,
        callback_id,
        chat_id,
        message_id,
        data,
    ):
        try:
            address = normalize_address(data.split(":", 1)[1])
        except (ValueError, IndexError):
            self.client.answer_callback_query(callback_id)
            return

        try:
            report = self.monitor.tpsl_report(address)
        except Exception as exc:
            print(f"[telegram] 刷新止盈止损失败: {exc}")
            self.client.answer_callback_query(callback_id, "刷新失败，请重试。")
            return
        subscriptions = self.store.get_subscriptions(
            chat_id=chat_id,
            active_only=False,
        )
        keyboard = address_selector_rows(subscriptions, address, "ast")
        self.client.edit_message_text(
            chat_id,
            message_id,
            report,
            reply_markup=(
                {"inline_keyboard": keyboard} if keyboard else None
            ),
            parse_mode="HTML",
        )
        self.client.answer_callback_query(callback_id)

    def _cmd_orders(self, chat_id, args):
        subscriptions = self.store.get_subscriptions(
            chat_id=chat_id,
            active_only=False,
        )
        if args.strip():
            address = self._resolve_address(chat_id, args.strip())
            if not address:
                self.client.send_message(chat_id, "找不到该地址或命名。")
                return
            self._show_orders_coin_menu(chat_id, address)
            return
        if not subscriptions:
            self.client.send_message(chat_id, "当前没有监控地址，请用 /add 添加。")
            return
        self._show_orders_account_menu(chat_id)

    def _show_orders_account_menu(self, chat_id, target_message_id=None):
        subscriptions = self.store.get_subscriptions(
            chat_id=chat_id,
            active_only=False,
        )
        if not subscriptions:
            self.client.send_message(chat_id, "当前没有监控地址，请用 /add 添加。")
            return
        keyboard = address_selector_rows(subscriptions, None, "aso")
        text = (
            "📋 选择要查看挂单的账户：\n"
            "（也可以直接发 /orders 命名 跳过这一步）"
        )
        if target_message_id is not None:
            self.client.edit_message_text(
                chat_id,
                target_message_id,
                text,
                reply_markup={"inline_keyboard": keyboard},
            )
        else:
            self.client.send_message(
                chat_id,
                text,
                reply_markup={"inline_keyboard": keyboard},
            )

    def _show_orders_coin_menu(
        self,
        chat_id,
        address,
        target_message_id=None,
        callback_id=None,
    ):
        try:
            summaries = self.monitor.open_orders_coin_summaries(address)
        except Exception as exc:
            print(f"[telegram] 加载挂单币种菜单失败: {exc}")
            if callback_id:
                self.client.answer_callback_query(callback_id, "刷新失败，请重试。")
            else:
                self.client.send_message(
                    chat_id,
                    f"查询普通挂单失败: {exc}",
                )
            return False

        self.store.set_chat_setting(
            chat_id,
            "selected_orders_address",
            address,
            int(time.time() * 1000),
        )
        total_orders = sum(item["count"] for item in summaries)
        lines = [
            f"<b>📋 选择标的 · {html.escape(short_addr(address))}</b>",
        ]
        if summaries:
            lines.append(f"共 {total_orders} 笔挂单 · {len(summaries)} 个标的")
            if len(summaries) > 48:
                lines.append("（仅显示金额最大的前 48 个标的）")
        else:
            lines.append("当前没有普通挂单")
        text = "\n".join(lines)

        if not summaries:
            keyboard = (
                [[{"text": "返回账户", "callback_data": f"oba:{address}"}]]
                if target_message_id is not None
                else []
            )
        else:
            shown = summaries[:48]
            keyboard = []
            row = []
            for item in shown:
                label = (
                    f"{item['label']} · {item['count']}笔 · "
                    f"≈{fmt_usd_cn(item['value'])}"
                )
                row.append(
                    {
                        "text": label,
                        "callback_data": f"osc:{address}:{item['coin']}",
                    }
                )
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            bottom = [
                {"text": "查看全部", "callback_data": f"osa:{address}"},
            ]
            if target_message_id is not None:
                bottom.append(
                    {"text": "返回账户", "callback_data": f"oba:{address}"}
                )
            keyboard.append(bottom)

        if target_message_id is not None:
            self.client.edit_message_text(
                chat_id,
                target_message_id,
                text,
                reply_markup={"inline_keyboard": keyboard},
                parse_mode="HTML",
            )
        else:
            self.client.send_message(
                chat_id,
                text,
                reply_markup={"inline_keyboard": keyboard} if keyboard else None,
                parse_mode="HTML",
            )
        return True

    def _show_orders_report(
        self,
        chat_id,
        address,
        coin,
        target_message_id=None,
        callback_id=None,
    ):
        level = self.store.get_chat_setting(
            chat_id,
            "orders_merge_level",
            "auto",
        )
        if level not in {"fine", "auto", "coarse"}:
            level = "auto"
        try:
            report = self.monitor.open_orders_report(
                address,
                coin=coin,
                level=level,
            )
        except Exception as exc:
            print(f"[telegram] 加载挂单密集区间失败: {exc}")
            if callback_id:
                self.client.answer_callback_query(callback_id, "刷新失败，请重试。")
            else:
                self.client.send_message(
                    chat_id,
                    f"查询普通挂单失败: {exc}",
                )
            return False

        self.store.set_chat_setting(
            chat_id,
            "selected_orders_address",
            address,
            int(time.time() * 1000),
        )
        coin_key = "all" if coin is None else coin
        level_buttons = []
        for value, label in (
            ("fine", "🔍 细"),
            ("auto", "自动"),
            ("coarse", "📦 粗"),
        ):
            text = f"✅ {label}" if value == level else label
            level_buttons.append(
                {
                    "text": text,
                    "callback_data": f"om:{value}:{address}:{coin_key}",
                }
            )
        keyboard = [
            level_buttons,
            [{"text": "◀️ 返回标的", "callback_data": f"obc:{address}"}],
            [{"text": "返回账户", "callback_data": f"oba:{address}"}],
        ]
        if target_message_id is not None:
            self.client.edit_message_text(
                chat_id,
                target_message_id,
                report,
                reply_markup={"inline_keyboard": keyboard},
                parse_mode="HTML",
            )
        else:
            self.client.send_message(
                chat_id,
                report,
                reply_markup={"inline_keyboard": keyboard},
                parse_mode="HTML",
            )
        return True

    def _handle_orders_level_callback(
        self,
        callback_id,
        chat_id,
        message_id,
        data,
    ):
        try:
            _, level, rest = data.split(":", 2)
            if level not in {"fine", "auto", "coarse"}:
                raise ValueError(level)
            address = normalize_address(rest[:42])
            coin = rest[43:]
        except (ValueError, IndexError):
            self.client.answer_callback_query(callback_id)
            return
        self.store.set_chat_setting(
            chat_id,
            "orders_merge_level",
            level,
            int(time.time() * 1000),
        )
        coin_arg = None if coin == "all" else coin
        ok = self._show_orders_report(
            chat_id,
            address,
            coin_arg,
            target_message_id=message_id,
            callback_id=callback_id,
        )
        if ok:
            labels = {"fine": "细粒度", "auto": "自动", "coarse": "粗粒度"}
            self.client.answer_callback_query(
                callback_id,
                f"已切换为{labels[level]}。",
            )

    def _handle_orders_address_callback(
        self,
        callback_id,
        chat_id,
        message_id,
        data,
    ):
        try:
            address = normalize_address(data.split(":", 1)[1])
        except (ValueError, IndexError):
            self.client.answer_callback_query(callback_id)
            return
        ok = self._show_orders_coin_menu(
            chat_id,
            address,
            target_message_id=message_id,
            callback_id=callback_id,
        )
        if ok:
            self.client.answer_callback_query(callback_id)

    def _handle_orders_coin_callback(
        self,
        callback_id,
        chat_id,
        message_id,
        data,
    ):
        try:
            parts = data.rsplit(":", 1)
            address = normalize_address(parts[0].split(":", 1)[1])
            coin = parts[1]
        except (ValueError, IndexError):
            self.client.answer_callback_query(callback_id)
            return
        ok = self._show_orders_report(
            chat_id,
            address,
            coin,
            target_message_id=message_id,
            callback_id=callback_id,
        )
        if ok:
            self.client.answer_callback_query(callback_id)

    def _handle_orders_all_callback(
        self,
        callback_id,
        chat_id,
        message_id,
        data,
    ):
        try:
            address = normalize_address(data.split(":", 1)[1])
        except (ValueError, IndexError):
            self.client.answer_callback_query(callback_id)
            return
        ok = self._show_orders_report(
            chat_id,
            address,
            None,
            target_message_id=message_id,
            callback_id=callback_id,
        )
        if ok:
            self.client.answer_callback_query(callback_id)

    def _handle_orders_back_coins_callback(
        self,
        callback_id,
        chat_id,
        message_id,
        data,
    ):
        try:
            address = normalize_address(data.split(":", 1)[1])
        except (ValueError, IndexError):
            self.client.answer_callback_query(callback_id)
            return
        ok = self._show_orders_coin_menu(
            chat_id,
            address,
            target_message_id=message_id,
            callback_id=callback_id,
        )
        if ok:
            self.client.answer_callback_query(callback_id)

    def _handle_orders_back_accounts_callback(
        self,
        callback_id,
        chat_id,
        message_id,
        data,
    ):
        try:
            address = normalize_address(data.split(":", 1)[1])
        except (ValueError, IndexError):
            self.client.answer_callback_query(callback_id)
            return
        self._show_orders_account_menu(chat_id, target_message_id=message_id)
        self.client.answer_callback_query(callback_id)

    def _send_status(self, chat_id, address, sort_mode="value"):
        try:
            data = self.monitor.snapshot_data(address)
            self.store.set_chat_setting(
                chat_id,
                f"brief_page:{address}",
                "0",
                int(time.time() * 1000),
            )
            self.store.set_chat_setting(
                chat_id,
                "selected_brief_address",
                address,
                int(time.time() * 1000),
            )
            self.router._publish_position_brief(
                chat_id,
                address,
                data,
                sort_mode,
                force_new=True,
                selected_address=address,
            )
        except Exception as exc:
            self.client.send_message(
                chat_id,
                f"查询 {short_addr(address)} 失败: {exc}",
            )

    def _cmd_sort(self, chat_id, args):
        value = args.strip().lower()
        if value not in {"value", "time"}:
            self.client.send_message(
                chat_id,
                "用法: /sort value 或 /sort time",
            )
            return
        self.store.set_chat_setting(
            chat_id,
            "position_sort",
            value,
            int(time.time() * 1000),
        )
        label = "开仓时间" if value == "time" else "仓位价值"
        self.client.send_message(chat_id, f"已切换持仓简报排序为：{label}。")

    def _cmd_coins(self, chat_id):
        self.client.send_message(
            chat_id,
            "请选择币种分类：",
            reply_markup=coin_category_keyboard(),
        )

    def _get_coins(self):
        now = time.time()
        if self._universe_cache and now - self._universe_cache_at < 3600:
            return self._universe_cache
        meta = self.monitor.api.meta()
        coins = sorted(
            str(item.get("name", ""))
            for item in (meta or {}).get("universe", [])
            if item.get("name")
        )
        if not coins:
            raise RuntimeError("Hyperliquid meta 返回为空")
        self._universe_cache = coins
        self._universe_cache_at = now
        return coins

    def _get_selected_coins(self, chat_id, coins):
        raw = self.store.get_chat_setting(chat_id, "notify_coins", None)
        if raw is None:
            return set(coins)
        try:
            selected = set(json.loads(raw))
        except (TypeError, ValueError):
            return set(coins)
        return {coin for coin in selected if coin in coins}

    def _set_selected_coins(self, chat_id, selected):
        self.store.set_chat_setting(
            chat_id,
            "notify_coins",
            json.dumps(sorted(selected), ensure_ascii=False),
            int(time.time() * 1000),
        )

    @staticmethod
    def _coins_text(coins, selected):
        if not coins:
            return "币种列表为空。"
        return f"选择要接收交易通知的币种（已选 {len(selected)}/{len(coins)}）"

    def _category_coins(self, category, coins):
        if category == "main":
            return [coin for coin in MAIN_COINS if coin in coins]
        if category == "metal":
            return [coin for coin in PRECIOUS_METAL_COINS if coin in coins]
        known = set(MAIN_COINS) | set(PRECIOUS_METAL_COINS)
        return [coin for coin in coins if coin not in known]

    @staticmethod
    def _category_label(category):
        return {
            "main": "主流币种",
            "metal": "贵金属",
            "other": "其他币种",
        }.get(category, "币种")

    def _cmd_recent(self, chat_id, args):
        try:
            limit = int(args.strip() or 10)
        except ValueError:
            limit = 10
        limit = max(1, min(limit, 20))

        subscriptions = self.store.get_subscriptions(chat_id=chat_id, active_only=False)
        watched = {sub["address"] for sub in subscriptions}
        if not watched:
            self.client.send_message(chat_id, "当前没有监控地址，请用 /add 添加。")
            return

        events = [
            event
            for event in self.store.recent_events(limit=limit * 5)
            if event["address"] in watched
        ][:limit]
        if not events:
            self.client.send_message(chat_id, "暂无可显示的事件。")
            return

        lines = ["最近事件:"]
        for event in events:
            lines.append(
                f"- [{fmt_time(event['time'])}] "
                f"{short_addr(event['address'])} {event['text']}"
            )
        self.client.send_message(chat_id, "\n".join(lines))
