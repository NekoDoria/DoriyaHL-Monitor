"""Hyperliquid 大户扫描：排行榜粗筛 + 成交胜率精算 + 收集。"""

from __future__ import annotations

import html
import json
import math
import threading
import time
import urllib.parse
import urllib.request

from .format import fmt_usd_cn, short_addr
from .net import build_opener

STATS_BASE = "https://stats-data.hyperliquid.xyz/{network}/leaderboard"

_cache_lock = threading.RLock()
_leaderboard_cache: dict[str, tuple[float, list]] = {}


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_pnl(value):
    if value is None:
        return "-"
    num = _num(value)
    sign = "+" if num > 0 else ""
    return f"{sign}{fmt_usd_cn(num)}"


def _window_perf(row, window="allTime"):
    for name, perf in (row.get("windowPerformances") or []):
        if name == window and isinstance(perf, dict):
            return {
                "pnl": _num(perf.get("pnl")),
                "roi": _num(perf.get("roi")),
                "vlm": _num(perf.get("vlm")),
            }
    return {"pnl": 0.0, "roi": 0.0, "vlm": 0.0}


def _leaderboard_opener(proxy_url):
    """socks5 代理转成 http 隧道，规避部分网络环境下的 TLS 握手问题。"""
    if proxy_url:
        parsed = urllib.parse.urlparse(proxy_url)
        scheme = (parsed.scheme or "").lower()
        if scheme in {"socks", "socks5", "socks5h"} and parsed.hostname:
            http_proxy = f"http://{parsed.hostname}:{parsed.port or 7890}"
            return build_opener(http_proxy)
    return build_opener(proxy_url)


def fetch_leaderboard(network="mainnet", proxy_url=None, ttl=1800):
    """拉取 Hyperliquid 排行榜（约 4.4 万账户），带内存缓存与重试。"""
    key = f"{network}:{proxy_url}"
    now = time.time()
    with _cache_lock:
        cached_at, cached = _leaderboard_cache.get(key, (0.0, []))
        if cached_at and now - cached_at < ttl and cached:
            return cached
    url = STATS_BASE.format(network="Mainnet" if network == "mainnet" else "Testnet")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    last_exc = None
    rows = []
    for attempt in range(3):
        try:
            opener = _leaderboard_opener(proxy_url)
            with opener.open(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            rows = (data or {}).get("leaderboardRows") or []
            break
        except Exception as exc:
            last_exc = exc
            time.sleep(1 + attempt)
    if last_exc is not None and not rows:
        raise last_exc
    with _cache_lock:
        _leaderboard_cache[key] = (now, rows)
    return rows


def _fill_win_stats(fills):
    """从最近成交记录计算胜率（笔数）与加权胜率（按盈亏金额）。"""
    wins = 0
    losses = 0
    gross_win = 0.0
    gross_loss = 0.0
    for fill in fills or []:
        pnl = _num(fill.get("closedPnl"))
        if abs(pnl) < 1e-9:
            continue
        if pnl > 0:
            wins += 1
            gross_win += pnl
        else:
            losses += 1
            gross_loss += -pnl
    total = wins + losses
    denom = gross_win + gross_loss
    return {
        "win_rate": wins / total if total else 0.0,
        "weighted_win_rate": gross_win / denom if denom > 0 else 0.0,
        "profit_factor": (
            gross_win / gross_loss
            if gross_loss > 0
            else (float("inf") if gross_win > 0 else 0.0)
        ),
        "sample_size": total,
        "gross_win": gross_win,
        "gross_loss": gross_loss,
    }


def scan(config, api, progress=None, coins=None):
    """粗筛排行榜 -> 精算胜率 -> 过滤 -> 按综合评分排序，返回收集列表。"""
    hunter = config.hunter
    rows = fetch_leaderboard(config.network, config.proxy_url)
    candidates = []
    for row in rows:
        address = str(row.get("ethAddress") or "").lower()
        if not address:
            continue
        account_value = _num(row.get("accountValue"))
        perf = _window_perf(row, "allTime")
        if account_value < hunter.min_account_value:
            continue
        if perf["vlm"] < hunter.min_volume:
            continue
        if perf["pnl"] < hunter.min_pnl:
            continue
        if perf["roi"] < hunter.min_roi:
            continue
        candidates.append(
            {
                "address": address,
                "alias": str(row.get("displayName") or ""),
                "account_value": account_value,
                "volume": perf["vlm"],
                "pnl": perf["pnl"],
                "roi": perf["roi"],
            }
        )
    candidates.sort(key=lambda item: item["account_value"], reverse=True)
    candidates = candidates[: hunter.candidates]

    results = []
    for index, cand in enumerate(candidates, 1):
        if progress:
            progress(index, len(candidates), cand["address"])
        try:
            fills = api.user_fills(cand["address"]) or []
        except Exception:
            fills = []
        if coins:
            coin_set = {str(c).upper() for c in coins}
            fills = [
                fill
                for fill in fills
                if str(fill.get("coin") or "").upper() in coin_set
            ]
        stats = _fill_win_stats(fills)
        if stats["sample_size"] < 1:
            continue
        if stats["weighted_win_rate"] < hunter.min_win_rate:
            continue
        score = (
            stats["weighted_win_rate"]
            * (1.0 + max(cand["roi"], 0.0))
            * (1.0 + math.log10(1.0 + cand["volume"] / 1_000_000.0))
        )
        cand.update(stats)
        cand["score"] = score
        cand["scanned_at"] = int(time.time() * 1000)
        results.append(cand)

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[: hunter.top_n]


def format_hunt_results_html(results, title="大户扫描"):
    lines = [f"<b>🎯 {html.escape(title)} · {len(results)} 个</b>"]
    if not results:
        lines.append("当前没有符合条件的账户")
        return "\n".join(lines)
    lines.append("胜率=盈利笔数/平仓笔数 · 加权=按盈亏金额 · ROI=全时段本金收益率")
    for index, item in enumerate(results, 1):
        pf = item.get("profit_factor")
        pf_text = "∞" if pf == float("inf") else f"{pf:.2f}"
        label = item.get("alias") or short_addr(item["address"])
        body = "\n".join(
            html.escape(line)
            for line in [
                f"地址: {item['address']}",
                f"净值: {fmt_usd_cn(item['account_value'])} · 全时段成交: {fmt_usd_cn(item['volume'])}",
                f"盈亏: {_fmt_pnl(item['pnl'])} · ROI: {item['roi'] * 100:.2f}%",
                f"胜率: {item['win_rate'] * 100:.1f}% · 加权胜率: {item['weighted_win_rate'] * 100:.1f}% · 盈亏因子: {pf_text}",
                f"样本: {item['sample_size']} 笔平仓 · 评分: {item['score']:.3f}",
            ]
        )
        lines.append("")
        lines.append(
            f"<b>{index}. {html.escape(label)}</b>\n"
            f"<blockquote expandable>{body}</blockquote>"
        )
    return "\n".join(lines)


SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(values, width=32):
    """把累计盈亏画成一行 sparkline（单行渲染，兼容各客户端）。"""
    if not values:
        return ""
    values = [v for v in values if v is not None]
    if not values:
        return ""
    if len(values) > width:
        step = len(values) / width
        values = [
            values[min(int(i * step), len(values) - 1)]
            for i in range(width)
        ]
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span <= 1e-12:
        return SPARK_CHARS[3] * len(values)
    return "".join(
        SPARK_CHARS[
            max(
                0,
                min(
                    len(SPARK_CHARS) - 1,
                    int((v - lo) / span * (len(SPARK_CHARS) - 1) + 0.5),
                ),
            )
        ]
        for v in values
    )


_pnl_cache: dict[str, tuple[float, list]] = {}
_PNL_CACHE_TTL = 900.0


def fetch_pnl_history(api, address, retries=4):
    """取全时段累计盈亏曲线（portfolio 接口的 pnlHistory），带限流重试与缓存。"""
    key = str(address).lower()
    now = time.time()
    with _cache_lock:
        cached = _pnl_cache.get(key)
        if cached and now - cached[0] < _PNL_CACHE_TTL:
            return cached[1]
    portfolio = None
    for attempt in range(retries):
        try:
            portfolio = api.portfolio(address)
            break
        except Exception as exc:
            if attempt >= retries - 1:
                print(f"[hunter] portfolio 拉取失败 ({short_addr(address)}): {exc}")
                break
            time.sleep(1.5 * (attempt + 1))
    out = []
    if isinstance(portfolio, list):
        for item in portfolio:
            if (
                isinstance(item, list)
                and len(item) == 2
                and item[0] == "allTime"
                and isinstance(item[1], dict)
            ):
                for entry in item[1].get("pnlHistory") or []:
                    try:
                        out.append((_num(entry[0]), _num(entry[1])))
                    except (TypeError, IndexError, ValueError):
                        continue
                break
    if out:
        with _cache_lock:
            _pnl_cache[key] = (now, out)
    return out


def _max_drawdown(values):
    """从累计盈亏曲线算最大回撤（USD 与百分比），避免入金/出金干扰。"""
    peak = None
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    for v in values:
        if peak is None or v > peak:
            peak = v
        if peak is not None and peak > 0 and v < peak:
            dd_usd = peak - v
            dd_pct = dd_usd / peak * 100
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_usd = dd_usd
    return max_dd_usd, max_dd_pct


_leverage_cache: dict[str, tuple[float, float | None]] = {}
_LEVERAGE_CACHE_TTL = 900.0


def _avg_leverage(api, address):
    """拉持仓快照算平均杠杠：总名义仓位 ÷ 账户净值。"""
    key = str(address).lower()
    now = time.time()
    with _cache_lock:
        cached = _leverage_cache.get(key)
        if cached and now - cached[0] < _LEVERAGE_CACHE_TTL:
            return cached[1]
    state = None
    for attempt in range(3):
        try:
            state = api.clearinghouse_state(address)
            break
        except Exception as exc:
            if attempt >= 2:
                print(f"[hunter] 持仓拉取失败 ({short_addr(address)}): {exc}")
            else:
                time.sleep(1.0 * (attempt + 1))
    value = None
    if state is not None:
        ms = state.get("marginSummary") or {}
        equity = _num(ms.get("accountValue"))
        ntl = _num(ms.get("totalNtlPos"))
        if equity > 0:
            value = ntl / equity
    if value is not None:
        with _cache_lock:
            _leverage_cache[key] = (now, value)
    return value


def attach_charts(api, results, progress=None):
    """给最终结果附上盈利走势与最大回撤数据。"""
    for index, item in enumerate(results, 1):
        if progress:
            progress(index, len(results), item.get("address", ""))
        pnl_history = fetch_pnl_history(api, item.get("address", ""))
        item["pnl_history"] = pnl_history
        item["avg_leverage"] = _avg_leverage(api, item.get("address", ""))
        time.sleep(0.4)
        if pnl_history:
            values = [v for _, v in pnl_history]
            item["pnl_min"] = min(values)
            item["pnl_max"] = max(values)
            item["pnl_current"] = values[-1]
            dd_usd, dd_pct = _max_drawdown(values)
            item["max_drawdown_usd"] = dd_usd
            item["max_drawdown_pct"] = dd_pct
        else:
            item["pnl_min"] = None
            item["pnl_max"] = None
            item["pnl_current"] = None
            item["max_drawdown_usd"] = None
            item["max_drawdown_pct"] = None
    return results


def format_account_card_html(account, index, total, spark_width=32, table_style="bordered compact"):
    """单账户卡片：标题 + 走势图 + 对齐指标表 + 双引号等宽地址。"""
    address = str(account.get("address", ""))
    alias = str(account.get("alias") or "")
    header = f"<b>{index}/{total}"
    if alias:
        header += f" · {html.escape(alias)}"
    header += "</b>"
    lines = [header]

    history = account.get("pnl_history") or []
    if history:
        values = [v for _, v in history]
        spark = _sparkline(values, width=spark_width)
        if spark:
            lines.append(spark)

    equity = fmt_usd_cn(account.get("account_value", 0))
    lev = account.get("avg_leverage")
    lev_text = f"{lev:.1f}x" if lev is not None else "-"
    wwr = _num(account.get("weighted_win_rate"))
    sample = int(account.get("sample_size", 0) or 0)
    dd_pct = account.get("max_drawdown_pct")
    dd_text = f"{dd_pct:.1f}%" if dd_pct is not None else "-"
    score = account.get("score")
    score_text = f"{round(_num(score) * 100)}/100" if score is not None else "-"

    attrs = f" {table_style}" if table_style else ""
    mark = "<mark>"
    table = (
        f"<table{attrs}>"
        f"<tr><td>净值</td><td><b>{html.escape(equity)}</b></td>"
        f"<td>平均杠杠</td><td>{html.escape(lev_text)}</td></tr>"
        f"<tr><td>加权胜率</td><td>{wwr * 100:.1f}%</td>"
        f"<td>样本</td><td>{sample} 笔</td></tr>"
        f"<tr><td>{mark}最大回撤</mark></td><td>{mark}{html.escape(dd_text)}</mark></td>"
        f"<td>{mark}评分</mark></td><td>{mark}{html.escape(score_text)}</mark></td></tr>"
        f"</table>"
    )
    lines.append(table)
    lines.append(f'"<code>{html.escape(address)}</code>"')
    return "\n".join(lines)
