"""格式化与展示辅助函数。"""

from datetime import datetime, timedelta, timezone

CN_TZ = timezone(timedelta(hours=8), name="UTC+8")


def fmt_time(ms):
    """毫秒时间戳 -> UTC+8 时间字符串。"""
    if ms is None:
        return "-"
    try:
        return datetime.fromtimestamp(ms / 1000, tz=CN_TZ).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (OverflowError, OSError, ValueError):
        return str(ms)


def fmt_time_min(ms):
    """毫秒时间戳 -> UTC+8 时间字符串（精确到分钟）。"""
    if ms is None:
        return "-"
    try:
        return datetime.fromtimestamp(ms / 1000, tz=CN_TZ).strftime(
            "%m-%d %H:%M"
        )
    except (OverflowError, OSError, ValueError):
        return str(ms)


def fmt_usd(x, decimals=2):
    try:
        return f"{float(x):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(x)


# 金额显示风格：cn=万/千万/亿，compact=K/M/B，full=完整数字。
AMOUNT_STYLES = ("cn", "compact", "full")
DEFAULT_AMOUNT_STYLE = "cn"
_amount_style = DEFAULT_AMOUNT_STYLE


def set_amount_style(style):
    """设置全局金额风格（Web 设置会调用；其余进程保持默认）。"""
    global _amount_style
    text = str(style or "").strip().lower()
    _amount_style = text if text in AMOUNT_STYLES else DEFAULT_AMOUNT_STYLE
    return _amount_style


def get_amount_style():
    return _amount_style


def fmt_usd_cn(x, decimals=2):
    """把 USD 金额压缩成 万/千万/百万/亿 这类中文单位。"""
    try:
        value = float(x)
    except (TypeError, ValueError):
        return str(x)

    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    if magnitude >= 100_000_000:
        return f"{sign}${magnitude / 100_000_000:,.{decimals}f}亿"
    if magnitude >= 10_000_000:
        return f"{sign}${magnitude / 10_000_000:,.{decimals}f}千万"
    if magnitude >= 1_000_000:
        return f"{sign}${magnitude / 1_000_000:,.{decimals}f}百万"
    if magnitude >= 10_000:
        return f"{sign}${magnitude / 10_000:,.{decimals}f}万"
    return f"{sign}${magnitude:,.{decimals}f}"


def fmt_usd_compact(x, decimals=2):
    """英文紧凑写法：K / M / B。"""
    try:
        value = float(x)
    except (TypeError, ValueError):
        return str(x)

    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    if magnitude >= 1_000_000_000:
        return f"{sign}${magnitude / 1_000_000_000:,.{decimals}f}B"
    if magnitude >= 1_000_000:
        return f"{sign}${magnitude / 1_000_000:,.{decimals}f}M"
    if magnitude >= 1_000:
        return f"{sign}${magnitude / 1_000:,.{decimals}f}K"
    return f"{sign}${magnitude:,.{decimals}f}"


def fmt_usd_full(x, decimals=2):
    """完整数字，例如 $12,345,678.90。"""
    try:
        value = float(x)
    except (TypeError, ValueError):
        return str(x)
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.{decimals}f}"


def fmt_usd_amount(x, decimals=2):
    """按当前金额风格格式化；所有对外展示金额都应走这里。"""
    if _amount_style == "compact":
        return fmt_usd_compact(x, decimals)
    if _amount_style == "full":
        return fmt_usd_full(x, decimals)
    return fmt_usd_cn(x, decimals)


def fmt_qty(x, decimals=2):
    """数量显示：大额保留 2 位小数，小额自动保留更多精度。"""
    try:
        value = float(x)
    except (TypeError, ValueError):
        return str(x)

    if value == 0:
        return "0"
    if abs(value) >= 1:
        text = f"{value:,.{decimals}f}"
    elif abs(value) >= 0.01:
        text = f"{value:,.4f}"
    else:
        text = f"{value:,.6f}"
    return text.rstrip("0").rstrip(".")


def short_addr(addr):
    addr = addr or ""
    if len(addr) > 12:
        return f"{addr[:6]}...{addr[-4:]}"
    return addr


def fmt_szi(szi):
    """仓位数量显示，保留最多 6 位有效小数。"""
    try:
        v = float(szi)
    except (TypeError, ValueError):
        return str(szi)
    if v == 0:
        return "0"
    return f"{v:,.6f}".rstrip("0").rstrip(".")


def fmt_side(side):
    return "买入" if str(side).upper() == "B" else "卖出"


DIR_CN = {
    "Open Long": "开多",
    "Close Long": "平多",
    "Open Short": "开空",
    "Close Short": "平空",
    "Long": "多单",
    "Short": "空单",
}


def fmt_dir(direction):
    return DIR_CN.get(direction, direction or "")
