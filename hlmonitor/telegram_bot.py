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
from .format import (
    fmt_dir,
    fmt_qty,
    fmt_side,
    fmt_szi,
    fmt_time,
    fmt_time_min,
    fmt_usd_cn,
    short_addr,
)
from .hunter import attach_charts, format_account_card_html, scan
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
/hunt [数量] - 扫描 Hyperliquid 大户：按体量粗筛、精算胜率并收集
/huntlist - 查看已收集的大户账户（可一键加入监控）
/coins - 选择要接收交易通知的币种
/mute - 暂停当前聊天的告警
/unmute - 恢复当前聊天的告警
/help - 显示本帮助

告警会自动发送到添加地址时所在的聊天。
持仓简报下方有按钮，可直接切换按仓位价值或按开仓时间排序。
成交通知会自动汇总为多档周期（5分钟/15分钟/1小时/4小时/1天/3天/1周），并在同一条实时消息中刷新。"""


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


FILL_WINDOWS = (
    (5, "5分钟"),
    (15, "15分钟"),
    (60, "1小时"),
    (240, "4小时"),
    (1440, "1天"),
    (4320, "3天"),
    (10080, "1周"),
)
FILL_WINDOW_LABELS = {minutes: label for minutes, label in FILL_WINDOWS}

FILL_STATS_VIEWS = (
    ("summary", "汇总"),
    ("timeline", "流水"),
    ("interval", "区间"),
)
FILL_STATS_VIEW_LABELS = {key: label for key, label in FILL_STATS_VIEWS}


def fill_stats_keyboard(
    address,
    window_min=5,
    subscriptions=None,
    selected_address=None,
    view="summary",
    page=0,
    page_count=1,
):
    rows = []
    if subscriptions:
        rows.extend(
            address_selector_rows(subscriptions, selected_address, "asf")
        )
    buttons = []
    for window, label in FILL_WINDOWS:
        text = f"✅ {label}" if window == window_min else label
        buttons.append(
            {
                "text": text,
                "callback_data": f"fs:{address}:{window}",
            }
        )
        if len(buttons) == 3:
            rows.append(buttons)
            buttons = []
    if buttons:
        rows.append(buttons)
    view_buttons = []
    for key, label in FILL_STATS_VIEWS:
        text = f"✅ {label}" if key == view else label
        view_buttons.append(
            {
                "text": text,
                "callback_data": f"fv:{address}:{key}",
            }
        )
    rows.append(view_buttons)
    if page_count > 1:
        nav = []
        if page > 0:
            nav.append(
                {
                    "text": "◀️ 上一页",
                    "callback_data": f"fp:{address}:{view}:{page - 1}",
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
                    "callback_data": f"fp:{address}:{view}:{page + 1}",
                }
            )
        rows.append(nav)
    return {"inline_keyboard": rows}


def format_fill_stats_html(address, fills, window_min=5, now=None, page=0, page_size=10):
    now = now or int(time.time() * 1000)
    cutoff = now - window_min * 60_000
    recent = [fill for fill in fills if int(fill.get("time") or 0) >= cutoff]

    lines = [
        f"<b>📈 成交统计 · {html.escape(short_addr(address))}</b>",
        f"窗口: {FILL_WINDOW_LABELS.get(window_min, str(window_min) + '分钟')} | 更新时间: {html.escape(fmt_time_min(now))}",
    ]
    if not recent:
        lines.append("")
        lines.append("当前窗口暂无成交")
        return "\n".join(lines), 1

    grouped = {}
    for fill in recent:
        coin = fill.get("coin", "?")
        size = abs(_as_float(fill.get("sz")))
        price = _as_float(fill.get("px"))
        bucket = (
            "close"
            if str(fill.get("dir") or "").lower().startswith("close")
            else "open"
        )
        item = grouped.setdefault(
            coin,
            {
                "count": 0,
                "notional": 0.0,
                "buy_notional": 0.0,
                "sell_notional": 0.0,
                "open_count": 0,
                "open_buy_size": 0.0,
                "open_buy_notional": 0.0,
                "open_sell_size": 0.0,
                "open_sell_notional": 0.0,
                "close_count": 0,
                "close_buy_size": 0.0,
                "close_buy_notional": 0.0,
                "close_sell_size": 0.0,
                "close_sell_notional": 0.0,
                "last_time": 0,
            },
        )
        item["count"] += 1
        item[f"{bucket}_count"] += 1
        value = size * price
        item["notional"] += value
        if fill.get("side") == "B":
            item["buy_notional"] += value
            item[f"{bucket}_buy_size"] += size
            item[f"{bucket}_buy_notional"] += value
        else:
            item["sell_notional"] += value
            item[f"{bucket}_sell_size"] += size
            item[f"{bucket}_sell_notional"] += value
        item["last_time"] = max(item["last_time"], int(fill.get("time") or 0))

    ordered = sorted(
        grouped.items(),
        key=lambda item: item[1]["notional"],
        reverse=True,
    )
    total_pages = max(1, math.ceil(len(ordered) / page_size))
    page = max(0, min(page, total_pages - 1))
    page_coins = ordered[page * page_size : (page + 1) * page_size]

    total_notional = sum(item["notional"] for _, item in ordered)
    lines.append(f"总成交额: {html.escape(fmt_usd_cn(total_notional))}")

    for coin, stat in page_coins:
        net = stat["buy_notional"] - stat["sell_notional"]
        if net > 1e-9:
            direction = "净多"
        elif net < -1e-9:
            direction = "净空"
        else:
            direction = "均衡"
        body_lines = []
        for label, count, buy_notional, buy_size, sell_notional, sell_size in (
            ("开仓", stat["open_count"], stat["open_buy_notional"], stat["open_buy_size"], stat["open_sell_notional"], stat["open_sell_size"]),
            ("平仓", stat["close_count"], stat["close_buy_notional"], stat["close_buy_size"], stat["close_sell_notional"], stat["close_sell_size"]),
        ):
            if count <= 0:
                continue
            body_lines.append(f"{label} | {count}笔")
            if buy_notional > 1e-9:
                body_lines.append(f"买入 {fmt_usd_cn(buy_notional)} / {fmt_szi(buy_size)}")
            if sell_notional > 1e-9:
                body_lines.append(f"卖出 {fmt_usd_cn(sell_notional)} / {fmt_szi(sell_size)}")
        body_lines.append(
            f"成交额: {fmt_usd_cn(stat['notional'])} · 最近: {fmt_time_min(stat['last_time'])}"
        )
        body = "\n".join(html.escape(line) for line in body_lines)
        lines.append("")
        lines.append(
            f"<b>{html.escape(coin)} · {direction}</b>\n"
            f"<blockquote expandable>{body}</blockquote>"
        )
    return "\n".join(lines), total_pages


def format_fill_timeline_html(address, fills, window_min=5, now=None, page=0, page_size=20):
    now = now or int(time.time() * 1000)
    cutoff = now - window_min * 60_000
    recent = [fill for fill in fills if int(fill.get("time") or 0) >= cutoff]

    lines = [
        f"<b>📈 成交流水 · {html.escape(short_addr(address))}</b>",
        f"窗口: {FILL_WINDOW_LABELS.get(window_min, str(window_min) + '分钟')} | 共 {len(recent)} 笔 | 更新时间: {html.escape(fmt_time_min(now))}",
    ]
    if not recent:
        lines.append("")
        lines.append("当前窗口暂无成交")
        return "\n".join(lines), 1

    total_pages = max(1, math.ceil(len(recent) / page_size))
    page = max(0, min(page, total_pages - 1))
    ordered = sorted(
        recent,
        key=lambda fill: int(fill.get("time") or 0),
        reverse=True,
    )
    rows = []
    for fill in ordered[page * page_size : (page + 1) * page_size]:
        coin = str(fill.get("coin") or "?")
        size = abs(_as_float(fill.get("sz")))
        price = _as_float(fill.get("px"))
        label = fmt_dir(fill.get("dir")) or fmt_side(fill.get("side"))
        rows.append(
            f"{fmt_time_min(fill.get('time'))} {coin} {label} "
            f"{fmt_szi(size)} @ {fmt_qty(price)} ≈{fmt_usd_cn(size * price)}"
        )
    lines.append("")
    lines.append(
        "<blockquote expandable>"
        + "\n".join(html.escape(row) for row in rows)
        + "</blockquote>"
    )
    return "\n".join(lines), total_pages


def _cluster_fills_by_price(fills, max_gap_pct=0.2):
    """把同币种、同方向、价格相近的成交合并成密集区间。"""
    groups = {}
    for fill in fills:
        coin = str(fill.get("coin") or "?")
        side = str(fill.get("side") or "").upper()
        px = _as_float(fill.get("px"))
        sz = abs(_as_float(fill.get("sz")))
        if side not in {"B", "A"} or px <= 0 or sz <= 0:
            continue
        groups.setdefault((coin, side), []).append(fill)

    clusters = []
    for (coin, side), group in groups.items():
        group = sorted(group, key=lambda f: _as_float(f.get("px")))
        current = []
        for fill in group:
            px = _as_float(fill.get("px"))
            if current:
                last_px = _as_float(current[-1].get("px"))
                first_px = _as_float(current[0].get("px"))
                gap_pct = (px - last_px) / last_px * 100 if last_px else 0
                width_pct = (px - first_px) / first_px * 100 if first_px else 0
                if gap_pct > max_gap_pct or width_pct > max_gap_pct * 3:
                    clusters.append(current)
                    current = []
            current.append(fill)
        if current:
            clusters.append(current)
    return clusters


def _cluster_interval_stats(cluster):
    sizes = [abs(_as_float(f.get("sz"))) for f in cluster]
    pxs = [_as_float(f.get("px")) for f in cluster]
    total_sz = sum(sizes)
    total_value = sum(px * size for px, size in zip(pxs, sizes))
    avg_px = total_value / total_sz if total_sz > 0 else (min(pxs) + max(pxs)) / 2
    dir_counts = {}
    for f in cluster:
        d = fmt_dir(f.get("dir"))
        if d:
            dir_counts[d] = dir_counts.get(d, 0) + 1
    times = sorted(int(f.get("time") or 0) for f in cluster)
    return {
        "side": "买入" if str(cluster[0].get("side", "")).upper() == "B" else "卖出",
        "count": len(cluster),
        "min_px": min(pxs),
        "max_px": max(pxs),
        "avg_px": avg_px,
        "total_sz": total_sz,
        "total_value": total_value,
        "dir_counts": dir_counts,
        "first_time": times[0],
        "last_time": times[-1],
    }


def format_fill_intervals_html(
    address,
    fills,
    window_min=5,
    now=None,
    page=0,
    max_coins=10,
    max_clusters=6,
    max_page_len=3400,
):
    now = now or int(time.time() * 1000)
    cutoff = now - window_min * 60_000
    recent = [fill for fill in fills if int(fill.get("time") or 0) >= cutoff]

    lines = [
        f"<b>📈 成交区间 · {html.escape(short_addr(address))}</b>",
        f"窗口: {FILL_WINDOW_LABELS.get(window_min, str(window_min) + '分钟')} | 共 {len(recent)} 笔 | 更新时间: {html.escape(fmt_time_min(now))}",
    ]
    if not recent:
        lines.append("")
        lines.append("当前窗口暂无成交")
        return "\n".join(lines), 1

    total_notional = sum(
        abs(_as_float(f.get("sz"))) * _as_float(f.get("px")) for f in recent
    )
    lines.append(f"总成交额: {html.escape(fmt_usd_cn(total_notional))}")

    coin_notional = {}
    for fill in recent:
        coin = str(fill.get("coin") or "?")
        coin_notional[coin] = coin_notional.get(coin, 0.0) + abs(
            _as_float(fill.get("sz"))
        ) * _as_float(fill.get("px"))
    ordered_coins = sorted(
        coin_notional.items(),
        key=lambda kv: kv[1],
        reverse=True,
    )[:max_coins]

    blocks = []
    for coin, _notional in ordered_coins:
        coin_fills = [f for f in recent if str(f.get("coin") or "?") == coin]
        clusters = _cluster_fills_by_price(coin_fills)
        clusters.sort(
            key=lambda c: max(int(f.get("time") or 0) for f in c),
            reverse=True,
        )
        side_groups = []
        side_index = {}
        for cluster in clusters[:max_clusters]:
            side = str(cluster[0].get("side") or "").upper()
            if side not in side_index:
                side_index[side] = len(side_groups)
                side_groups.append((side, []))
            side_groups[side_index[side]][1].append(cluster)
        tables = []
        used = 0
        for _side, cluster_list in side_groups:
            for cluster in cluster_list:
                stat = _cluster_interval_stats(cluster)
                dir_text = " · ".join(
                    f"{k}×{v}" for k, v in sorted(stat["dir_counts"].items())
                )
                head = f"{stat['side']} · {stat['count']}笔"
                if dir_text:
                    head += f"（{dir_text}）"
                single = stat["min_px"] == stat["max_px"]
                range_label = "价格" if single else "区间"
                range_value = (
                    fmt_qty(stat["min_px"])
                    if single
                    else f"{fmt_qty(stat['min_px'])} – {fmt_qty(stat['max_px'])}"
                )
                rows = (
                    f"<tr><td>方向</td><td>{html.escape(head)}</td>"
                    f"<td>{range_label}</td><td>{html.escape(range_value)}</td></tr>"
                    f"<tr><td>均价</td><td>{fmt_qty(stat['avg_px'])}</td>"
                    f"<td>数量</td><td>{html.escape(fmt_szi(stat['total_sz']))}</td></tr>"
                    f"<tr><td>金额</td><td>{html.escape(fmt_usd_cn(stat['total_value']))}</td>"
                    f"<td>时间</td><td>{html.escape(f'{fmt_time_min(stat["first_time"])} – {fmt_time_min(stat["last_time"])}')}</td></tr>"
                )
                table = f"<table bordered compact>{rows}</table>"
                if used + len(table) > max_page_len - 300:
                    tables.append("…… 其余区间省略")
                    break
                tables.append(table)
                used += len(table)
            if tables and tables[-1].startswith("…"):
                break
        if tables:
            blocks.append((coin, tables))

    pages = []
    current = []
    current_len = len("\n".join(lines))
    for coin, side_blocks in blocks:
        block_len = (
            len(f"<b>{coin}</b>")
            + sum(len(b) for b in side_blocks)
            + len(side_blocks) * 2
            + 3
        )
        if current and current_len + block_len + 2 > max_page_len:
            pages.append(current)
            current = []
            current_len = len("\n".join(lines))
        current.append((coin, side_blocks))
        current_len += block_len + 2
    if current:
        pages.append(current)

    total_pages = max(1, len(pages))
    page = max(0, min(page, total_pages - 1))
    head_text = "\n".join(lines)
    chunks = []
    for coin, side_blocks in pages[page]:
        if side_blocks:
            chunks.append(
                f"<b>{html.escape(coin)}</b>{''.join(side_blocks)}"
            )
        else:
            chunks.append(f"<b>{html.escape(coin)}</b>")
    if not chunks:
        return head_text, total_pages
    return head_text + "\n\n" + "".join(chunks), total_pages



def _rich_html(text):
    """把旧 HTML 消息中的换行转成 <br>（保留 <pre> 内换行），适配富文本渲染。"""
    parts = []
    rest = text
    while True:
        start = rest.find("<pre>")
        if start < 0:
            parts.append(rest.replace("\n", "<br>"))
            break
        end = rest.find("</pre>", start)
        if end < 0:
            parts.append(rest[:start].replace("\n", "<br>"))
            parts.append(rest[start:])
            break
        parts.append(rest[:start].replace("\n", "<br>"))
        parts.append(rest[start:end + len("</pre>")])
        rest = rest[end + len("</pre>"):]
    return "".join(parts)


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
        if parse_mode == "HTML":
            try:
                rich = {
                    "chat_id": chat_id,
                    "rich_message": {"html": _rich_html(text)},
                    "disable_web_page_preview": True,
                }
                if reply_markup is not None:
                    rich["reply_markup"] = reply_markup
                return self._call("sendRichMessage", rich)
            except Exception as exc:
                print(f"[telegram] sendRichMessage 失败，回退旧格式: {exc}")
        return self._call("sendMessage", payload)

    def send_typing(self, chat_id):
        return self._call("sendChatAction", {"chat_id": chat_id, "action": "typing"})

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
        if parse_mode == "HTML":
            try:
                rich = {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "rich_message": {"html": _rich_html(text)},
                }
                if reply_markup is not None:
                    rich["reply_markup"] = reply_markup
                return self._call("editMessageText", rich)
            except Exception as exc:
                print(f"[telegram] editMessageText(rich) 失败，回退旧格式: {exc}")
        return self._call("editMessageText", payload)

    def delete_message(self, chat_id, message_id):
        return self._call(
            "deleteMessage",
            {"chat_id": chat_id, "message_id": message_id},
        )

    def answer_callback_query(self, callback_query_id, text=None):
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return self._call("answerCallbackQuery", payload)


class TelegramRouter:
    """Route monitor events to chats subscribed to the affected address."""

    def __init__(self, client: TelegramClient, store: EventStore, fallback_chat_id=None, api=None):
        self.client = client
        self.store = store
        self.fallback_chat_id = str(fallback_chat_id) if fallback_chat_id else None
        self.api = api
        self._fill_buffers = {}
        self._fill_lock = threading.RLock()
        self._fill_dirty = set()
        self._fill_timer = None
        self._api_fill_cache = {}

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
                self.store.set_chat_setting(
                    chat_id,
                    key,
                    str(target_message_id),
                    int(time.time() * 1000),
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
                    "dir": fill.get("dir"),
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
            self._fill_timer = None

        for key in dirty:
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
                    None,
                    selected_address=selected_address,
                )
            except Exception as exc:
                print(f"[telegram] 刷新成交统计失败 ({chat_id}): {exc}")

    def refresh_fill_stats(self, chat_id, address, force_new=False, target_message_id=None):
        self._publish_fill_stats(
            chat_id,
            address,
            None,
            selected_address=address,
            force_new=force_new,
            target_message_id=target_message_id,
        )

    def _stats_fills(self, chat_id, address, window_min):
        """合并实时缓冲与（长期窗口）API 历史成交，按时间倒序去重。"""
        with self._fill_lock:
            merged = list(self._fill_buffers.get((chat_id, address), []))
        if self.api is not None and window_min > 15:
            merged.extend(self._fetch_api_fills(address, window_min))
        seen = set()
        result = []
        for fill in merged:
            try:
                key = (
                    int(fill.get("time") or 0),
                    str(fill.get("coin") or "?"),
                    str(fill.get("side") or "").upper(),
                    str(fill.get("dir") or ""),
                    round(float(fill.get("sz") or 0), 8),
                    round(float(fill.get("px") or 0), 8),
                )
            except (TypeError, ValueError):
                continue
            if key in seen:
                continue
            seen.add(key)
            result.append(fill)
        result.sort(key=lambda item: int(item.get("time") or 0), reverse=True)
        return result[:5000]

    def _fetch_api_fills(self, address, window_min):
        """从 Hyperliquid API 拉取指定窗口的历史成交（60 秒缓存）。"""
        cache_key = (address, window_min)
        now = time.time()
        with self._fill_lock:
            cached_at, cached = self._api_fill_cache.get(cache_key, (0.0, []))
            if now - cached_at < 60:
                return cached
        start_ms = int(time.time() * 1000) - window_min * 60_000
        try:
            raw = self.api.user_fills_by_time(address, start_ms) or []
        except Exception as exc:
            print(f"[telegram] 拉取历史成交失败 ({short_addr(address)}): {exc}")
            return []
        normalized = []
        for fill in raw:
            side = str(fill.get("side") or "").upper()
            if side not in {"B", "A"}:
                continue
            try:
                timestamp = int(fill.get("time") or 0)
                sz = float(fill.get("sz") or 0)
                px = float(fill.get("px") or 0)
            except (TypeError, ValueError):
                continue
            if not timestamp:
                continue
            normalized.append(
                {
                    "time": timestamp,
                    "coin": str(fill.get("coin") or "?"),
                    "side": side,
                    "dir": fill.get("dir"),
                    "sz": str(sz),
                    "px": str(px),
                }
            )
        with self._fill_lock:
            self._api_fill_cache[cache_key] = (time.time(), normalized)
        return normalized

    def _publish_fill_stats(
        self,
        chat_id,
        address,
        fills=None,
        selected_address=None,
        force_new=False,
        target_message_id=None,
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
        if window_min not in FILL_WINDOW_LABELS:
            window_min = 5

        view = str(
            self.store.get_chat_setting(
                chat_id,
                f"fill_stats_view:{address}",
                "summary",
            )
        )
        if view not in FILL_STATS_VIEW_LABELS:
            view = "summary"

        try:
            page = int(
                self.store.get_chat_setting(
                    chat_id,
                    f"fill_stats_page:{address}:{view}",
                    "0",
                )
            )
        except (TypeError, ValueError):
            page = 0
        page = max(0, page)

        if fills is None:
            fills = self._stats_fills(chat_id, address, window_min)

        if view == "timeline":
            text, page_count = format_fill_timeline_html(
                address, fills, window_min, page=page
            )
        elif view == "interval":
            text, page_count = format_fill_intervals_html(
                address, fills, window_min, page=page
            )
        else:
            text, page_count = format_fill_stats_html(
                address, fills, window_min, page=page
            )
        if page >= page_count:
            page = page_count - 1
            if view == "timeline":
                text, page_count = format_fill_timeline_html(
                    address, fills, window_min, page=page
                )
            elif view == "interval":
                text, page_count = format_fill_intervals_html(
                    address, fills, window_min, page=page
                )
            else:
                text, page_count = format_fill_stats_html(
                    address, fills, window_min, page=page
                )
        reply_markup = fill_stats_keyboard(
            address,
            window_min,
            subscriptions=self.store.get_subscriptions(
                chat_id=chat_id,
                active_only=False,
            ),
            selected_address=selected_address or address,
            view=view,
            page=page,
            page_count=page_count,
        )
        key = "live_fill_stats_panel"
        message_id = self.store.get_chat_setting(chat_id, key, None)
        if force_new:
            message_id = None
        if target_message_id is not None:
            message_id = target_message_id
        if message_id is not None:
            try:
                self.client.edit_message_text(
                    chat_id,
                    int(message_id),
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
                self.store.set_chat_setting(
                    chat_id,
                    key,
                    str(message_id),
                    int(time.time() * 1000),
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
        self.monitor = monitor or AddressMonitor(
            config,
            store=self.store,
            notifier=None,
        )
        self.router = TelegramRouter(
            self.client,
            self.store,
            fallback_chat_id=self.fallback_chat_id,
            api=self.monitor.api,
        )
        if monitor is None:
            self.monitor.notifier = self.router
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
        pending_address = self.store.get_chat_setting(
            chat_id,
            f"pending_alias:{chat_id}",
            None,
        )
        if pending_address:
            first_word = (
                text.split(maxsplit=1)[0].split("@", 1)[0].lower()
                if text
                else ""
            )
            if first_word == "/skip":
                self._finish_alias(chat_id, pending_address, None)
            elif text:
                self._finish_alias(chat_id, pending_address, text)
            return
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

        if data.startswith("hp:"):
            self._handle_hunt_page_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("hs:"):
            self._handle_hunt_sub_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("ht:"):
            self._handle_hunt_style_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
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

        if data.startswith("fp:"):
            self._handle_fill_page_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return

        if data.startswith("fv:"):
            self._handle_fill_view_callback(
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
        if window_min not in FILL_WINDOW_LABELS:
            self.client.answer_callback_query(callback_id)
            return

        now_ms = int(time.time() * 1000)
        self.store.set_chat_setting(
            chat_id,
            f"fill_stats_window:{address}",
            str(window_min),
            now_ms,
        )
        view = str(
            self.store.get_chat_setting(
                chat_id,
                f"fill_stats_view:{address}",
                "summary",
            )
        )
        if view not in FILL_STATS_VIEW_LABELS:
            view = "summary"
        self.store.set_chat_setting(
            chat_id,
            f"fill_stats_page:{address}:{view}",
            "0",
            now_ms,
        )
        try:
            self.router.refresh_fill_stats(chat_id, address)
        except Exception as exc:
            print(f"[telegram] 切换成交统计窗口失败: {exc}")
            self.client.answer_callback_query(callback_id, "切换失败，请重试。")
            return
        self.client.answer_callback_query(callback_id, f"已切换为{FILL_WINDOW_LABELS[window_min]}窗口。")

    def _handle_fill_page_callback(self, callback_id, chat_id, message_id, data):
        try:
            _, address, view, page_text = data.split(":", 3)
            address = normalize_address(address)
            page = int(page_text)
        except (ValueError, TypeError):
            self.client.answer_callback_query(callback_id)
            return
        if view not in FILL_STATS_VIEW_LABELS or page < 0:
            self.client.answer_callback_query(callback_id)
            return
        self.store.set_chat_setting(
            chat_id,
            f"fill_stats_page:{address}:{view}",
            str(page),
            int(time.time() * 1000),
        )
        try:
            self.router.refresh_fill_stats(chat_id, address)
        except Exception as exc:
            print(f"[telegram] 切换成交统计翻页失败: {exc}")
            self.client.answer_callback_query(callback_id, "切换失败，请重试。")
            return
        self.client.answer_callback_query(callback_id)

    def _handle_fill_view_callback(self, callback_id, chat_id, message_id, data):
        try:
            _, address, view = data.split(":", 2)
            address = normalize_address(address)
        except (ValueError, TypeError):
            self.client.answer_callback_query(callback_id, "无效的按钮数据。")
            return
        if view not in FILL_STATS_VIEW_LABELS:
            self.client.answer_callback_query(callback_id, "无效的视图。")
            return
        now_ms = int(time.time() * 1000)
        self.store.set_chat_setting(
            chat_id,
            f"fill_stats_view:{address}",
            view,
            now_ms,
        )
        self.store.set_chat_setting(
            chat_id,
            f"fill_stats_page:{address}:{view}",
            "0",
            now_ms,
        )
        try:
            self.router.refresh_fill_stats(chat_id, address)
        except Exception as exc:
            print(f"[telegram] 切换成交统计视图失败: {exc}")
            self.client.answer_callback_query(callback_id, "切换失败，请重试。")
            return
        label = FILL_STATS_VIEW_LABELS[view]
        self.client.answer_callback_query(callback_id, f"已切换为{label}视图。")

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

        now_ms = int(time.time() * 1000)
        self.store.set_chat_setting(
            chat_id,
            "selected_fill_stats_address",
            address,
            now_ms,
        )
        view = str(
            self.store.get_chat_setting(
                chat_id,
                f"fill_stats_view:{address}",
                "summary",
            )
        )
        if view not in FILL_STATS_VIEW_LABELS:
            view = "summary"
        self.store.set_chat_setting(
            chat_id,
            f"fill_stats_page:{address}:{view}",
            "0",
            now_ms,
        )
        try:
            self.router.refresh_fill_stats(chat_id, address)
        except Exception as exc:
            print(f"[telegram] 切换成交统计地址失败: {exc}")
            self.client.answer_callback_query(callback_id, "切换地址失败，请重试。")
            return
        self.client.answer_callback_query(callback_id)

    def _handle_hunt_page_callback(self, callback_id, chat_id, message_id, data):
        try:
            page = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            self.client.answer_callback_query(callback_id)
            return
        results = self._load_hunt_session(chat_id)
        rendered = self._hunt_page(chat_id, results, page)
        if rendered is None:
            self.client.answer_callback_query(callback_id)
            return
        text, keyboard = rendered
        try:
            self.client.edit_message_text(
                chat_id,
                message_id,
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception as exc:
            print(f"[telegram] 切换大户页失败: {exc}")
        self.client.answer_callback_query(callback_id)

    def _handle_hunt_sub_callback(self, callback_id, chat_id, message_id, data):
        try:
            page = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            self.client.answer_callback_query(callback_id)
            return
        results = self._load_hunt_session(chat_id)
        if page < 0 or page >= len(results):
            self.client.answer_callback_query(callback_id)
            return
        address = str(results[page].get("address", ""))
        now_ms = int(time.time() * 1000)
        if self._is_subscribed(chat_id, address):
            self.store.unsubscribe(chat_id, address)
            self.monitor.set_addresses(
                self.store.all_watched_addresses(active_only=False)
            )
            self.client.answer_callback_query(callback_id, "已取消订阅。")
        else:
            self.store.subscribe(chat_id, address, ts=now_ms)
            self.monitor.set_addresses(
                self.store.all_watched_addresses(active_only=False)
            )
            self.client.answer_callback_query(callback_id, "已加入监控。")
            self._ask_alias(chat_id, address)
        rendered = self._hunt_page(chat_id, results, page)
        if rendered is not None:
            text, keyboard = rendered
            try:
                self.client.edit_message_text(
                    chat_id,
                    message_id,
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            except Exception as exc:
                print(f"[telegram] 更新订阅状态失败: {exc}")

    def _handle_hunt_style_callback(self, callback_id, chat_id, message_id, data):
        try:
            page = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            self.client.answer_callback_query(callback_id)
            return
        current = str(
            self.store.get_chat_setting(chat_id, "hunt_spark_width", "long")
        )
        new_mode = "short" if current == "long" else "long"
        self.store.set_chat_setting(
            chat_id,
            "hunt_spark_width",
            new_mode,
            int(time.time() * 1000),
        )
        results = self._load_hunt_session(chat_id)
        rendered = self._hunt_page(chat_id, results, page)
        if rendered is not None:
            text, keyboard = rendered
            try:
                self.client.edit_message_text(
                    chat_id,
                    message_id,
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            except Exception as exc:
                print(f"[telegram] 切换走势样式失败: {exc}")
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
        elif command == "/hunt":
            self._cmd_hunt(chat_id, args)
        elif command == "/huntlist":
            self._cmd_huntlist(chat_id)
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
        placeholder_id = self._send_loading(chat_id, "⏳ 正在获取成交统计…")
        try:
            self.router.refresh_fill_stats(
                chat_id,
                address,
                force_new=True,
                target_message_id=placeholder_id,
            )
        except Exception as exc:
            error_text = f"打开成交统计失败: {exc}"
            if placeholder_id is not None:
                self.client.edit_message_text(
                    chat_id,
                    placeholder_id,
                    error_text,
                )
            else:
                self.client.send_message(chat_id, error_text)

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

        placeholder_id = self._send_loading(chat_id, "⏳ 正在整理持仓历史…")
        try:
            report = self.monitor.history_report(address)
        except Exception as exc:
            error_text = f"查询持仓历史失败: {exc}"
            if placeholder_id is not None:
                self.client.edit_message_text(
                    chat_id,
                    placeholder_id,
                    error_text,
                )
            else:
                self.client.send_message(chat_id, error_text)
            return
        if placeholder_id is not None:
            self.client.edit_message_text(
                chat_id,
                placeholder_id,
                report,
                parse_mode="HTML",
            )
        else:
            self.client.send_message(chat_id, report, parse_mode="HTML")

    def _cmd_hunt(self, chat_id, args):
        placeholder_id = self._send_loading(chat_id, "⏳ 正在扫描 Hyperliquid 大户…")
        try:
            limit = int(args.strip())
            if limit <= 0:
                limit = 0
        except (TypeError, ValueError):
            limit = 0

        def progress(done, total, address):
            if placeholder_id is not None and done % 3 == 0:
                try:
                    self.client.edit_message_text(
                        chat_id,
                        placeholder_id,
                        f"⏳ 正在精算胜率 {done}/{total}…",
                    )
                except Exception:
                    pass

        def chart_progress(done, total, address):
            if placeholder_id is not None and done % 2 == 0:
                try:
                    self.client.edit_message_text(
                        chat_id,
                        placeholder_id,
                        f"⏳ 正在生成盈利曲线 {done}/{total}…",
                    )
                except Exception:
                    pass

        def work():
            try:
                results = scan(self.config, self.monitor.api, progress=progress)
                if limit > 0:
                    results = results[:limit]
                for item in results:
                    self.store.upsert_collected_account(item)
                attach_charts(self.monitor.api, results, progress=chart_progress)
                if not results:
                    text = "当前没有符合条件的账户"
                    if placeholder_id is not None:
                        self.client.edit_message_text(
                            chat_id,
                            placeholder_id,
                            text,
                        )
                    else:
                        self.client.send_message(chat_id, text)
                    return
                self._store_hunt_session(chat_id, results)
                rendered = self._hunt_page(chat_id, results, 0)
                if rendered is None:
                    return
                text, keyboard = rendered
                if placeholder_id is not None:
                    self.client.edit_message_text(
                        chat_id,
                        placeholder_id,
                        text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                else:
                    self.client.send_message(
                        chat_id,
                        text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
            except Exception as exc:
                print(f"[telegram] 大户扫描失败: {exc}")
                error_text = f"大户扫描失败: {exc}"
                if placeholder_id is not None:
                    self.client.edit_message_text(
                        chat_id,
                        placeholder_id,
                        error_text,
                    )
                else:
                    self.client.send_message(chat_id, error_text)

        threading.Thread(target=work, daemon=True).start()

    def _cmd_huntlist(self, chat_id):
        accounts = self.store.get_collected_accounts()
        if not accounts:
            self.client.send_message(chat_id, "还没有收集到账户，先用 /hunt 扫描。")
            return
        placeholder_id = self._send_loading(chat_id, "⏳ 正在整理已收集账户…")

        def chart_progress(done, total, address):
            if placeholder_id is not None and done % 2 == 0:
                try:
                    self.client.edit_message_text(
                        chat_id,
                        placeholder_id,
                        f"⏳ 正在生成盈利曲线 {done}/{total}…",
                    )
                except Exception:
                    pass

        def work():
            try:
                attach_charts(self.monitor.api, accounts, progress=chart_progress)
                self._store_hunt_session(chat_id, accounts)
                rendered = self._hunt_page(chat_id, accounts, 0)
                if rendered is None:
                    return
                text, keyboard = rendered
                if placeholder_id is not None:
                    self.client.edit_message_text(
                        chat_id,
                        placeholder_id,
                        text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                else:
                    self.client.send_message(
                        chat_id,
                        text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
            except Exception as exc:
                print(f"[telegram] 查看已收集账户失败: {exc}")
                error_text = f"查看已收集账户失败: {exc}"
                if placeholder_id is not None:
                    self.client.edit_message_text(
                        chat_id,
                        placeholder_id,
                        error_text,
                    )
                else:
                    self.client.send_message(chat_id, error_text)

        threading.Thread(target=work, daemon=True).start()

    def _store_hunt_session(self, chat_id, results):
        self.store.set_chat_setting(
            chat_id,
            f"hunt_session:{chat_id}",
            json.dumps(results, ensure_ascii=False),
            int(time.time() * 1000),
        )

    def _load_hunt_session(self, chat_id):
        raw = self.store.get_chat_setting(chat_id, f"hunt_session:{chat_id}", None)
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (TypeError, ValueError):
            return []

    def _is_subscribed(self, chat_id, address):
        address = str(address).lower()
        subscriptions = self.store.get_subscriptions(
            chat_id=chat_id,
            active_only=False,
        )
        return any(
            str(sub["address"]).lower() == address for sub in subscriptions
        )

    def _hunt_card_keyboard(self, page, total, subscribed, spark_long=True):
        nav = []
        if page > 0:
            nav.append(
                {"text": "◀️ 上一页", "callback_data": f"hp:{page - 1}"}
            )
        nav.append(
            {
                "text": "✅ 已订阅" if subscribed else "➕ 订阅",
                "callback_data": f"hs:{page}",
            }
        )
        if page < total - 1:
            nav.append(
                {"text": "下一页 ▶️", "callback_data": f"hp:{page + 1}"}
            )
        toggle_text = "📉 紧凑走势" if spark_long else "📈 完整走势"
        return {"inline_keyboard": [nav, [{"text": toggle_text, "callback_data": f"ht:{page}"}]]}

    def _hunt_page(self, chat_id, results, page):
        if page < 0 or page >= len(results):
            return None
        account = dict(results[page])
        subscriptions = self.store.get_subscriptions(
            chat_id=chat_id,
            active_only=False,
        )
        sub_map = {
            str(sub["address"]).lower(): str(sub.get("alias") or "")
            for sub in subscriptions
        }
        key = str(account.get("address", "")).lower()
        account["alias"] = sub_map.get(key) or account.get("alias") or ""
        spark_long = (
            str(self.store.get_chat_setting(chat_id, "hunt_spark_width", "long"))
            != "short"
        )
        spark_width = 32 if spark_long else 18
        text = format_account_card_html(
            account,
            page + 1,
            len(results),
            spark_width=spark_width,
        )
        keyboard = self._hunt_card_keyboard(
            page,
            len(results),
            key in sub_map,
            spark_long=spark_long,
        )
        return text, keyboard

    def _ask_alias(self, chat_id, address):
        now_ms = int(time.time() * 1000)
        self.store.set_chat_setting(
            chat_id,
            f"pending_alias:{chat_id}",
            address,
            now_ms,
        )
        result = self.client.send_message(
            chat_id,
            "给它起个名字吗？直接回复名字，或发送 /skip 跳过。",
        )
        prompt_id = (result or {}).get("message_id")
        if prompt_id is not None:
            self.store.set_chat_setting(
                chat_id,
                f"pending_alias_prompt:{chat_id}",
                str(prompt_id),
                now_ms,
            )

    def _finish_alias(self, chat_id, address, alias):
        prompt_id = self.store.get_chat_setting(
            chat_id,
            f"pending_alias_prompt:{chat_id}",
            None,
        )
        now_ms = int(time.time() * 1000)
        self.store.set_chat_setting(chat_id, f"pending_alias:{chat_id}", "", now_ms)
        self.store.set_chat_setting(
            chat_id,
            f"pending_alias_prompt:{chat_id}",
            "",
            now_ms,
        )
        if alias:
            self.store.set_subscription_alias(chat_id, address, alias, ts=now_ms)
            done_text = f"✅ 已命名：{alias}"
        else:
            done_text = "已跳过命名。"
        if prompt_id:
            try:
                self.client.edit_message_text(chat_id, int(prompt_id), done_text)
            except Exception as exc:
                print(f"[telegram] 命名提示更新失败: {exc}")
                self.client.send_message(chat_id, done_text)

            def vanish():
                try:
                    self.client.delete_message(chat_id, int(prompt_id))
                except Exception:
                    pass

            threading.Timer(4.0, vanish).start()
        else:
            self.client.send_message(chat_id, done_text)

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
        self.client.send_typing(chat_id)
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
            self.client.send_typing(chat_id)
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

    def _send_loading(self, chat_id, text="⏳ 正在获取数据，请稍候…"):
        try:
            result = self.client.send_message(chat_id, text)
            self.client.send_typing(chat_id)
            return (result or {}).get("message_id")
        except Exception as exc:
            print(f"[telegram] 发送加载提示失败 ({chat_id}): {exc}")
            return None

    def _send_status(self, chat_id, address, sort_mode="value"):
        placeholder_id = self._send_loading(chat_id, "⏳ 正在获取账户数据…")
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
                target_message_id=placeholder_id,
            )
        except Exception as exc:
            error_text = f"查询 {short_addr(address)} 失败: {exc}"
            if placeholder_id is not None:
                self.client.edit_message_text(
                    chat_id,
                    placeholder_id,
                    error_text,
                )
            else:
                self.client.send_message(chat_id, error_text)

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
