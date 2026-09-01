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
    )
