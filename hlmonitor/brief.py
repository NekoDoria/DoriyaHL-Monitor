"""Shared formatting for aggregated per-address position briefs."""

from __future__ import annotations

import html
import math

from .format import fmt_qty, fmt_time, fmt_usd_cn, short_addr


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_positions(positions):
    if isinstance(positions, dict):
        return [
            {"coin": coin, **pos}
            for coin, pos in positions.items()
        ]
    return positions or []


def sort_positions(positions, sort_mode="value"):
    items = normalize_positions(positions)
    if sort_mode == "time":
        def time_key(pos):
            value = int(pos.get("open_time_ms") or 0)
            return (0, value) if value else (1, 0)

        return sorted(
            items,
            key=time_key,
        )
    return sorted(
        items,
        key=lambda pos: abs(_num(pos.get("notional"))),
        reverse=True,
    )


def side_label(szi):
    value = _num(szi)
    if value > 0:
        return "多"
    if value < 0:
        return "空"
    return "平"


def leverage_label(pos):
    try:
        value = float(pos.get("leverage"))
        return f"{value:g}x"
    except (TypeError, ValueError):
        return "-"


def _progress_bar(ratio, length=10):
    ratio = max(0.0, min(1.0, float(ratio or 0)))
    filled = round(ratio * length)
    return "█" * filled + "░" * (length - filled)


BRIEF_PAGE_SIZE = 5


def format_position_brief(
    address,
    summary,
    positions,
    spot_balances=None,
    sort_mode="value",
    title="持仓简报",
    changes=None,
    closed_positions=None,
    include_spot=True,
    spot_limit=10,
):
    changes = changes or {}
    closed_positions = closed_positions or []
    sorted_positions = sort_positions(positions, sort_mode)
    sort_label = "按开仓时间" if sort_mode == "time" else "按仓位价值"

    lines = [
        f"📊 {title} · {short_addr(address)}",
        f"账户净值: {fmt_usd_cn(summary.get('account_value', 0))}",
        f"合约持仓名义: {fmt_usd_cn(summary.get('total_ntl_pos', 0))}",
        f"可提取: {fmt_usd_cn(summary.get('withdrawable', 0))}",
        f"排序: {sort_label}",
    ]

    if sorted_positions:
        lines.append("")
        for index, pos in enumerate(sorted_positions):
            coin = pos.get("coin", "?")
            side = side_label(pos.get("szi"))
            entry = pos.get("entry_px") or "-"
            notional = abs(_num(pos.get("notional")))
            open_time = pos.get("open_time_ms") or 0
            open_label = fmt_time(open_time) if open_time else "未知"
            if index:
                lines.append("─────────────────────")
            lines.append(f"{coin} · {side}")
            if coin in changes:
                lines.append(f"  变动: {changes[coin]}")
            lines.append(f"  持仓: {fmt_usd_cn(notional)}")
            lines.append(f"  峰值: {fmt_usd_cn(pos.get('peak_notional') or notional)}")
            lines.append(f"  杠杆: {leverage_label(pos)}")
            lines.append(f"  入场价: {entry}")
            lines.append(f"  开仓时间: {open_label}")
    else:
        lines.append("")
        lines.append("当前无合约持仓")

    if closed_positions:
        lines.append("")
        lines.append("已平仓：")
        for coin, label in closed_positions:
            lines.append(f"  {coin}：{label}")

    if include_spot and spot_balances:
        nonzero_spot = [
            (coin, balance)
            for coin, balance in (
                spot_balances.items()
                if isinstance(spot_balances, dict)
                else spot_balances
            )
            if _num(balance.get("total")) != 0
        ]
        lines.append("")
        lines.append(f"现货非零余额币种: {len(nonzero_spot)}")
        for coin, balance in nonzero_spot[:spot_limit]:
            lines.append(
                f"  {coin}: {fmt_qty(balance.get('total'))}"
                f"（冻结 {fmt_qty(balance.get('hold'))}）"
            )
        if len(nonzero_spot) > spot_limit:
            lines.append(f"  ... 其余 {len(nonzero_spot) - spot_limit} 个币种省略")

    return "\n".join(lines)


def format_position_brief_data(data, sort_mode="value"):
    return format_position_brief(
        data.get("address", ""),
        data.get("summary", {}),
        data.get("positions", []),
        spot_balances=data.get("spot_balances"),
        sort_mode=sort_mode,
        title=data.get("title", "持仓简报"),
        changes=data.get("changes"),
        closed_positions=data.get("closed_positions"),
        include_spot=data.get("include_spot", True),
        spot_limit=data.get("spot_limit", 10),
    )


def format_position_brief_html(
    address,
    summary,
    positions,
    spot_balances=None,
    sort_mode="value",
    title="持仓简报",
    changes=None,
    closed_positions=None,
    include_spot=True,
    spot_limit=10,
    page=0,
    page_size=BRIEF_PAGE_SIZE,
):
    changes = changes or {}
    closed_positions = closed_positions or []
    sorted_positions = sort_positions(positions, sort_mode)
    total_pages = max(1, math.ceil(len(sorted_positions) / page_size))
    page = max(0, min(page, total_pages - 1))
    page_positions = sorted_positions[
        page * page_size : (page + 1) * page_size
    ]
    sort_label = "按开仓时间" if sort_mode == "time" else "按仓位价值"

    header = "\n".join(
        [
            f"<b>📊 {html.escape(title)} · {html.escape(short_addr(address))}</b>",
            f"账户净值: {html.escape(fmt_usd_cn(summary.get('account_value', 0)))}",
            f"合约持仓名义: {html.escape(fmt_usd_cn(summary.get('total_ntl_pos', 0)))}",
            f"可提取: {html.escape(fmt_usd_cn(summary.get('withdrawable', 0)))}",
            f"排序: {sort_label}",
        ]
    )

    blocks = [header]
    if page_positions:
        total_ntl_pos = abs(_num(summary.get("total_ntl_pos")))
        for pos in page_positions:
            coin = pos.get("coin", "?")
            side = side_label(pos.get("szi"))
            entry = pos.get("entry_px") or "-"
            notional = abs(_num(pos.get("notional")))
            open_time = pos.get("open_time_ms") or 0
            open_label = fmt_time(open_time) if open_time else "未知"

            ratio = notional / total_ntl_pos if total_ntl_pos else 0
            title_line = f"<b>{html.escape(coin)}</b> · {side}"
            lines = []
            if coin in changes:
                lines.append(html.escape(f"变动: {changes[coin]}"))
            lines.extend(
                [
                    html.escape(f"持仓: {fmt_usd_cn(notional)}"),
                    html.escape(
                        f"峰值: {fmt_usd_cn(pos.get('peak_notional') or notional)}"
                    ),
                    html.escape(f"杠杆: {leverage_label(pos)}"),
                    html.escape(f"入场价: {entry}"),
                    html.escape(f"开仓时间: {open_label}"),
                    html.escape(
                        f"占比: {_progress_bar(ratio)} {ratio * 100:.1f}%"
                    ),
                ]
            )
            body = "\n".join(lines)
            blocks.append(
                f"{title_line}\n<blockquote expandable>{body}</blockquote>"
            )
    else:
        blocks.append("<blockquote>当前无合约持仓</blockquote>")

    if page == 0 and closed_positions:
        closed_lines = ["已平仓："]
        for coin, label in closed_positions:
            closed_lines.append(f"{coin}：{label}")
        blocks.append(
            f"<blockquote>{html.escape(chr(10).join(closed_lines))}</blockquote>"
        )

    if page == 0 and include_spot and spot_balances:
        nonzero_spot = [
            (coin, balance)
            for coin, balance in (
                spot_balances.items()
                if isinstance(spot_balances, dict)
                else spot_balances
            )
            if _num(balance.get("total")) != 0
        ]
        spot_lines = [f"现货非零余额币种: {len(nonzero_spot)}"]
        for coin, balance in nonzero_spot[:spot_limit]:
            spot_lines.append(
                f"{coin}: {fmt_qty(balance.get('total'))}"
                f"（冻结 {fmt_qty(balance.get('hold'))}）"
            )
        if len(nonzero_spot) > spot_limit:
            spot_lines.append(f"... 其余 {len(nonzero_spot) - spot_limit} 个币种省略")
        blocks.append(
            f"<blockquote expandable>{html.escape(chr(10).join(spot_lines))}</blockquote>"
        )

    return "\n\n".join(blocks)


def format_position_brief_html_data(data, sort_mode="value", page=0, page_size=BRIEF_PAGE_SIZE):
    return format_position_brief_html(
        data.get("address", ""),
        data.get("summary", {}),
        data.get("positions", []),
        spot_balances=data.get("spot_balances"),
        sort_mode=sort_mode,
        title=data.get("title", "持仓简报"),
        changes=data.get("changes"),
        closed_positions=data.get("closed_positions"),
        include_spot=data.get("include_spot", True),
        spot_limit=data.get("spot_limit", 10),
        page=page,
        page_size=page_size,
    )


def _tpsl_type_label(order):
    label = {
        "Stop Market": "市价止损",
        "Stop Limit": "限价止损",
        "Take Profit Market": "市价止盈",
        "Take Profit Limit": "限价止盈",
    }.get(order.get("orderType"))
    return label or str(order.get("orderType") or "触发单")


def _trigger_condition_cn(condition):
    """把 'Price below 75400' 这类条件翻译成中文。"""
    condition = str(condition or "")
    if condition.startswith("Price below"):
        return "低于 " + condition[len("Price below"):].strip()
    if condition.startswith("Price above"):
        return "高于 " + condition[len("Price above"):].strip()
    return condition


def _tpsl_side(order):
    return "卖出" if str(order.get("side", "")).upper() == "A" else "买入"


def _tpsl_size_text(order):
    if order.get("isPositionTpsl"):
        return "跟随仓位"
    size = _num(order.get("sz"))
    orig = _num(order.get("origSz"))
    if size <= 0:
        return "跟随仓位"
    if orig > 0 and abs(size - orig) > 1e-9:
        return f"{fmt_qty(size)}（原始 {fmt_qty(orig)}）"
    return fmt_qty(size)


def _tpsl_notional(order, mids, position_notionals=None):
    size = _num(order.get("sz"))
    if size <= 0:
        size = _num(order.get("origSz"))
    position_notionals = position_notionals or {}
    position_size = _num(position_notionals.get(order.get("coin")))
    if size <= 0:
        return position_size
    mid = _num(mids.get(order.get("coin")))
    return size * mid


def format_tpsl_report_html(
    address,
    orders,
    mids=None,
    position_notionals=None,
    limit=60,
    max_chars=3800,
):
    """把当前挂着的止盈止损单整理成 HTML 简报。"""
    mids = mids or {}
    position_notionals = position_notionals or {}
    groups = {}
    for order in orders or []:
        coin = str(order.get("coin") or "?")
        groups.setdefault(coin, []).append(order)

    def group_notional(entries):
        return max(
            (
                _tpsl_notional(order, mids, position_notionals)
                for order in entries
            ),
            default=0.0,
        )

    ordered_coins = sorted(
        groups.keys(),
        key=lambda coin: group_notional(groups[coin]),
        reverse=True,
    )

    blocks = [
        "\n".join(
            [
                f"<b>🎯 止盈止损 · {html.escape(short_addr(address))}</b>",
                "数据来源: 当前挂单（已触发或已撤销的不会显示）",
            ]
        )
    ]
    used = len(blocks[0])
    shown = 0
    total = sum(len(entries) for entries in groups.values())
    last_coin = None
    exceeded = False
    for coin in ordered_coins:
        entries = sorted(
            groups[coin],
            key=lambda order: _num(order.get("triggerPx")) or 0,
        )
        for order in entries:
            if shown >= limit:
                exceeded = True
                break
            body = [
                f"{_tpsl_type_label(order)} · {_tpsl_side(order)}",
                f"触发: {_trigger_condition_cn(order.get('triggerCondition')) or '未知'}",
            ]
            order_type = str(order.get("orderType") or "")
            if "Limit" in order_type:
                body.append(f"限价: {order.get('limitPx') or '-'}")
            body.append(f"数量: {_tpsl_size_text(order)}")
            notional = _tpsl_notional(order, mids, position_notionals)
            if notional > 0:
                marker = ""
                if _num(order.get("sz")) <= 0 and _num(order.get("origSz")) <= 0:
                    marker = "（当前仓位）"
                body.append(f"金额: ≈{fmt_usd_cn(notional)}{marker}")
            entry_block = (
                "<blockquote expandable>"
                + "\n".join(html.escape(line) for line in body)
                + "</blockquote>"
            )
            add_cost = len(entry_block) + 2
            if coin != last_coin:
                add_cost += len(f"<b>{html.escape(coin)}</b>") + 2
            if used + add_cost > max_chars:
                exceeded = True
                break
            if coin != last_coin:
                coin_header = f"<b>{html.escape(coin)}</b>"
                blocks.append(coin_header)
                used += len(coin_header) + 2
                last_coin = coin
            blocks.append(entry_block)
            used += len(entry_block) + 2
            shown += 1
        if exceeded:
            break

    if not shown:
        blocks.append("<blockquote>当前没有挂着的止盈止损单</blockquote>")
    elif total > shown:
        blocks.append(f"…… 其余 {total - shown} 条未显示")
    return "\n\n".join(blocks)


def _spot_coin_label(coin, spot_names):
    coin = str(coin or "?")
    if coin.startswith("@"):
        index = coin[1:]
        name = (spot_names or {}).get(index)
        return f"{name}（现货）" if name else f"现货{index}"
    return coin


def _is_uniform_ladder(group, min_orders=5, max_cv=0.30):
    """判断一组同方向挂单是不是间距均匀的网格（阶梯挂单）。"""
    if len(group) < min_orders:
        return False
    pxs = sorted(_num(order.get("limitPx")) for order in group)
    gaps = []
    for prev, current in zip(pxs, pxs[1:]):
        if prev > 0 and current > prev:
            gaps.append((current - prev) / prev * 100)
    if len(gaps) < min_orders - 1:
        return False
    mean = sum(gaps) / len(gaps)
    if mean <= 0:
        return False
    variance = sum((gap - mean) ** 2 for gap in gaps) / len(gaps)
    cv = variance ** 0.5 / mean
    return cv <= max_cv


def cluster_open_orders(
    orders,
    max_gap_pct=0.2,
    gap_by_coin=None,
    width_multiplier=3.0,
    scale=1.0,
    ladder_detection=True,
    ladder_min_orders=5,
    ladder_max_cv=0.30,
):
    """把同方向、价格相近的挂单合并成密集区间。

    相邻两单价格差距不超过 max_gap_pct（百分比）就归入同一区间；
    买入和卖出分开聚类，避免混在一起。gap_by_coin 可按币种覆盖阈值
    （键为原始币种名，如 BTC、@334），适合波动不同的币种分开设置。
    同时限制单个区间总宽度不超过 阈值 × width_multiplier，
    防止间距均匀的网格被链式合并成一个过宽的区间。scale 是粒度缩放
    （细=0.5、自动=1.0、粗=2.0）；ladder_detection 开启时，间距均匀的
    整段网格会直接合并成一个区间，不再受宽度限制。
    """
    gap_by_coin = gap_by_coin or {}
    groups = {}
    for order in orders or []:
        side = str(order.get("side", "")).upper()
        coin = str(order.get("coin") or "?")
        px = _num(order.get("limitPx"))
        size = _num(order.get("sz"))
        if side not in {"B", "A"} or px <= 0 or size <= 0:
            continue
        groups.setdefault((side, coin), []).append(order)

    clusters = []
    for (side, coin), group in groups.items():
        threshold = gap_by_coin.get(coin, max_gap_pct) * scale
        max_width = threshold * width_multiplier
        if ladder_detection and _is_uniform_ladder(
            group,
            min_orders=ladder_min_orders,
            max_cv=ladder_max_cv,
        ):
            clusters.append(list(group))
            continue
        group = sorted(
            group,
            key=lambda order: _num(order.get("limitPx")),
        )
        current = []
        for order in group:
            px = _num(order.get("limitPx"))
            if current:
                last_px = _num(current[-1].get("limitPx"))
                first_px = _num(current[0].get("limitPx"))
                gap_pct = (px - last_px) / last_px * 100 if last_px else 0
                width_pct = (
                    (px - first_px) / first_px * 100 if first_px else 0
                )
                if gap_pct > threshold or width_pct > max_width:
                    clusters.append(current)
                    current = []
            current.append(order)
        if current:
            clusters.append(current)
    return clusters


def interval_stats(cluster):
    """计算一个密集区间的汇总信息（数量加权均价）。"""
    sizes = [_num(order.get("sz")) for order in cluster]
    pxs = [_num(order.get("limitPx")) for order in cluster]
    total_sz = sum(sizes)
    total_value = sum(px * size for px, size in zip(pxs, sizes))
    avg_px = (
        total_value / total_sz
        if total_sz > 0
        else (min(pxs) + max(pxs)) / 2
    )
    return {
        "side": "买入" if str(cluster[0].get("side", "")).upper() == "B" else "卖出",
        "count": len(cluster),
        "min_px": min(pxs),
        "max_px": max(pxs),
        "avg_px": avg_px,
        "total_sz": total_sz,
        "total_value": total_value,
    }


def build_open_orders_summaries(orders, spot_names=None):
    """按币种汇总挂单数量与金额，供币种按钮菜单使用。"""
    spot_names = spot_names or {}
    groups = {}
    for order in orders or []:
        raw = str(order.get("coin") or "?")
        px = _num(order.get("limitPx"))
        size = _num(order.get("sz"))
        if px <= 0 or size <= 0:
            continue
        info = groups.setdefault(raw, {"count": 0, "value": 0.0})
        info["count"] += 1
        info["value"] += px * size
    items = []
    for raw, info in groups.items():
        items.append(
            {
                "coin": raw,
                "label": _spot_coin_label(raw, spot_names),
                "count": info["count"],
                "value": info["value"],
            }
        )
    return sorted(items, key=lambda item: item["value"], reverse=True)


def format_open_orders_intervals_html(
    address,
    orders,
    coin=None,
    mids=None,
    spot_names=None,
    gap_by_coin=None,
    base_gap_pct=0.2,
    width_multiplier=3.0,
    scale=1.0,
    ladder_detection=True,
    ladder_min_orders=5,
    ladder_max_cv=0.30,
    level="auto",
    limit=100,
    max_chars=3800,
):
    """把普通挂单按密集区间整理成 HTML 简报。

    coin 为 None 时展示所有币种；否则只展示该币种。
    """
    mids = mids or {}
    spot_names = spot_names or {}
    gap_by_coin = gap_by_coin or {}
    if coin is not None:
        coin = str(coin)
        filtered = [
            order
            for order in orders or []
            if str(order.get("coin")) == coin
        ]
        display_coin = _spot_coin_label(coin, spot_names)
        threshold = gap_by_coin.get(coin, base_gap_pct) * scale
        title = f"<b>📋 挂单密集区间 · {html.escape(display_coin)}</b>"
        source_line = (
            f"粒度: {level} · 合并阈值 {threshold:g}% · 止盈止损另列"
        )
    else:
        filtered = list(orders or [])
        title = (
            f"<b>📋 挂单密集区间 · "
            f"{html.escape(short_addr(address))}</b>"
        )
        source_line = (
            f"粒度: {level} · 按各币种波动自适应合并 · 止盈止损另列"
        )

    blocks = [
        "\n".join(
            [
                title,
                source_line,
            ]
        )
    ]
    used = len(blocks[0])
    shown = 0
    total = 0
    last_coin = None
    exceeded = False

    groups = {}
    for order in filtered:
        groups.setdefault(str(order.get("coin") or "?"), []).append(order)
    ordered_coins = sorted(
        groups.keys(),
        key=lambda c: sum(
            _num(o.get("limitPx")) * _num(o.get("sz"))
            for o in groups[c]
        ),
        reverse=True,
    )

    for group_coin in ordered_coins:
        clusters = cluster_open_orders(
            groups[group_coin],
            max_gap_pct=base_gap_pct,
            gap_by_coin=gap_by_coin,
            width_multiplier=width_multiplier,
            scale=scale,
            ladder_detection=ladder_detection,
            ladder_min_orders=ladder_min_orders,
            ladder_max_cv=ladder_max_cv,
        )
        total += len(clusters)
        for cluster in clusters:
            if shown >= limit:
                exceeded = True
                break
            stats = interval_stats(cluster)
            ladder = ladder_detection and _is_uniform_ladder(
                cluster,
                min_orders=ladder_min_orders,
                max_cv=ladder_max_cv,
            )
            range_line = (
                f"价格: {fmt_qty(stats['min_px'])}"
                if stats["min_px"] == stats["max_px"]
                else (
                    f"区间: {fmt_qty(stats['min_px'])} – "
                    f"{fmt_qty(stats['max_px'])}"
                )
            )
            body = [
                (
                    f"{stats['side']}网格 · {stats['count']} 笔"
                    if ladder
                    else f"{stats['side']} · {stats['count']} 笔"
                ),
                range_line,
                f"均价: {fmt_qty(stats['avg_px'])}",
                f"数量: {fmt_qty(stats['total_sz'])}",
                f"金额: ≈{fmt_usd_cn(stats['total_value'])}",
            ]
            entry_block = (
                "<blockquote expandable>"
                + "\n".join(html.escape(line) for line in body)
                + "</blockquote>"
            )
            add_cost = len(entry_block) + 2
            if coin is None and group_coin != last_coin:
                display = _spot_coin_label(group_coin, spot_names)
                add_cost += len(f"<b>{html.escape(display)}</b>") + 2
            if used + add_cost > max_chars:
                exceeded = True
                break
            if coin is None and group_coin != last_coin:
                display = _spot_coin_label(group_coin, spot_names)
                coin_header = f"<b>{html.escape(display)}</b>"
                blocks.append(coin_header)
                used += len(coin_header) + 2
                last_coin = group_coin
            blocks.append(entry_block)
            used += len(entry_block) + 2
            shown += 1
        if exceeded:
            break

    if not shown:
        blocks.append("<blockquote>当前没有普通挂单</blockquote>")
    elif total > shown:
        blocks.append(f"…… 其余 {total - shown} 个区间未显示")
    return "\n\n".join(blocks)
