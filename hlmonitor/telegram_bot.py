"""Interactive Telegram bot for managing and receiving Hyperliquid alerts."""

from __future__ import annotations

import json
import html
import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import Config, normalize_address
from .brief import (
    BRIEF_PAGE_SIZE,
    cluster_open_orders,
    format_position_brief_html_data,
    interval_stats,
    sort_positions,
)
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
from .hunter import _build_coin_dex_map, attach_charts, format_account_card_html, scan
from .monitor import AddressMonitor
from .net import build_opener
from .state import EventStore


HELP_TEXT = """Hyperliquid 地址监控 Bot

/add 0x地址 [别名] - 添加监控地址
/name 新名称 [0x地址/旧名称] - 命名或重命名；只发名称则改当前查看的地址
/remove 0x地址 - 删除地址
/removeall - 删除当前聊天的全部地址
/list - 查看当前监控列表
/status [0x地址] - 查询当前账户/持仓状态
/stats [0x地址] - 打开或刷新成交统计面板
/history [0x地址] - 查看历史持仓（来自最近成交记录）
/tpsl [0x地址] - 查看当前挂着的止盈止损单
/orders [0x地址] - 查看普通挂单：先选账户，再选标的，价格相近的会合并成密集区间
/recent [条数] - 查看最近事件
/hunt [数量] - 先选择要统计的标的（或综合），再输入数量扫描大户
/huntlist - 查看已收集的大户账户（可一键加入监控）
/autohunt - 设置后台自动收集大户（可选标的、每轮数量与间隔）
/zones [标的] - 查看自动收集账户在所选标的上的挂单密集区
/fillzones [进程名] [标的] - 查看自动收集账户的成交密集区间
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

STOCK_COINS = [
    "AAPL", "TSLA", "NVDA", "META", "AMZN", "MSFT", "GOOGL", "GOOG", "NFLX",
    "AMD", "INTC", "COIN", "MSTR", "SPY", "QQQ", "PLTR", "AVGO", "ORCL",
    "CRM", "UBER", "SHOP", "PYPL", "ABNB", "TSM", "BABA", "DIS", "NKE",
    "JPM", "V", "MA", "XOM", "WMT", "PG", "KO", "PEP", "MCD", "HD",
    "CSCO", "QCOM", "TXN", "IBM", "ADBE", "SNOW", "CRWD", "PANW", "BAC",
    "COST", "LLY", "ASML", "ARM",
]

HUNT_METAL_SYMBOLS = {
    "GOLD", "SILVER", "PLATINUM", "PALLADIUM",
    "XAU", "XAG", "PAXG", "XAUT",
}

HUNT_STOCK_SYMBOLS = set(STOCK_COINS) | {
    "SNDK", "CRCL", "SKHX", "RIVN", "CRWV", "GME", "HIMS", "DKNG",
    "LITE", "MRVL", "RKLB", "BIRD", "ZM", "EBAY", "NOW", "NBIS",
    "WDC", "NOK", "STRC", "AMAT", "IBIDEN", "GEV", "IREN", "NET",
    "RDDT", "AAOI", "MRNA", "SHEIN", "KIOXIA", "SOFTBANK", "HYUNDAI", "SMSN",
    "BX", "DELL", "UNITREE", "CXMT", "YMTC", "SKHY", "GIGADEV", "SHAZ",
    "LYTE", "RTX", "XIAOMI", "TENCENT", "KWEB", "CAMBRICON", "NAVER", "SMCI",
    "MELI", "SOFI", "TTWO", "COHR", "GLW", "CRDO", "LRCX", "STX",
    "VST", "TER", "CIEN", "IONQ", "GPRO", "IGV", "GLDMINE", "SMH",
    "SOXL", "MAGS", "XBI", "XLE", "URNM", "KORU", "KSTR", "EWY",
    "EWJ", "EWZ", "EWT", "SPACEX", "OPENAI", "ANTHROPIC", "OAI", "ANTH",
    "BB", "INNOLIGHT",
}


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
                {
                    "text": "美股",
                    "callback_data": "c:cat:stocks",
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


def hunt_category_keyboard(swing=False):
    return {
        "inline_keyboard": [
            [
                {"text": "主流币种", "callback_data": "hq:cat:main"},
                {"text": "贵金属", "callback_data": "hq:cat:metal"},
                {"text": "美股", "callback_data": "hq:cat:stocks"},
            ],
            [
                {"text": "其他币种", "callback_data": "hq:cat:other"},
                {"text": "综合（全部）", "callback_data": "hq:all"},
            ],
            [
                {"text": "🔍 搜索标的", "callback_data": "hq:find"},
            ],
            [
                {"text": f"📈 波段/中长线：{'开' if swing else '关'}", "callback_data": "hq:swing"},
            ],
        ]
    }


def hunt_coins_keyboard(category, coins, selected, page=0):
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
                    "callback_data": f"hq:{category}:t:{page}:{coin}",
                }
            )
        rows.append(row)

    nav = []
    if page > 0:
        nav.append(
            {
                "text": "◀️ 上一页",
                "callback_data": f"hq:{category}:n:{page - 1}",
            }
        )
    if page < total_pages - 1:
        nav.append(
            {
                "text": "下一页 ▶️",
                "callback_data": f"hq:{category}:n:{page + 1}",
            }
        )
    if nav:
        rows.append(nav)
    rows.append(
        [
            {"text": "全选", "callback_data": f"hq:{category}:a"},
            {"text": "清空", "callback_data": f"hq:{category}:c"},
        ]
    )
    rows.append(
        [
            {"text": "🔍 搜索", "callback_data": "hq:find"},
        ]
    )
    rows.append(
        [
            {"text": "返回分类", "callback_data": "hq:back"},
            {"text": "✅ 完成，输入数量", "callback_data": f"hq:done:{category}"},
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
    ("interval", "区间"),
    ("summary", "汇总"),
    ("timeline", "流水"),
)
FILL_STATS_VIEW_LABELS = {key: label for key, label in FILL_STATS_VIEWS}


def fill_stats_keyboard(
    address,
    window_min=5,
    subscriptions=None,
    selected_address=None,
    view="interval",
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

    def pair_text(value, size):
        if value > 1e-9:
            return f"{fmt_usd_cn(value)} / {fmt_szi(size)}"
        return "-"

    chunks = []
    for coin, stat in page_coins:
        net = stat["buy_notional"] - stat["sell_notional"]
        if net > 1e-9:
            direction = "净多"
        elif net < -1e-9:
            direction = "净空"
        else:
            direction = "均衡"
        open_buy = pair_text(stat["open_buy_notional"], stat["open_buy_size"])
        open_sell = pair_text(stat["open_sell_notional"], stat["open_sell_size"])
        close_buy = pair_text(stat["close_buy_notional"], stat["close_buy_size"])
        close_sell = pair_text(stat["close_sell_notional"], stat["close_sell_size"])
        rows = (
            f"<tr><td>开仓</td><td>{stat['open_count']} 笔</td>"
            f"<td>平仓</td><td>{stat['close_count']} 笔</td></tr>"
            f"<tr><td>买入</td><td>{html.escape(open_buy)}</td>"
            f"<td>买入</td><td>{html.escape(close_buy)}</td></tr>"
            f"<tr><td>卖出</td><td>{html.escape(open_sell)}</td>"
            f"<td>卖出</td><td>{html.escape(close_sell)}</td></tr>"
            f"<tr><td>成交额</td><td>{html.escape(fmt_usd_cn(stat['notional']))}</td>"
            f"<td>最近</td><td>{html.escape(fmt_time_min(stat['last_time']))}</td></tr>"
        )
        chunks.append(
            f"<b>{html.escape(coin)} · {direction}</b>"
            f"<table bordered compact>{rows}</table>"
        )
    head_text = "\n".join(lines)
    if not chunks:
        return head_text, total_pages
    return head_text + "\n\n" + "".join(chunks), total_pages


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
                "interval",
            )
        )
        if view not in FILL_STATS_VIEW_LABELS:
            view = "interval"

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
        self._hunt_universe_cache = None
        self._hunt_universe_cache_at = 0
        self._auto_thread = None
        self._auto_run_lock = threading.Lock()

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

        self._auto_thread = threading.Thread(
            target=self._auto_hunt_loop,
            name="auto-hunt-loop",
            daemon=True,
        )
        self._auto_thread.start()

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
            # Run every button callback on a worker thread so the polling
            # thread is never blocked by network requests.
            self._async(lambda cb=callback: self._process_callback(cb))
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
        pending_limit = self.store.get_chat_setting(
            chat_id,
            "pending_hunt_limit",
            None,
        )
        if pending_limit:
            first_word = (
                text.split(maxsplit=1)[0].split("@", 1)[0].lower()
                if text
                else ""
            )
            if first_word == "/skip":
                self._clear_hunt_pending(chat_id)
                self.client.send_message(chat_id, "已取消 hunt。")
                return
            if text.startswith("/"):
                self._clear_hunt_pending(chat_id)
            else:
                try:
                    limit = int(text.strip())
                except (TypeError, ValueError):
                    self.client.send_message(
                        chat_id,
                        "请输入数字（例如 10；0 = 默认数量），或回复 /skip 取消。",
                    )
                    return
                if limit < 0:
                    limit = 0
                if limit > 50:
                    limit = 50
                self.store.set_chat_setting(
                    chat_id,
                    "pending_hunt_limit",
                    None,
                    int(time.time() * 1000),
                )
                self._run_hunt(chat_id, limit, self._load_hunt_filter(chat_id))
                return
        pending_search = self.store.get_chat_setting(
            chat_id,
            "pending_hunt_search",
            None,
        )
        if pending_search:
            first_word = (
                text.split(maxsplit=1)[0].split("@", 1)[0].lower()
                if text
                else ""
            )
            if first_word == "/skip":
                self._clear_hunt_search(chat_id)
                self.client.send_message(chat_id, "已取消搜索。")
                return
            if text.startswith("/"):
                self._clear_hunt_search(chat_id)
            else:
                self._show_hunt_search_results(chat_id, text)
                return
        pending_auto_params = self.store.get_chat_setting(
            chat_id,
            "pending_autohunt_params",
            None,
        )
        if pending_auto_params:
            proc = str(self.store.get_chat_setting(chat_id, "pending_autohunt_name", "") or "")
            now_ms = int(time.time() * 1000)
            if not proc:
                self.store.set_chat_setting(chat_id, "pending_autohunt_params", None, now_ms)
                self.client.send_message(chat_id, "设置进程名丢失，请重新 /autohunt new 名称。")
                return
            if text.lower().startswith("/skip"):
                self.store.set_chat_setting(chat_id, "pending_autohunt_params", None, now_ms)
                self.store.set_chat_setting(chat_id, "pending_autohunt_name", None, now_ms)
                self.client.send_message(chat_id, "已取消设置。")
                return
            if text.startswith("/"):
                self.store.set_chat_setting(chat_id, "pending_autohunt_params", None, now_ms)
                self.store.set_chat_setting(chat_id, "pending_autohunt_name", None, now_ms)
            else:
                raw = text.replace(",", " ").split()
                try:
                    limit = int(float(raw[0])) if raw else 20
                    interval_h = float(raw[1]) if len(raw) > 1 else 6.0
                except (ValueError, IndexError):
                    limit = None
                if limit is None or limit < 0 or interval_h <= 0:
                    self.client.send_message(chat_id, "格式不对，请回复两个数字：每轮数量 间隔小时，例如 20 6。")
                    return
                key = self._auto_key(proc, "limit")
                self.store.set_chat_setting(chat_id, key, str(int(limit)), now_ms)
                self.store.set_chat_setting(chat_id, self._auto_key(proc, "interval_h"), str(float(interval_h)), now_ms)
                self.store.set_chat_setting(chat_id, self._auto_key(proc, "enabled"), "1", now_ms)
                self.store.set_chat_setting(chat_id, self._auto_key(proc, "last_run"), "0", now_ms)
                self.store.set_chat_setting(chat_id, "pending_autohunt_params", None, now_ms)
                self.store.set_chat_setting(chat_id, "pending_autohunt_name", None, now_ms)
                self.client.send_message(
                    chat_id,
                    f"✔ 进程 {proc} 已启动：每轮收集 {int(limit)} 个，每 {float(interval_h):g} 小时跑一次。\n"
                    f"可用 /autohunt list 查看，/autohunt off {proc} 停止，/zones {proc} 查看挂单区。",
                )
                return
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

        if data.startswith("fzw:"):
            self._handle_fillzones_window_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return
        if data.startswith("fz:"):
            self._handle_fillzones_view_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
            return
        if data.startswith("hq:"):
            self._handle_hunt_pick_callback(
                callback_id,
                chat_id,
                message_id,
                data,
            )
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
                "interval",
            )
        )
        if view not in FILL_STATS_VIEW_LABELS:
            view = "interval"
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
                "interval",
            )
        )
        if view not in FILL_STATS_VIEW_LABELS:
            view = "interval"
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

        if category not in {"main", "metal", "stocks", "other"}:
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
        elif command == "/autohunt":
            self._cmd_autohunt(chat_id, args)
        elif command == "/zones":
            self._cmd_zones(chat_id, args)
        elif command == "/fillzones":
            self._cmd_fillzones(chat_id, args)
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
        if not parts or not parts[0].strip():
            self.client.send_message(
                chat_id,
                "用法: /name 新名称 [0x地址或旧名称]\n"
                "只发一个名称时，会改名当前正在查看的地址（例如 /status 选中的那个）。",
            )
            return
        alias = parts[0].strip()
        if len(parts) > 1 and parts[1].strip():
            address = self._resolve_address(chat_id, parts[1].strip())
            if not address:
                self.client.send_message(
                    chat_id,
                    "找不到该地址或旧名称，请先用 /list 查看，或直接发 0x 地址。",
                )
                return
        else:
            address = self.store.get_chat_setting(
                chat_id,
                "selected_brief_address",
                None,
            )
            if not address:
                self.client.send_message(
                    chat_id,
                    "当前没有正在查看的地址，请带上 0x 地址或旧名称。",
                )
                return
        subscriptions = self.store.get_subscriptions(
            chat_id=chat_id,
            active_only=False,
        )
        if str(address).lower() not in {
            str(sub["address"]).lower() for sub in subscriptions
        }:
            self.client.send_message(chat_id, "该地址尚未添加，请先订阅或使用 /add。")
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
            self._async(lambda: self._send_status(chat_id, address, sort_mode))
            return

        subscriptions = self.store.get_subscriptions(chat_id=chat_id, active_only=False)
        if not subscriptions:
            self.client.send_message(chat_id, "当前没有监控地址，请用 /add 添加。")
            return
        self._async(
            lambda: self._send_status(chat_id, subscriptions[0]["address"], sort_mode)
        )

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
        def work():
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
        self._async(work)

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

        def work():
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
        self._async(work)

    def _cmd_hunt(self, chat_id, args):
        if args.strip():
            try:
                limit = int(args.strip())
                if limit < 0:
                    limit = 0
            except ValueError:
                self.client.send_message(
                    chat_id,
                    "数量格式不对，例如 /hunt 10；不带参数可先选标的。",
                )
                return
            self._run_hunt(chat_id, limit, self._load_hunt_filter(chat_id))
            return
        self._clear_hunt_pending(chat_id)
        self.client.send_message(
            chat_id,
            "选择要统计胜率的标的（可多选）；选「综合」则按全部交易计算：",
            reply_markup=hunt_category_keyboard(self._hunt_swing_enabled(chat_id)),
        )

    def _load_hunt_filter(self, chat_id):
        raw = self.store.get_chat_setting(chat_id, "hunt_coins", None)
        if raw is None:
            return None
        try:
            coins = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if not isinstance(coins, list) or not coins:
            return None
        out = []
        for c in coins:
            c = str(c).upper()
            if ":" in c:
                c = c.rsplit(":", 1)[-1]
            if c not in out:
                out.append(c)
        return out

    def _get_hunt_selected(self, chat_id, coins):
        raw = self.store.get_chat_setting(chat_id, "hunt_sel", None)
        if raw is None:
            return set()
        try:
            selected = set(json.loads(raw))
        except (TypeError, ValueError):
            return set()
        return {coin for coin in selected if coin in coins}

    def _set_hunt_selected(self, chat_id, selected):
        self.store.set_chat_setting(
            chat_id,
            "hunt_sel",
            json.dumps(sorted(selected), ensure_ascii=False),
            int(time.time() * 1000),
        )

    def _hunt_swing_enabled(self, chat_id):
        hunter = getattr(getattr(self, "config", None), "hunter", None)
        if hunter is not None and getattr(hunter, "swing_mode", False):
            return True
        return str(self.store.get_chat_setting(chat_id, "hunt_swing", None)) == "1"

    def _clear_hunt_search(self, chat_id):
        now_ms = int(time.time() * 1000)
        prompt_id = self.store.get_chat_setting(chat_id, "hunt_search_prompt", None)
        if prompt_id:
            try:
                self.client.delete_message(chat_id, int(prompt_id))
            except Exception:
                pass
        self.store.set_chat_setting(chat_id, "pending_hunt_search", None, now_ms)
        self.store.set_chat_setting(chat_id, "hunt_search_query", None, now_ms)
        self.store.set_chat_setting(chat_id, "hunt_search_prompt", None, now_ms)

    def _ask_hunt_search(self, chat_id):
        now_ms = int(time.time() * 1000)
        self.store.set_chat_setting(chat_id, "pending_hunt_search", "1", now_ms)
        result = self.client.send_message(
            chat_id,
            "🔍 直接回复要搜索的标的名称（支持关键字，如 GOLD / TSLA / XYZ），或 /skip 取消。",
        )
        prompt_id = (result or {}).get("message_id")
        if prompt_id is not None:
            self.store.set_chat_setting(
                chat_id,
                "hunt_search_prompt",
                str(prompt_id),
                now_ms,
            )

    def _hunt_search_symbols(self, query):
        query = str(query or "").strip().lower()
        if not query:
            return []
        found = set()
        for coin in self._get_hunt_coins():
            coin = str(coin)
            if query in coin.lower():
                symbol = coin.rsplit(":", 1)[-1].upper() if ":" in coin else coin.upper()
                found.add(symbol)
        for symbol in self._get_hunt_symbols():
            if query in symbol.lower():
                found.add(symbol)
        return sorted(found)

    def _show_hunt_search_results(self, chat_id, query):
        now_ms = int(time.time() * 1000)
        self.store.set_chat_setting(chat_id, "pending_hunt_search", None, now_ms)
        matches = self._hunt_search_symbols(query)
        prompt_id = self.store.get_chat_setting(chat_id, "hunt_search_prompt", None)
        if not matches:
            self.store.set_chat_setting(chat_id, "hunt_search_query", None, now_ms)
            text = f"没有找到匹配 “{query.strip()}” 的标的，试试 GOLD / TSLA / XYZ 这类关键字。"
            if prompt_id:
                try:
                    self.client.edit_message_text(chat_id, int(prompt_id), text)
                    return
                except Exception:
                    pass
            self.client.send_message(chat_id, text)
            return
        self.store.set_chat_setting(chat_id, "hunt_search_query", str(query).strip(), now_ms)
        symbols = self._get_hunt_symbols()
        selected = self._get_hunt_selected(chat_id, symbols)
        sel_count = len(selected & set(matches))
        text = f"搜索结果 “{query.strip()}”：已选 {sel_count}/{len(matches)}，可多选"
        keyboard = hunt_coins_keyboard("search", matches, selected)
        if prompt_id:
            try:
                self.client.edit_message_text(
                    chat_id,
                    int(prompt_id),
                    text,
                    reply_markup=keyboard,
                )
                return
            except Exception:
                pass
        self.client.send_message(chat_id, text, reply_markup=keyboard)

    def _clear_hunt_pending(self, chat_id):
        now_ms = int(time.time() * 1000)
        self.store.set_chat_setting(chat_id, "pending_hunt_limit", None, now_ms)
        self.store.set_chat_setting(chat_id, "hunt_sel", None, now_ms)
        self._clear_hunt_search(chat_id)

    def _hunt_category_coins(self, category, coins):
        # Classify by the symbol after any dex prefix (xyz:GOLD -> GOLD),
        # so HIP-3 builder markets work too.
        if category == "main":
            return [coin for coin in MAIN_COINS if coin in coins]
        symbol = lambda coin: coin.rsplit(":", 1)[-1] if ":" in coin else coin
        if category == "metal":
            return [coin for coin in coins if symbol(coin) in HUNT_METAL_SYMBOLS]
        if category == "stocks":
            return [coin for coin in coins if symbol(coin) in HUNT_STOCK_SYMBOLS]
        main_coins = set(MAIN_COINS) & set(coins)
        return [
            coin
            for coin in coins
            if coin not in main_coins
            and symbol(coin) not in HUNT_METAL_SYMBOLS
            and symbol(coin) not in HUNT_STOCK_SYMBOLS
        ]

    def _ask_hunt_limit(self, chat_id, coins):
        now_ms = int(time.time() * 1000)
        self.store.set_chat_setting(
            chat_id,
            "hunt_coins",
            json.dumps([str(c).upper() for c in coins], ensure_ascii=False),
            now_ms,
        )
        self.store.set_chat_setting(chat_id, "hunt_sel", None, now_ms)
        self.store.set_chat_setting(chat_id, "pending_hunt_limit", "1", now_ms)
        scope = "、".join(str(c) for c in coins) if coins else "全部标的（综合）"
        self.client.send_message(
            chat_id,
            f"已选择：{scope}\n要 hunt 多少个账户？直接回复数字（例如 10；0 = 默认数量）。",
        )

    def _run_hunt(self, chat_id, limit, coins):
        placeholder_id = self._send_loading(chat_id, "⏳ 正在扫描 Hyperliquid 大户…")

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
                results = scan(
                    self.config,
                    self.monitor.api,
                    progress=progress,
                    coins=coins,
                    swing_mode=self._hunt_swing_enabled(chat_id),
                    max_results=(limit if limit > 0 else None),
                )
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

    def _handle_hunt_pick_callback(self, callback_id, chat_id, message_id, data):
        try:
            coins = self._get_hunt_symbols()
        except Exception as exc:
            self.client.answer_callback_query(callback_id, f"获取标的失败: {exc}")
            return
        selected = self._get_hunt_selected(chat_id, coins)
        parts = data.split(":")
        if len(parts) < 2:
            self.client.answer_callback_query(callback_id)
            return
        head = parts[1]
        auto_setup = self.store.get_chat_setting(chat_id, "pending_autohunt_setup", None)
        if head == "back":
            self.client.edit_message_text(
                chat_id,
                message_id,
                "设置自动猎手：选择要追踪的标的（可多选）"
                if auto_setup
                else "选择要统计胜率的标的（可多选）；选「综合」则按全部交易计算：",
                reply_markup=hunt_category_keyboard(self._hunt_swing_enabled(chat_id)),
            )
            self.client.answer_callback_query(callback_id)
            return
        if head == "swing":
            hunter = getattr(getattr(self, "config", None), "hunter", None)
            if hunter is not None and getattr(hunter, "swing_mode", False):
                self.client.answer_callback_query(callback_id, "波段模式已在配置中开启。")
                return
            now_ms = int(time.time() * 1000)
            new_state = not self._hunt_swing_enabled(chat_id)
            self.store.set_chat_setting(
                chat_id,
                "hunt_swing",
                "1" if new_state else None,
                now_ms,
            )
            text = "选择要统计胜率的标的（可多选）；选「综合」则按全部交易计算："
            keyboard = hunt_category_keyboard(new_state)
            try:
                self.client.edit_message_text(
                    chat_id,
                    message_id,
                    text,
                    reply_markup=keyboard,
                )
            except Exception as exc:
                print(f"[telegram] 切换波段模式失败: {exc}")
                self.client.answer_callback_query(callback_id, "切换失败，请重试。")
                return
            self.client.answer_callback_query(
                callback_id,
                "已开启波段/中长线模式" if new_state else "已关闭波段模式",
            )
            return
        if head == "find":
            self._ask_hunt_search(chat_id)
            self.client.answer_callback_query(callback_id)
            return
        if head == "all":
            self._set_hunt_selected(chat_id, set())
            if auto_setup:
                self._finish_autohunt_coins(chat_id, [])
            else:
                self._ask_hunt_limit(chat_id, [])
            self.client.answer_callback_query(callback_id, "已选综合（全部）")
            return
        if head == "done" and len(parts) >= 3:
            if auto_setup:
                self._finish_autohunt_coins(chat_id, sorted(selected))
            else:
                self._ask_hunt_limit(chat_id, sorted(selected))
            self.client.answer_callback_query(callback_id)
            return
        if head == "cat" and len(parts) >= 3:
            category = parts[2]
            action = ""
            page = 0
        else:
            category = head
            action = parts[2] if len(parts) > 2 else ""
            page = 0
            if action == "n" and len(parts) >= 4:
                page = int(parts[3])

        if category not in {"main", "metal", "stocks", "other", "search"}:
            self.client.answer_callback_query(callback_id)
            return

        if category == "search":
            query = str(self.store.get_chat_setting(chat_id, "hunt_search_query", "") or "")
            category_coins = self._hunt_search_symbols(query)
        else:
            category_coins = self._hunt_category_coins(category, coins)

        if action == "t" and len(parts) >= 5:
            page = int(parts[3])
            coin = ":".join(parts[4:])
            if coin in selected:
                selected.discard(coin)
            else:
                selected.add(coin)
        elif action == "a":
            selected.update(category_coins)
        elif action == "c":
            selected.difference_update(category_coins)
        elif action not in {"", "n"}:
            self.client.answer_callback_query(callback_id)
            return

        self._set_hunt_selected(chat_id, selected)
        if not category_coins:
            if category == "search":
                text = "没有找到匹配的标的，点击 🔍 可重新搜索。"
            else:
                text = f"{self._category_label(category)}：当前没有可用标的。"
            keyboard = {
                "inline_keyboard": [
                    [{"text": "返回分类", "callback_data": "hq:back"}]
                ]
            }
        else:
            sel_in_cat = selected & set(category_coins)
            if category == "search":
                text = (
                    f"搜索结果 “{query}”：已选 "
                    f"{len(sel_in_cat)}/{len(category_coins)}，可多选"
                )
            else:
                text = (
                    f"选择 {self._category_label(category)}（已选 "
                    f"{len(sel_in_cat)}/{len(category_coins)}，可多选）"
                )
            keyboard = hunt_coins_keyboard(
                category,
                category_coins,
                selected,
                page,
            )
        try:
            self.client.edit_message_text(
                chat_id,
                message_id,
                text,
                reply_markup=keyboard,
            )
        except Exception as exc:
            print(f"[telegram] 更新 hunt 标的菜单失败: {exc}")
            self.client.answer_callback_query(callback_id, "更新失败，请重试。")
            return
        self.client.answer_callback_query(callback_id)

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
        self._async(lambda: self._send_tpsl(chat_id, address))

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
            self._async(
                lambda: (
                    self.client.send_typing(chat_id),
                    self._show_orders_coin_menu(chat_id, address),
                )
            )
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

    def _async(self, fn):
        threading.Thread(target=fn, daemon=True).start()

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

    def _get_hunt_coins(self):
        """Native perps plus all HIP-3 builder perp coins (cached)."""
        now = time.time()
        if self._hunt_universe_cache and now - self._hunt_universe_cache_at < 6 * 3600:
            return self._hunt_universe_cache
        coins = set(self._get_coins())
        try:
            dexs = self.monitor.api.perp_dexs() or []
            for item in dexs:
                if not isinstance(item, dict):
                    continue
                dex = str(item.get("name") or "")
                if not dex:
                    continue
                meta = self.monitor.api.meta_by_dex(dex) or {}
                for uni in meta.get("universe") or []:
                    name = str(uni.get("name") or "")
                    if name:
                        coins.add(name)
        except Exception as exc:
            print(f"[telegram] fetch HIP-3 coins failed, fallback to native: {exc}")
        out = sorted(coins)
        self._hunt_universe_cache = out
        self._hunt_universe_cache_at = now
        return out

    def _get_hunt_symbols(self):
        """Dedupe the hunt universe by bare symbol for the picker."""
        symbols = set()
        for coin in self._get_hunt_coins():
            coin = str(coin).upper()
            if ":" in coin:
                coin = coin.rsplit(":", 1)[-1]
            symbols.add(coin)
        return sorted(symbols)

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
        if category == "stocks":
            return [coin for coin in STOCK_COINS if coin in coins]
        known = (
            set(MAIN_COINS)
            | set(PRECIOUS_METAL_COINS)
            | set(STOCK_COINS)
        )
        return [coin for coin in coins if coin not in known]

    @staticmethod
    def _category_label(category):
        return {
            "main": "主流币种",
            "metal": "贵金属",
            "stocks": "美股",
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

    # ---------- auto hunt processes ----------

    @staticmethod
    def _auto_key(name, field):
        return f"autohunt_proc:{name}:{field}"

    def _autohunt_names(self, chat_id):
        return self.store.get_autohunt_names(chat_id)

    def _auto_config(self, chat_id, name):
        if not name:
            return None
        key = self._auto_key
        raw_coins = self.store.get_chat_setting(chat_id, key(name, "coins"), None)
        coins = None
        if raw_coins:
            try:
                parsed = json.loads(raw_coins)
                if isinstance(parsed, list) and parsed:
                    coins = sorted({str(c).upper() for c in parsed})
            except (TypeError, ValueError):
                pass
        try:
            limit = max(1, int(float(str(self.store.get_chat_setting(chat_id, key(name, "limit"), "20")))))
        except (TypeError, ValueError):
            limit = 20
        try:
            interval_h = max(1.0, float(str(self.store.get_chat_setting(chat_id, key(name, "interval_h"), "6"))))
        except (TypeError, ValueError):
            interval_h = 6.0
        try:
            last_run = int(float(str(self.store.get_chat_setting(chat_id, key(name, "last_run"), "0"))))
        except (TypeError, ValueError):
            last_run = 0
        enabled = str(self.store.get_chat_setting(chat_id, key(name, "enabled"), None)) == "1"
        configured = raw_coins is not None
        return {
            "name": name,
            "configured": configured,
            "coins": coins,
            "limit": limit,
            "interval_h": interval_h,
            "enabled": enabled,
            "last_run": last_run,
        }

    def _finish_autohunt_coins(self, chat_id, coins):
        name = str(self.store.get_chat_setting(chat_id, "pending_autohunt_name", "") or "")
        now_ms = int(time.time() * 1000)
        if not name:
            self.client.send_message(chat_id, "设置进程名失效了，请重新 /autohunt new 名称。")
            return
        key = self._auto_key
        self.store.set_chat_setting(
            chat_id,
            key(name, "coins"),
            json.dumps(sorted(set(str(c).upper() for c in coins)), ensure_ascii=False),
            now_ms,
        )
        self.store.set_chat_setting(chat_id, "pending_autohunt_setup", None, now_ms)
        self.store.set_chat_setting(chat_id, "hunt_sel", None, now_ms)
        self.store.set_chat_setting(chat_id, "pending_autohunt_params", "1", now_ms)
        scope = "、".join(sorted(set(str(c).upper() for c in coins))) if coins else "全部标的（综合）"
        self.client.send_message(
            chat_id,
            f"进程 {name} 已选择：{scope}\n"
            "请回复两个数字：每轮自动收集多少个 间隔多少小时。例如：20 6",
        )

    def _cmd_autohunt(self, chat_id, args):
        names = self._autohunt_names(chat_id)
        parts = args.strip().split(maxsplit=1)
        mode = parts[0].lower() if parts else ""
        rest = parts[1].strip() if len(parts) > 1 else ""

        if not mode or mode in {"list", "ls", "status"}:
            if not names:
                self.client.send_message(
                    chat_id,
                    "还没有自动猎手进程。\n"
                    "用法：/autohunt new 名称\n"
                    "例如：/autohunt new btc\n"
                    "然后按提示选标的、回复“数量 间隔小时”。",
                )
                return
            lines = ["自动猎手进程："]
            for name in sorted(names):
                cfg = self._auto_config(chat_id, name)
                if not cfg:
                    continue
                accounts = self.store.get_auto_accounts(chat_id, name)
                scope = "、".join(cfg["coins"]) if cfg["coins"] else "综合"
                status = "运行中" if cfg["enabled"] else "已停止"
                lines.append(
                    f"· {name}：{scope} | 每轮 {cfg['limit']} | 间隔 {cfg['interval_h']:g}h | {status} | 账户 {len(accounts)}"
                )
            lines.append("管理：/autohunt on|off|now|del 名称 | 新建：/autohunt new 名称")
            self.client.send_message(chat_id, "\n".join(lines))
            return

        if mode in {"new", "add"}:
            name = rest.split(maxsplit=1)[0].strip().lower() if rest else ""
            if not name or not all(ch.isalnum() or ch in "_-" for ch in name) or len(name) > 24:
                self.client.send_message(chat_id, "进程名请用字母/数字/下划线/短横线，最长 24 个字符，例如 btc_gold。")
                return
            now_ms = int(time.time() * 1000)
            self.store.set_chat_setting(chat_id, "pending_autohunt_name", name, now_ms)
            self.store.set_chat_setting(chat_id, "pending_autohunt_setup", "1", now_ms)
            self.store.set_chat_setting(chat_id, "hunt_sel", None, now_ms)
            tip = "（该名称已存在，重新设置会覆盖之前的标的）\n" if name in names else ""
            self.client.send_message(
                chat_id,
                f"创建进程 {name}，选择要追踪的标的（可多选）；选「综合」则按全部交易计算：\n{tip}",
                reply_markup=hunt_category_keyboard(self._hunt_swing_enabled(chat_id)),
            )
            return

        if mode in {"progress", "prog"} and not rest and len(names) > 1:
            blocks = [
                self._autohunt_progress_text(chat_id, name)
                for name in sorted(names)
            ]
            self.client.send_message(chat_id, "\n\n".join(blocks))
            return
        if mode in {"on", "off", "now", "del", "run", "progress", "prog"}:
            if rest:
                name = rest.split()[0].lower()
            elif len(names) == 1:
                name = names[0]
            else:
                name = ""
            if not name or name not in names:
                if not names:
                    self.client.send_message(chat_id, "还没有进程，先 /autohunt new 名称。")
                elif name:
                    self.client.send_message(chat_id, f"找不到进程 {name}，先 /autohunt list 查看。")
                else:
                    self.client.send_message(chat_id, "有多个进程，请指定名称，例如 /autohunt now 名称。")
                return
            now_ms = int(time.time() * 1000)
            key = self._auto_key
            if mode == "on":
                self.store.set_chat_setting(chat_id, key(name, "enabled"), "1", now_ms)
                self.store.set_chat_setting(chat_id, key(name, "last_run"), "0", now_ms)
                self.client.send_message(chat_id, f"进程 {name} 已开启，到点会自动扫描。")
            elif mode == "off":
                self.store.set_chat_setting(chat_id, key(name, "enabled"), None, now_ms)
                self.client.send_message(chat_id, f"进程 {name} 已停止（已收集账户保留）。")
            elif mode in {"now", "run"}:
                cfg = self._auto_config(chat_id, name)
                if not cfg or not cfg["configured"]:
                    self.client.send_message(chat_id, f"进程 {name} 还没选标的，先 /autohunt new {name} 重设。")
                    return
                self._start_auto_scan(chat_id, name, manual=True)
            elif mode in {"progress", "prog"}:
                cfg = self._auto_config(chat_id, name)
                self.client.send_message(
                    chat_id,
                    self._autohunt_progress_text(chat_id, name, cfg),
                )
            elif mode == "del":
                self.store.remove_auto_accounts(chat_id, name)
                for field in ("coins", "limit", "interval_h", "enabled", "last_run"):
                    self.store.set_chat_setting(chat_id, key(name, field), None, now_ms)
                self.client.send_message(chat_id, f"进程 {name} 已删除。")
            return

        self.client.send_message(
            chat_id,
            "用法：\n"
            "/autohunt new 名称 - 新建一个自动猎手进程\n"
            "/autohunt list - 查看所有进程\n"
            "/autohunt on|off|now|del|progress [名称] - 启动/停止/立即跑/删除/查进度（一个时可省略名称）\n"
            "查看挂单区：/zones 进程名 [标的]",
        )

    def _auto_hunt_loop(self):
        while True:
            if self._stop.wait(60):
                return
            try:
                self._run_due_auto_hunts()
            except Exception as exc:
                print(f"[autohunt] loop error: {exc}")

    def _run_due_auto_hunts(self):
        for chat_id, name in self.store.enabled_autohunt_processes():
            cfg = self._auto_config(chat_id, name)
            if not cfg or not cfg["enabled"]:
                continue
            now_ms = int(time.time() * 1000)
            interval_ms = max(1.0, cfg["interval_h"]) * 3600000
            if cfg["last_run"] and now_ms - cfg["last_run"] < interval_ms:
                continue
            if not self._auto_run_lock.acquire(blocking=False):
                continue

            def run_locked(cid=chat_id, proc=name):
                try:
                    self._run_auto_scan(cid, proc)
                except Exception as exc:
                    print(f"[autohunt] scan failed {cid}/{proc}: {exc}")
                finally:
                    self.store.set_chat_setting(
                        cid,
                        self._auto_key(proc, "last_run"),
                        str(int(time.time() * 1000)),
                        int(time.time() * 1000),
                    )
                    self._auto_run_lock.release()

            threading.Thread(target=run_locked, daemon=True).start()

    def _start_auto_scan(self, chat_id, name, manual=False):
        if not self._auto_run_lock.acquire(blocking=False):
            if manual:
                self.client.send_message(chat_id, "已经有一轮自动猎手在跑，稍后再试。")
            return
        if manual:
            self.client.send_message(chat_id, f"🔄 进程 {name} 开始扫描，完成后会通知你。")

        def run_locked(cid=chat_id, proc=name):
            try:
                self._run_auto_scan(cid, proc)
            except Exception as exc:
                print(f"[autohunt] scan failed {cid}/{proc}: {exc}")
            finally:
                self.store.set_chat_setting(
                    cid,
                    self._auto_key(proc, "last_run"),
                    str(int(time.time() * 1000)),
                    int(time.time() * 1000),
                )
                self._auto_run_lock.release()

        threading.Thread(target=run_locked, daemon=True).start()

    def _autohunt_progress_text(self, chat_id, name, cfg=None):
        cfg = cfg or self._auto_config(chat_id, name)
        if not cfg:
            return f"进程 {name} 不存在。"
        key = self._auto_key
        running = str(self.store.get_chat_setting(chat_id, key(name, "progress_running"), None)) == "1"
        accounts = self.store.get_auto_accounts(chat_id, name)
        lines = [f"进程 {name}"]
        if running:
            try:
                done = int(float(str(self.store.get_chat_setting(chat_id, key(name, "progress_done"), "0"))))
                total = int(float(str(self.store.get_chat_setting(chat_id, key(name, "progress_total"), "0"))))
            except (TypeError, ValueError):
                done = 0
                total = 0
            total = max(total, 1)
            done = min(max(done, 0), total)
            pct = done / total
            width = 12
            filled = round(pct * width)
            bar = "█" * filled + "░" * (width - filled)
            lines.append(f"扫描中 {bar} {done}/{total} ({pct * 100:.0f}%)")
        elif cfg["enabled"]:
            if cfg["last_run"]:
                next_ms = cfg["last_run"] + int(max(1.0, cfg["interval_h"]) * 3600000)
                wait_min = max(0, int((next_ms - int(time.time() * 1000)) / 60000))
                lines.append(f"等待下一轮：约 {wait_min} 分钟后")
            else:
                lines.append("已开启，等待首轮扫描")
        else:
            lines.append("已停止")
        scope = "、".join(cfg["coins"]) if cfg["coins"] else "综合"
        lines.append(f"标的：{scope} · 每轮 {cfg['limit']} · 间隔 {cfg['interval_h']:g}h · 已收集 {len(accounts)}")
        lines.append("/autohunt now " + name + " 可立即跑一轮")
        return "\n".join(lines)

    def _run_auto_scan(self, chat_id, name):
        cfg = self._auto_config(chat_id, name)
        if not cfg or not cfg["configured"]:
            return
        now_ms = int(time.time() * 1000)
        key = self._auto_key
        self.store.set_chat_setting(chat_id, key(name, "progress_running"), "1", now_ms)
        self.store.set_chat_setting(chat_id, key(name, "progress_done"), "0", now_ms)
        self.store.set_chat_setting(chat_id, key(name, "progress_total"), "0", now_ms)
        skip_hours = float(getattr(self.config.hunter, "auto_skip_hours", 12.0))
        since_ms = int(now_ms - max(skip_hours, 0.5) * 3600000)
        seen = self.store.recent_auto_scanned(chat_id, name, since_ms)
        scanned_out = []
        try:
            def progress(done, total, address):
                ts = int(time.time() * 1000)
                self.store.set_chat_setting(chat_id, key(name, "progress_done"), str(done), ts)
                self.store.set_chat_setting(chat_id, key(name, "progress_total"), str(total), ts)
            results = scan(
                self.config,
                self.monitor.api,
                coins=cfg["coins"],
                max_results=cfg["limit"],
                exclude=seen,
                scanned_out=scanned_out,
                progress=progress,
            )
            if scanned_out:
                self.store.record_auto_scanned(chat_id, name, scanned_out, ts=now_ms)
            self.store.purge_auto_scanned(chat_id, name, since_ms)
            for item in results:
                self.store.upsert_auto_account(chat_id, name, item, ts=now_ms)
        finally:
            self.store.set_chat_setting(chat_id, key(name, "progress_running"), None, int(time.time() * 1000))
        total = len(self.store.get_auto_accounts(chat_id, name))
        scope = "、".join(cfg["coins"]) if cfg["coins"] else "综合"
        self.client.send_message(
            chat_id,
            f"进程 {name} 本轮完成：实际精算 {len(scanned_out)} 个（跳过近期已扫 {len(seen)} 个），"
            f"新收录 {len(results)} 个账户（{scope}），自动列表共 {total} 个。\n用 /zones {name} 查看挂单密集区。",
        )

    # ---------- auto account order zones ----------

    def _cmd_zones(self, chat_id, args):
        names = self._autohunt_names(chat_id)
        if not names:
            self.client.send_message(chat_id, "还没有自动猎手进程，先 /autohunt new 名称。")
            return
        parts = args.strip().split()
        proc = None
        symbols_text = []
        if parts and parts[0].lower() in {n.lower() for n in names}:
            proc = next(n for n in names if n.lower() == parts[0].lower())
            symbols_text = parts[1:]
        elif len(names) == 1:
            proc = names[0]
            symbols_text = parts
        else:
            self.client.send_message(
                chat_id,
                "你有多个自动猎手进程，请指定：/zones 进程名 [标的]，例如 /zones btc BTC GOLD。\n"
                "进程：" + "、".join(sorted(names)),
            )
            return
        cfg = self._auto_config(chat_id, proc)
        symbols = []
        for token in symbols_text:
            token = str(token).upper()
            if ":" in token:
                token = token.rsplit(":", 1)[-1]
            if token not in symbols:
                symbols.append(token)
        if not symbols:
            symbols = list((cfg or {}).get("coins") or [])
        if not symbols:
            self.client.send_message(
                chat_id,
                f"进程 {proc} 设的是综合，/zones {proc} 需要带标的，例如 /zones {proc} BTC GOLD。",
            )
            return
        accounts = self.store.get_auto_accounts(chat_id, proc)
        if not accounts:
            self.client.send_message(chat_id, f"进程 {proc} 的自动列表还是空的，先等它跑一轮。")
            return
        placeholder_id = self._send_loading(chat_id, "🔍 正在拉取自动账户挂单并聚合…")
        def work():
            try:
                text = self._build_auto_zones_report(chat_id, proc, symbols, accounts)
            except Exception as exc:
                print(f"[zones] report failed: {exc}")
                text = f"挂单区统计失败: {exc}"
            if placeholder_id is not None:
                try:
                    self.client.edit_message_text(chat_id, placeholder_id, text, parse_mode="HTML")
                except Exception:
                    self.client.send_message(chat_id, text, parse_mode="HTML")
            else:
                self.client.send_message(chat_id, text, parse_mode="HTML")
        threading.Thread(target=work, daemon=True).start()

    def _build_auto_zones_report(self, chat_id, proc, symbols, accounts):
        selected = set(symbols)
        api = self.monitor.api
        dex_map = _build_coin_dex_map(api)
        dexes = set()
        for symbol in selected:
            dexes.update(dex_map.get(symbol, set()))
        if not dexes:
            dexes.add("")
        flat = []
        for account in accounts[:40]:
            address = str(account.get("address", ""))
            for dex in sorted(dexes):
                try:
                    orders = (
                        api.frontend_open_orders(address)
                        if dex == ""
                        else api.frontend_open_orders(address, dex)
                    )
                except Exception:
                    continue
                for order in orders or []:
                    if order.get("isTrigger") or order.get("isPositionTpsl"):
                        continue
                    raw_coin = str(order.get("coin") or "")
                    symbol = raw_coin.rsplit(":", 1)[-1].upper() if ":" in raw_coin else raw_coin.upper()
                    if symbol not in selected:
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
        if not flat:
            scope = "、".join(sorted(selected))
            return f"进程 {proc}：这些自动账户目前在 {scope} 上没有普通挂单。"
        merge = self.config.order_merge
        clusters = cluster_open_orders(
            flat,
            max_gap_pct=merge.base_gap_pct,
            width_multiplier=merge.width_multiplier,
            scale=1.0,
            ladder_detection=True,
            ladder_min_orders=merge.ladder_min_orders,
            ladder_max_cv=merge.ladder_max_cv,
        )
        rows = []
        for cluster in clusters:
            accounts_in = {str(o.get("_account") or "") for o in cluster}
            stats = interval_stats(cluster)
            total_value = stats["total_value"]
            if len(cluster) < 3 and len(accounts_in) < 2 and total_value < 200000:
                continue
            rows.append(
                {
                    "side": stats["side"],
                    "coin": str(cluster[0].get("coin") or ""),
                    "min_px": stats["min_px"],
                    "max_px": stats["max_px"],
                    "orders": len(cluster),
                    "accounts": len(accounts_in),
                    "value": total_value,
                }
            )
        rows.sort(key=lambda item: (item["accounts"], item["value"]), reverse=True)
        rows = rows[:12]
        account_count = len({str(a.get("address", "")) for a in accounts[:40]})
        lines = [
            f"<b>自动猎手 {proc} · 挂单密集区</b>",
            f"统计账户：{account_count} 个 · 标的：{'、'.join(sorted(selected))}",
            "<table bordered compact>",
            "<tr><td>方向</td><td>币种</td><td>价格区间</td><td>单数/账户</td><td>名义金额</td></tr>",
        ]
        for item in rows:
            if item["max_px"] >= 1000:
                price = f"{item['min_px']:,.0f} - {item['max_px']:,.0f}"
            else:
                price = f"{item['min_px']:,.2f} - {item['max_px']:,.2f}"
            lines.append(
                "<tr>"
                f"<td>{item['side']}</td>"
                f"<td>{item['coin']}</td>"
                f"<td>{price}</td>"
                f"<td>{item['orders']}单/{item['accounts']}户</td>"
                f"<td>{fmt_usd_cn(item['value'])}</td>"
                "</tr>"
            )
        lines.append("</table>")
        lines.append("数据为实时查询；价格相近的挂单会自动聚成区间。")
        return "\n".join(lines)


    # ---------- auto account fill zones ----------



    def _fillzones_ctx_key(self, proc):
        return f"fillzones_rows:{proc}"

    def _cmd_fillzones(self, chat_id, args):
        names = self._autohunt_names(chat_id)
        if not names:
            self.client.send_message(chat_id, "还没有自动猎手进程，先 /autohunt new 名称。")
            return
        parts = args.strip().split()
        proc = None
        symbols_text = []
        if parts and parts[0].lower() in {n.lower() for n in names}:
            proc = next(n for n in names if n.lower() == parts[0].lower())
            symbols_text = parts[1:]
        elif len(names) == 1:
            proc = names[0]
            symbols_text = parts
        else:
            self.client.send_message(
                chat_id,
                "你有多个自动猎手进程，请指定：/fillzones 进程名 [标的]，例如 /fillzones btc BTC GOLD。\n"
                "进程：" + "、".join(sorted(names)),
            )
            return
        cfg = self._auto_config(chat_id, proc)
        symbols = []
        for token in symbols_text:
            token = str(token).upper()
            if ":" in token:
                token = token.rsplit(":", 1)[-1]
            if token not in symbols:
                symbols.append(token)
        if not symbols:
            symbols = list((cfg or {}).get("coins") or [])
        if not symbols:
            self.client.send_message(
                chat_id,
                f"进程 {proc} 设的是综合，/fillzones {proc} 需要带标的，例如 /fillzones {proc} BTC GOLD。",
            )
            return
        accounts = self.store.get_auto_accounts(chat_id, proc)
        if not accounts:
            self.client.send_message(chat_id, f"进程 {proc} 的自动列表还是空的，先等它跑一轮。")
            return
        placeholder_id = self._send_loading(chat_id, "🔍 正在拉取自动账户成交并聚类…")
        def work():
            window_min = 0
            try:
                rows, account_count = self._fetch_fillzones_rows(
                    proc, symbols, accounts, window_min=window_min
                )
            except Exception as exc:
                print(f"[fillzones] report failed: {exc}")
                text = f"成交区统计失败: {exc}"
                if placeholder_id is not None:
                    try:
                        self.client.edit_message_text(chat_id, placeholder_id, text)
                    except Exception:
                        self.client.send_message(chat_id, text)
                else:
                    self.client.send_message(chat_id, text)
                return
            if not rows:
                scope = "、".join(sorted(symbols))
                text = f"进程 {proc}：这些自动账户近期在 {scope} 上没有可聚类的成交。"
                if placeholder_id is not None:
                    try:
                        self.client.edit_message_text(chat_id, placeholder_id, text)
                    except Exception:
                        self.client.send_message(chat_id, text)
                else:
                    self.client.send_message(chat_id, text)
                return
            now_ms = int(time.time() * 1000)
            self.store.set_chat_setting(chat_id, f"fillzones_window:{proc}", str(window_min), now_ms)
            self.store.set_chat_setting(chat_id, self._fillzones_ctx_key(proc), json.dumps(rows), now_ms)
            self.store.set_chat_setting(
                chat_id,
                f"fillzones_symbols:{proc}",
                json.dumps(sorted(symbols), ensure_ascii=False),
                now_ms,
            )
            view = str(self.store.get_chat_setting(chat_id, f"fillzones_view:{proc}", "table") or "table")
            text = self._format_fillzones_view(
                proc, symbols, rows, account_count, view,
                window_label=self._fillzones_window_label(window_min),
            )
            keyboard = self._fillzones_keyboard(proc, view, window_min)
            if placeholder_id is not None:
                try:
                    self.client.edit_message_text(
                        chat_id,
                        placeholder_id,
                        text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                    return
                except Exception:
                    pass
            self.client.send_message(
                chat_id,
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        threading.Thread(target=work, daemon=True).start()

    def _fetch_fillzones_rows(self, proc, symbols, accounts, window_min=None):
        selected = set(symbols)
        api = self.monitor.api
        workers = max(1, int(getattr(self.config.hunter, "scan_workers", 6)))
        cutoff = None
        if window_min:
            cutoff = int(time.time() * 1000) - int(window_min) * 60000

        def fetch_fills(account):
            address = str(account.get("address", ""))
            try:
                if cutoff is None:
                    fills = api.user_fills(address) or []
                else:
                    fills = []
                    end = int(time.time() * 1000) + 1000
                    for _ in range(4):
                        batch = api.user_fills_by_time(address, cutoff, end) or []
                        if not batch:
                            break
                        fills.extend(batch)
                        if len(batch) < 2000 or len(fills) >= 8000:
                            break
                        times = [int(item.get("time") or 0) for item in batch if item.get("time")]
                        if not times:
                            break
                        end = min(times) - 1
            except Exception:
                return []
            out = []
            for fill in fills:
                raw_coin = str(fill.get("coin") or "")
                symbol = raw_coin.rsplit(":", 1)[-1].upper() if ":" in raw_coin else raw_coin.upper()
                if symbol not in selected:
                    continue
                try:
                    px = float(fill.get("px") or 0)
                    size = abs(float(fill.get("sz") or 0))
                except (TypeError, ValueError):
                    continue
                if px <= 0 or size <= 0:
                    continue
                item = dict(fill)
                item["coin"] = symbol
                item["_account"] = address
                out.append(item)
            return out

        flat = []
        if workers > 1 and len(accounts) > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(fetch_fills, acc): acc for acc in accounts[:40]}
                for future in as_completed(futures):
                    try:
                        flat.extend(future.result())
                    except Exception as exc:
                        print(f"[fillzones] fetch failed: {exc}")
        else:
            for account in accounts[:40]:
                flat.extend(fetch_fills(account))

        clusters = _cluster_fills_by_price(flat)
        rows = []
        for cluster in clusters:
            accounts_in = {str(o.get("_account") or "") for o in cluster}
            stat = _cluster_interval_stats(cluster)
            total_value = stat["total_value"]
            if len(cluster) < 3 and len(accounts_in) < 2 and total_value < 200000:
                continue
            rows.append(
                {
                    "side": stat["side"],
                    "coin": str(cluster[0].get("coin") or ""),
                    "min_px": stat["min_px"],
                    "max_px": stat["max_px"],
                    "fills": len(cluster),
                    "accounts": len(accounts_in),
                    "value": total_value,
                }
            )
        rows.sort(key=lambda item: (item["accounts"], item["value"]), reverse=True)
        rows = rows[:20]
        account_count = len({str(a.get("address", "")) for a in accounts[:40]})
        return rows, account_count

    def _format_fillzones_view(
        self, proc, symbols, rows, account_count, view, window_label=None
    ):
        summary = f"统计账户：{account_count} 个 · 标的：{'、'.join(sorted(symbols))} · 每账户最近 2000 笔"
        if window_label:
            summary += f" · 窗口：{window_label}"
        if view == "graph":
            return self._format_fillzones_graph(proc, rows, summary)
        return self._format_fillzones_table(proc, rows, summary)

    @staticmethod
    def _fill_side_marker(side):
        return "🟢" if str(side) == "买入" else "🔴"

    def _format_fillzones_table(self, proc, rows, summary):
        lines = [f"<b>自动猎手 {proc} · 成交密集区间（表格）</b>", summary]
        coins = list(dict.fromkeys(r["coin"] for r in rows))
        for coin in coins:
            coin_rows = sorted(
                (r for r in rows if r["coin"] == coin),
                key=lambda r: r["max_px"],
                reverse=True,
            )
            if not coin_rows:
                continue
            lines.append(f"<b>{coin}</b>")
            lines.append("<table bordered compact>")
            lines.append(
                "<tr><td></td><td>价格区间</td><td>笔数/账户</td><td>成交额</td></tr>"
            )
            for item in coin_rows:
                marker = self._fill_side_marker(item["side"])
                if item["max_px"] >= 1000:
                    price = f"{item['min_px']:,.0f} - {item['max_px']:,.0f}"
                else:
                    price = f"{item['min_px']:,.2f} - {item['max_px']:,.2f}"
                lines.append(
                    "<tr>"
                    f"<td>{marker}</td>"
                    f"<td>{price}</td>"
                    f"<td>{item['fills']}笔/{item['accounts']}户</td>"
                    f"<td>{fmt_usd_cn(item['value'])}</td>"
                    "</tr>"
                )
            lines.append("</table>")
        lines.append("🟢 = 买入 · 🔴 = 卖出；每个标的内按价格从高到低排列。")
        return "\n".join(lines)

    def _format_fillzones_graph(self, proc, rows, summary):
        lines = [
            f"<b>自动猎手 {proc} · 成交密集区间（图形）</b>",
            summary,
        ]
        coins = list(dict.fromkeys(r["coin"] for r in rows))
        for coin in coins:
            coin_rows = sorted(
                (r for r in rows if r["coin"] == coin),
                key=lambda r: r["max_px"],
                reverse=True,
            )
            if not coin_rows:
                continue
            lines.append(f"<b>{coin}</b>")
            max_value = max(r["value"] for r in coin_rows) or 1
            width = 22
            chart = []
            for item in coin_rows:
                bar_len = max(1, round(item["value"] / max_value * width))
                if item["max_px"] >= 1000:
                    price = f"{item['min_px']:,.0f}-{item['max_px']:,.0f}"
                else:
                    price = f"{item['min_px']:,.2f}-{item['max_px']:,.2f}"
                marker = self._fill_side_marker(item["side"])
                bar = "-" * bar_len
                chart.append(f"{marker} {price} {bar} | {fmt_usd_cn(item['value'])}")
            lines.append("<pre>" + "\n".join(html.escape(row) for row in chart) + "</pre>")
        lines.append("🟢 = 买入 · 🔴 = 卖出；每个标的内按价格从高到低排列。")
        return "\n".join(lines)

    @staticmethod
    def _fillzones_window_label(window_min):
        if int(window_min) == 0:
            return "全部（最新 2000 笔）"
        return dict(FILL_WINDOWS).get(int(window_min), f"{int(window_min)}分钟")

    def _fillzones_keyboard(self, proc, view, window_min=60):
        rows = []
        current = []
        for minutes, label in [(0, "全部")] + list(FILL_WINDOWS):
            btn_text = f"✅ {label}" if int(minutes) == int(window_min) else label
            current.append(
                {"text": btn_text, "callback_data": f"fzw:{proc}:{minutes}"}
            )
            if len(current) >= 4:
                rows.append(current)
                current = []
        if current:
            rows.append(current)
        target = "graph" if view == "table" else "table"
        label = "📈 图形视图" if view == "table" else "📊 表格视图"
        rows.append([{"text": label, "callback_data": f"fz:{proc}:{target}"}])
        return {"inline_keyboard": rows}

    def _handle_fillzones_view_callback(self, callback_id, chat_id, message_id, data):
        try:
            _, proc, view = data.split(":", 2)
        except ValueError:
            self.client.answer_callback_query(callback_id)
            return
        raw_rows = self.store.get_chat_setting(chat_id, self._fillzones_ctx_key(proc), None)
        raw_symbols = self.store.get_chat_setting(chat_id, f"fillzones_symbols:{proc}", None)
        if not raw_rows or not raw_symbols:
            self.client.answer_callback_query(callback_id, "请先重新运行 /fillzones。")
            return
        try:
            rows = json.loads(raw_rows)
            symbols = json.loads(raw_symbols)
        except (TypeError, ValueError):
            self.client.answer_callback_query(callback_id, "缓存已失效，请重新运行 /fillzones。")
            return
        account_count = len(
            {str(a.get("address", "")) for a in self.store.get_auto_accounts(chat_id, proc)}
        )
        self.store.set_chat_setting(
            chat_id,
            f"fillzones_view:{proc}",
            view,
            int(time.time() * 1000),
        )
        try:
            window_min = int(float(str(self.store.get_chat_setting(chat_id, f"fillzones_window:{proc}", "0"))))
        except (TypeError, ValueError):
            window_min = 60
        text = self._format_fillzones_view(
            proc,
            symbols,
            rows,
            account_count,
            view,
            window_label=self._fillzones_window_label(window_min),
        )
        keyboard = self._fillzones_keyboard(proc, view, window_min)
        try:
            self.client.edit_message_text(
                chat_id,
                message_id,
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception as exc:
            print(f"[fillzones] view switch failed: {exc}")
            self.client.answer_callback_query(callback_id, "切换失败，请重试。")
            return
        self.client.answer_callback_query(callback_id)


    def _handle_fillzones_window_callback(self, callback_id, chat_id, message_id, data):
        try:
            _, proc, minutes_text = data.split(":", 2)
            window_min = int(minutes_text)
        except (ValueError, IndexError):
            self.client.answer_callback_query(callback_id)
            return
        raw_symbols = self.store.get_chat_setting(chat_id, f"fillzones_symbols:{proc}", None)
        if not raw_symbols:
            self.client.answer_callback_query(callback_id, "请先重新运行 /fillzones。")
            return
        try:
            symbols = json.loads(raw_symbols)
        except (TypeError, ValueError):
            self.client.answer_callback_query(callback_id, "缓存已失效，请重新运行 /fillzones。")
            return
        now_ms = int(time.time() * 1000)
        self.store.set_chat_setting(chat_id, f"fillzones_window:{proc}", str(window_min), now_ms)
        try:
            self.client.edit_message_text(
                chat_id,
                message_id,
                f"正在切换到 {self._fillzones_window_label(window_min)} 窗口并重新聚类…",
            )
        except Exception:
            pass
        view = str(self.store.get_chat_setting(chat_id, f"fillzones_view:{proc}", "table") or "table")

        def work():
            try:
                accounts = self.store.get_auto_accounts(chat_id, proc)
                rows, account_count = self._fetch_fillzones_rows(
                    proc, symbols, accounts, window_min=window_min
                )
            except Exception as exc:
                print(f"[fillzones] window fetch failed: {exc}")
                try:
                    self.client.edit_message_text(
                        chat_id,
                        message_id,
                        f"切换窗口失败: {exc}",
                    )
                except Exception:
                    pass
                self.client.answer_callback_query(callback_id, "切换失败")
                return
            ts = int(time.time() * 1000)
            self.store.set_chat_setting(chat_id, self._fillzones_ctx_key(proc), json.dumps(rows), ts)
            if not rows:
                scope = "、".join(sorted(symbols))
                try:
                    self.client.edit_message_text(
                        chat_id,
                        message_id,
                        f"进程 {proc}：这些自动账户在 {self._fillzones_window_label(window_min)} 窗口内、{scope} 上没有可聚类的成交。",
                    )
                except Exception:
                    pass
                self.client.answer_callback_query(callback_id)
                return
            text = self._format_fillzones_view(
                proc,
                symbols,
                rows,
                account_count,
                view,
                window_label=self._fillzones_window_label(window_min),
            )
            keyboard = self._fillzones_keyboard(proc, view, window_min)
            try:
                self.client.edit_message_text(
                    chat_id,
                    message_id,
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            except Exception as exc:
                print(f"[fillzones] window refresh failed: {exc}")
            self.client.answer_callback_query(callback_id)

        threading.Thread(target=work, daemon=True).start()
