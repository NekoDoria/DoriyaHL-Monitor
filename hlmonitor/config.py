"""Configuration loading and validation."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def normalize_address(value) -> str:
    if isinstance(value, bool):
        raise ValueError("address must be a string, not a boolean")
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"invalid Hyperliquid address: {value}")
        address = "0x" + format(value, "040x")
    elif isinstance(value, str):
        address = value.strip()
    elif value is None:
        address = ""
    else:
        raise ValueError(
            "address must be a string; if you wrote 0x... without quotes, "
            "TOML may have parsed it as an integer"
        )

    if address.startswith("0x") and not ADDRESS_RE.match(address):
        raise ValueError(f"invalid Hyperliquid address: {address}")
    if not address.startswith("0x") and re.fullmatch(r"[0-9a-fA-F]{40}", address):
        address = "0x" + address
    if not ADDRESS_RE.match(address):
        raise ValueError(f"invalid Hyperliquid address: {address}")
    return address.lower()


def normalize_addresses(values) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not values:
        return []
    out = []
    for value in values:
        out.append(normalize_address(value))
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(out))


@dataclass
class RuleConfig:
    account_value_change_pct: float = 1.0
    position_delta_min_usd: float = 0.0
    ignore_ws_snapshots: bool = True
    alert_funding: bool = True


@dataclass
class OrderConfig:
    """普通挂单密集区间的合并规则。"""

    base_gap_pct: float = 0.2      # 最低合并阈值（%）
    vol_multiplier: float = 1.5    # 阈值 = 币种典型小时波动 × 该倍数
    max_gap_pct: float = 2.0       # 合并阈值上限（%）
    vol_lookback_hours: int = 48   # 用最近多少小时的 1 小时 K 线估算波动
    width_multiplier: float = 3.0  # 单个区间最大宽度 = 合并阈值 × 该倍数
    ladder_min_orders: int = 5     # 至少多少笔才判定为均匀网格
    ladder_max_cv: float = 0.30    # 相邻间距变异系数低于该值判定为均匀网格


@dataclass
class HunterConfig:
    min_account_value: float = 500_000.0   # 账户净值下限（USD）
    min_volume: float = 10_000_000.0       # 全时段成交量下限（USD）
    min_pnl: float = 0.0                   # 全时段盈亏下限（USD）
    min_roi: float = 0.0                   # 全时段收益率下限
    min_win_rate: float = 0.50             # 加权胜率下限（0-1）
    swing_mode: bool = False               # 只留目前持大仓、拿得久且走出幅度的账户
    swing_min_position_usd: float = 50_000.0
    swing_min_move_pct: float = 1.5
    swing_min_funding_pct: float = 0.1
    auto_skip_hours: float = 12.0              # autohunt 跳过最近多少小时内已扫过的地址
    scan_workers: int = 6                    # autohunt/hunt 精算时并行拉取的线程数
    candidates: int = 150                  # 从合格账户中随机抽取精算的数量（不再按净值取前 N）
    top_n: int = 10                        # 最终收集数量


@dataclass
class WhaleConfig:
    """链上筹码集中度扫描与巨鲸地址监控。"""

    enabled: bool = True
    scan_limit: int = 50                 # 单次扫描抓取的持仓地址数量
    watch_interval_minutes: float = 10.0  # 监控地址余额轮询间隔（分钟）
    scan_interval_hours: float = 6.0      # 已订阅代币自动复扫间隔（小时）
    min_delta_pct: float = 2.0            # 余额变化告警阈值（百分比）
    min_delta_abs: float = 0.0            # 余额变化告警阈值（绝对数量）
    concentration_threshold: float = 3.0  # 集中度变化多少个百分点才告警
    solana_rpc: str = ""                  # Solana RPC；留空则不支持 Solana
    blockchair_url: str = "https://api.blockchair.com"
    blockchair_key: str = ""              # 可选，提高 Blockchair 额度
    blockchair_chains: list = field(default_factory=list)
    chain_urls: dict = field(default_factory=dict)   # chain -> 自定义 API 地址
    disabled_chains: list = field(default_factory=list)
    exclude_tags: list = field(default_factory=list)      # 额外排除的地址标签
    exclude_label_keywords: list = field(default_factory=list)  # 额外排除的地址名关键词
    exclude_addresses: list = field(default_factory=list)  # 手动排除的地址
    max_rows: int = 12                    # 扫描结果展示行数
    timeout: float = 25.0
    retries: int = 2


@dataclass
class Config:
    addresses: list[str] = field(default_factory=list)
    network: str = "mainnet"
    data_dir: str = "data"
    poll_interval: float = 30.0
    poll_on_start: bool = True
    ws_max_silence: float = 180.0
    position_sort: str = "value"
    proxy_url: str | None = None
    alerts: dict = field(default_factory=dict)
    rules: RuleConfig = field(default_factory=RuleConfig)
    order_merge: OrderConfig = field(default_factory=OrderConfig)
    hunter: HunterConfig = field(default_factory=HunterConfig)
    whales: WhaleConfig = field(default_factory=WhaleConfig)

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir).expanduser() / "hlmonitor.sqlite3"

    @property
    def info_url(self) -> str:
        return (
            "https://api.hyperliquid-testnet.xyz/info"
            if self.network == "testnet"
            else "https://api.hyperliquid.xyz/info"
        )

    @property
    def ws_url(self) -> str:
        return (
            "wss://api.hyperliquid-testnet.xyz/ws"
            if self.network == "testnet"
            else "wss://api.hyperliquid.xyz/ws"
        )


def _as_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value, default):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Load a TOML config, falling back to defaults when no file is supplied."""
    data: dict = {}
    if path:
        config_path = Path(path).expanduser()
        if not config_path.exists():
            raise FileNotFoundError(f"config file not found: {config_path}")
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)

    general = data.get("general", {})
    proxy = data.get("proxy", {})
    alerts = data.get("alerts", {})
    rules_data = data.get("rules", {})
    order_data = data.get("orders", {})

    addresses = normalize_addresses(general.get("addresses", []))
    network = str(general.get("network", "mainnet")).strip().lower()
    if network not in {"mainnet", "testnet"}:
        raise ValueError("general.network must be 'mainnet' or 'testnet'")

    proxy_enabled = _as_bool(proxy.get("enabled", False), False)
    proxy_url = str(proxy.get("url", "")).strip() if proxy_enabled else None
    if proxy_url == "":
        proxy_url = None

    rules = RuleConfig(
        account_value_change_pct=_as_float(
            rules_data.get("account_value_change_pct", 1.0), 1.0
        ),
        position_delta_min_usd=_as_float(
            rules_data.get("position_delta_min_usd", 0.0), 0.0
        ),
        ignore_ws_snapshots=_as_bool(
            rules_data.get("ignore_ws_snapshots", True), True
        ),
        alert_funding=_as_bool(rules_data.get("alert_funding", False), False),
    )

    order_merge = OrderConfig(
        base_gap_pct=max(0.0, _as_float(order_data.get("base_gap_pct", 0.2), 0.2)),
        vol_multiplier=max(0.0, _as_float(order_data.get("vol_multiplier", 1.5), 1.5)),
        max_gap_pct=max(0.0, _as_float(order_data.get("max_gap_pct", 2.0), 2.0)),
        vol_lookback_hours=max(
            6,
            _as_int(order_data.get("vol_lookback_hours", 48), 48),
        ),
        width_multiplier=max(
            1.0,
            _as_float(order_data.get("width_multiplier", 3.0), 3.0),
        ),
        ladder_min_orders=max(
            3,
            _as_int(order_data.get("ladder_min_orders", 5), 5),
        ),
        ladder_max_cv=max(
            0.05,
            _as_float(order_data.get("ladder_max_cv", 0.30), 0.30),
        ),
    )
    if order_merge.max_gap_pct < order_merge.base_gap_pct:
        order_merge.max_gap_pct = order_merge.base_gap_pct

    hunter_data = data.get("hunter", {})
    hunter = HunterConfig(
        min_account_value=max(
            0.0,
            _as_float(hunter_data.get("min_account_value", 500_000.0), 500_000.0),
        ),
        min_volume=max(
            0.0,
            _as_float(hunter_data.get("min_volume", 10_000_000.0), 10_000_000.0),
        ),
        min_pnl=_as_float(hunter_data.get("min_pnl", 0.0), 0.0),
        min_roi=_as_float(hunter_data.get("min_roi", 0.0), 0.0),
        min_win_rate=min(
            1.0,
            max(0.0, _as_float(hunter_data.get("min_win_rate", 0.50), 0.50)),
        ),
        swing_mode=_as_bool(hunter_data.get("swing_mode", False), False),
        swing_min_position_usd=max(
            0.0, _as_float(hunter_data.get("swing_min_position_usd", 50_000.0), 50_000.0)
        ),
        swing_min_move_pct=max(
            0.0, _as_float(hunter_data.get("swing_min_move_pct", 1.5), 1.5)
        ),
        swing_min_funding_pct=max(
            0.0, _as_float(hunter_data.get("swing_min_funding_pct", 0.1), 0.1)
        ),
        auto_skip_hours=max(
            0.5, _as_float(hunter_data.get("auto_skip_hours", 12.0), 12.0)
        ),
        scan_workers=max(1, min(32, _as_int(hunter_data.get("scan_workers", 6), 6))),
        candidates=max(1, _as_int(hunter_data.get("candidates", 150), 150)),
        top_n=max(1, _as_int(hunter_data.get("top_n", 10), 10)),
    )

    whales_data = data.get("whales", {})
    blockchair_chains = [
        str(item).lower() for item in _as_list(whales_data.get("blockchair_chains"))
    ]
    chain_urls = {
        str(key).lower(): str(value).strip()
        for key, value in (whales_data.get("chain_urls") or {}).items()
        if str(value).strip()
    }
    whales = WhaleConfig(
        enabled=_as_bool(whales_data.get("enabled", True), True),
        scan_limit=max(5, min(200, _as_int(whales_data.get("scan_limit", 50), 50))),
        watch_interval_minutes=max(
            1.0,
            _as_float(
                whales_data.get("watch_interval_minutes", 10.0), 10.0
            ),
        ),
        scan_interval_hours=max(
            0.25,
            _as_float(whales_data.get("scan_interval_hours", 6.0), 6.0),
        ),
        min_delta_pct=max(
            0.0, _as_float(whales_data.get("min_delta_pct", 2.0), 2.0)
        ),
        min_delta_abs=max(
            0.0, _as_float(whales_data.get("min_delta_abs", 0.0), 0.0)
        ),
        concentration_threshold=max(
            0.1,
            _as_float(whales_data.get("concentration_threshold", 3.0), 3.0),
        ),
        solana_rpc=str(whales_data.get("solana_rpc", "") or "").strip(),
        blockchair_url=(
            str(whales_data.get("blockchair_url", "") or "").strip()
            or "https://api.blockchair.com"
        ),
        blockchair_key=str(whales_data.get("blockchair_key", "") or "").strip(),
        blockchair_chains=blockchair_chains,
        chain_urls=chain_urls,
        disabled_chains=[
            str(item).lower()
            for item in _as_list(whales_data.get("disabled_chains"))
        ],
        exclude_tags=[
            str(item).lower()
            for item in _as_list(whales_data.get("exclude_tags"))
        ],
        exclude_label_keywords=[
            str(item).lower()
            for item in _as_list(whales_data.get("exclude_label_keywords"))
        ],
        exclude_addresses=[
            str(item) for item in _as_list(whales_data.get("exclude_addresses"))
        ],
        max_rows=max(3, min(50, _as_int(whales_data.get("max_rows", 12), 12))),
        timeout=max(5.0, _as_float(whales_data.get("timeout", 25.0), 25.0)),
        retries=max(0, min(5, _as_int(whales_data.get("retries", 2), 2))),
    )

    return Config(
        addresses=addresses,
        network=network,
        data_dir=str(general.get("data_dir", "data")),
        poll_interval=max(1.0, _as_float(general.get("poll_interval", 30.0), 30.0)),
        poll_on_start=_as_bool(general.get("poll_on_start", True), True),
        ws_max_silence=max(1.0, _as_float(general.get("ws_max_silence", 180.0), 180.0)),
        position_sort=str(general.get("position_sort", "value")).strip().lower()
        if str(general.get("position_sort", "value")).strip().lower() in {"value", "time"}
        else "value",
        proxy_url=proxy_url,
        alerts=alerts,
        rules=rules,
        order_merge=order_merge,
        hunter=hunter,
        whales=whales,
    )
