"""多链筹码集中度扫描与巨鲸地址监控。

数据源（均可在 config.toml 的 [whales] 节调整）：

- EVM：Blockscout v2 API，免费免密钥，并自带交易所/跨链桥/协议标签
- UTXO（BTC/ZEC/LTC/DOGE/DASH）：Blockchair，免费免密钥但有频率限制
- Solana：JSON-RPC，需要允许 getTokenLargestAccounts 的 RPC 服务

像 HyperEVM 这类没有免费持仓榜的链只支持余额监控，不支持持仓榜扫描。
"""

from __future__ import annotations

import html
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .format import fmt_time
from .net import build_opener

__all__ = [
    "BLOCKSCOUT_CHAINS",
    "BLOCKCHAIR_CHAINS",
    "EVM_RPC_CHAINS",
    "DEFAULT_EXCLUDE_TAGS",
    "DEFAULT_EXCLUDE_LABEL_KEYWORDS",
    "DataSourceError",
    "Holder",
    "TokenMeta",
    "ConcentrationReport",
    "BlockscoutAdapter",
    "SolanaRpcAdapter",
    "BlockchairAdapter",
    "EvmRpcAdapter",
    "build_adapters",
    "scan_token",
    "search_tokens",
    "parse_config_labels",
    "is_exchange_label",
    "resolve_token",
    "rank_token_candidates",
    "TokenResolution",
    "concentration_score",
    "format_scan_html",
    "format_watchlist_html",
    "describe_chains",
    "split_ref",
    "addr_key",
    "WhaleAlert",
    "WhaleWatcher",
]

BALANCE_OF_SELECTOR = "0x70a08231"
NATIVE_ALIASES = {"native", "coin", "gas", "", "-"}

# Blockscout v2 API：免费、免密钥，同时返回持仓榜和地址标签。
BLOCKSCOUT_CHAINS = {
    "ethereum": ("Ethereum", "https://eth.blockscout.com", 1),
    "base": ("Base", "https://base.blockscout.com", 8453),
    "arbitrum": ("Arbitrum One", "https://arbitrum.blockscout.com", 42161),
    "optimism": ("OP Mainnet", "https://explorer.optimism.io", 10),
    "polygon": ("Polygon", "https://polygon.blockscout.com", 137),
    "gnosis": ("Gnosis", "https://gnosisscan.io", 100),
    "scroll": ("Scroll", "https://scrollscan.com", 534352),
    "zksync": ("zkSync Era", "https://zksync.blockscout.com", 324),
    "celo": ("Celo", "https://celo.blockscout.com", 42220),
}

# Blockchair 支持的 UTXO 链（地址 -> (名称, 符号, 最小单位位数)）。
BLOCKCHAIR_CHAINS = {
    "bitcoin": ("Bitcoin", "BTC", 8),
    "zcash": ("Zcash", "ZEC", 8),
    "litecoin": ("Litecoin", "LTC", 8),
    "dogecoin": ("Dogecoin", "DOGE", 8),
    "dash": ("Dash", "DASH", 8),
}

# 只提供 JSON-RPC 余额查询、没有免费持仓榜的 EVM 链。
EVM_RPC_CHAINS = {
    "hyperevm": ("HyperEVM", "https://rpc.hyperliquid.xyz/evm", 999),
}

# Blockscout 的 generic 标签里，这些类别代表多人共用地址或基础设施地址，
# 不算个人大户；计算单地址集中度时默认剔除。
DEFAULT_EXCLUDE_TAGS = (
    "exchange",
    "cex",
    "bridge",
    "dex",
    "lending",
    "staking",
    "custody",
    "gambling",
    "payment",
)

# 名称里出现这些词就当成交易所，用来判断资金是进所还是出所。
EXCHANGE_LABEL_KEYWORDS = (
    "binance",
    "coinbase",
    "okx",
    "kraken",
    "bybit",
    "bitfinex",
    "kucoin",
    "gate.io",
    "gateio",
    "huobi",
    "htx",
    "gemini",
    "crypto.com",
    "upbit",
    "bithumb",
    "robinhood",
    "bitstamp",
    "poloniex",
    "mexc",
    "bitget",
    "exchange",
    "交易所",
)

# 有些交易所钱包在 Blockscout 上只有名称标签、没有 exchange 分类标签，
# 这里再用名称关键词兜底识别，避免把交易所冷热钱包当成个人大户。
DEFAULT_EXCLUDE_LABEL_KEYWORDS = (
    "binance",
    "coinbase",
    "okx",
    "kraken",
    "bybit",
    "bitfinex",
    "kucoin",
    "gate.io",
    "gateio",
    "huobi",
    "htx",
    "gemini",
    "crypto.com",
    "upbit",
    "bithumb",
    "robinhood",
    "bitstamp",
    "poloniex",
    "mexc",
    "bitget",
    "exchange",
    "hot wallet",
    "cold wallet",
    "bridge",
    "custody",
)

# 代理合约的 name 字段往往只是代理类型名，对识别持仓方没有帮助。
GENERIC_PROXY_LABELS = {
    "ERC1967Proxy",
    "Proxy",
    "TransparentUpgradeableProxy",
    "AdminUpgradeabilityProxy",
    "BeaconProxy",
    "UUPSProxy",
    "DiamondProxy",
}


# 各链原生币的常见写法。用户手填 "HYPE"/"SOL" 时不应该被当成合约地址。
NATIVE_SYMBOLS = {
    "ethereum": ("ETH",),
    "base": ("ETH",),
    "arbitrum": ("ETH",),
    "optimism": ("ETH",),
    "scroll": ("ETH",),
    "zksync": ("ETH",),
    "polygon": ("POL", "MATIC"),
    "gnosis": ("XDAI", "GNO"),
    "celo": ("CELO",),
    "hyperevm": ("HYPE",),
    "solana": ("SOL",),
    "bitcoin": ("BTC",),
    "zcash": ("ZEC",),
    "litecoin": ("LTC",),
    "dogecoin": ("DOGE",),
    "dash": ("DASH",),
}


BURN_ADDRESSES = {
    "0x0000000000000000000000000000000000000000",
    "0x0000000000000000000000000000000000000001",
    "0x000000000000000000000000000000000000dead",
}


class DataSourceError(RuntimeError):
    """数据源不可用、被限流，或返回了无法解析的内容。"""


def addr_key(chain, address):
    """地址归一化：EVM 系不区分大小写，Solana/UTXO 保持原样。"""
    text = str(address or "").strip()
    if str(chain or "").lower() in BLOCKCHAIR_CHAINS or str(chain or "").lower() == "solana":
        return text
    return text.lower()


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_iso_ms(value):
    """把 ISO 时间串转成毫秒时间戳；解析不了返回 0。"""
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        cleaned = text.replace("Z", "+00:00").replace(" ", "T", 1)
        return int(datetime.fromisoformat(cleaned).timestamp() * 1000)
    except (ValueError, TypeError, OSError):
        return 0


def is_exchange_label(label, category=""):
    """判断某个地址是不是交易所。

    先看分类标签（Blockscout 的 generic tag，如 exchange / cex），
    再退回名称关键词，因为不少交易所钱包只有名称标签。
    """
    tags = str(category or "").lower()
    if "exchange" in tags or "cex" in tags:
        return True
    name = str(label or "").lower()
    if not name:
        return False
    return any(word in name for word in EXCHANGE_LABEL_KEYWORDS)


def parse_config_labels(mapping):
    """把 config 里 "链:地址" = "标签" 的写法解析成标签条目。"""
    out = []
    for key, value in (mapping or {}).items():
        chain, address = split_ref(key)
        if not chain or not address or address == "native":
            continue
        out.append(
            {
                "chain": chain,
                "address": address,
                "label": str(value),
                "category": "exchange" if is_exchange_label(value, "") else "",
                "source": "config",
            }
        )
    return out


def is_native_token(chain, token):
    """判断代币参数是否指本链原生币（native/coin/gas 或本链符号）。"""
    text = str(token or "").strip().lower()
    if text in NATIVE_ALIASES:
        return True
    return text in {item.lower() for item in NATIVE_SYMBOLS.get(str(chain or "").lower(), ())}


def is_hex_address(value):
    text = str(value or "").strip()
    if len(text) != 42 or not text.lower().startswith("0x"):
        return False
    try:
        int(text[2:], 16)
    except ValueError:
        return False
    return True


def _error_text(exc):
    """把异常转成可读原因。

    DataSourceError 的文案本身就是给人看的，直接用；
    其他异常一律带上类型名，避免只看到 "'token'" 这类莫名信息。
    """
    message = str(exc).strip() or exc.__class__.__name__
    if isinstance(exc, DataSourceError):
        return message
    return f"{exc.__class__.__name__}: {message}"


def raw_to_units(raw, decimals):
    """把最小单位整数精确换算成人类可读数量。"""
    try:
        scale = Decimal(10) ** int(decimals)
        return float(Decimal(str(raw)) / scale)
    except (InvalidOperation, ValueError, TypeError):
        return 0.0


def split_ref(text):
    """把 ``chain:token`` 拆成 (chain, token)；没有冒号时 token 取 native。"""
    body = str(text or "").strip()
    if ":" not in body:
        return body.lower(), "native"
    chain, token = body.split(":", 1)
    return chain.strip().lower(), token.strip()


def _http_error_message(exc, body):
    # Blockchair 超限时返回 HTTP 430，响应体是一大段 JSON，直接透出很难读。
    if exc.code == 430:
        return (
            "Blockchair 限流（HTTP 430）：该出口 IP 被临时拉黑。"
            "可在 [whales] 配置 blockchair_key，或降低扫描频率、等几分钟再试"
        )
    if exc.code == 429:
        return (
            "数据源限流（HTTP 429）：短时间内请求过多，稍后会自动恢复。"
            "可以把 [whales] 的 watch_interval_minutes 调大以降低请求频率"
        )
    detail = ""
    if body:
        try:
            detail = body.decode("utf-8", "replace")[:200].strip()
        except Exception:
            detail = ""
    base = f"HTTP {exc.code} {exc.reason}"
    return f"{base}: {detail}" if detail else base


class HttpClient:
    """带重试与退避的 JSON 客户端，复用项目已有的代理配置。"""

    def __init__(self, proxy_url=None, timeout=25.0, retries=2):
        self.opener = build_opener(proxy_url)
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))

    def _fetch(self, build_request):
        """build_request 每次调用都要返回全新的 Request。

        urllib 的 ProxyHandler 会原地改写 Request（把 scheme 标记成 socks5），
        复用同一个对象重试时第二次会直接报 “unknown url type: socks5”，
        把真正的原因盖掉，所以这里每轮都重建。
        """
        last_error = None
        for attempt in range(self.retries + 1):
            req = build_request()
            try:
                with self.opener.open(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read()
                except Exception:
                    body = b""
                last_error = DataSourceError(_http_error_message(exc, body))
                if exc.code in (408, 425, 429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise last_error
            except urllib.error.URLError as exc:
                last_error = DataSourceError(f"网络错误: {exc.reason}")
                if attempt < self.retries:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise last_error
            except Exception as exc:
                raise DataSourceError(f"请求失败: {exc}") from exc
        raise last_error or DataSourceError("请求失败")

    def _headers(self, extra=None):
        headers = {
            "Accept": "application/json",
            "User-Agent": "hlmonitor-whale/1.0",
        }
        if extra:
            headers.update(extra)
        return headers

    def get_json(self, url, params=None, headers=None):
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}{urllib.parse.urlencode(clean)}"
        def build_request():
            return urllib.request.Request(url, headers=self._headers(headers))

        payload = self._fetch(build_request)
        try:
            return json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise DataSourceError(f"返回内容不是合法 JSON: {exc}") from exc

    def post_json(self, url, body, headers=None):
        data = json.dumps(body).encode("utf-8")
        extra = {"Content-Type": "application/json"}
        if headers:
            extra.update(headers)
        def build_request():
            return urllib.request.Request(
                url, data=data, headers=self._headers(extra), method="POST"
            )

        payload = self._fetch(build_request)
        try:
            result = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise DataSourceError(f"返回内容不是合法 JSON: {exc}") from exc
        if isinstance(result, dict) and result.get("error"):
            err = result["error"]
            if isinstance(err, dict):
                raise DataSourceError(str(err.get("message") or err))
            raise DataSourceError(str(err))
        return result


@dataclass
class Holder:
    """单个持仓地址。"""

    address: str
    balance: float = 0.0
    pct: float = 0.0
    rank: int = 0
    is_contract: bool = False
    label: str = ""
    tags: tuple = ()
    excluded: bool = False
    exclude_reason: str = ""


@dataclass
class TokenMeta:
    symbol: str = ""
    name: str = ""
    decimals: int = 18
    supply: float = 0.0
    holder_count: int = 0
    kind: str = "erc20"
    price_usd: float = 0.0


@dataclass
class ConcentrationReport:
    """一次集中度扫描的结果。"""

    chain: str
    token: str
    symbol: str = ""
    name: str = ""
    decimals: int = 18
    supply: float = 0.0
    holder_count: int = 0
    price_usd: float = 0.0
    holders: list = field(default_factory=list)
    top1_pct: float = 0.0
    top5_pct: float = 0.0
    top10_pct: float = 0.0
    whale_pct: float = 0.0
    whale10_pct: float = 0.0
    whale_address: str = ""
    whale_label: str = ""
    score: float = 0.0
    scanned_ms: int = 0
    error: str = ""

    def to_dict(self):
        return {
            "chain": self.chain,
            "token": self.token,
            "symbol": self.symbol,
            "name": self.name,
            "decimals": self.decimals,
            "supply": self.supply,
            "holder_count": self.holder_count,
            "price_usd": self.price_usd,
            "holders": [
                {
                    "address": h.address,
                    "balance": h.balance,
                    "pct": h.pct,
                    "rank": h.rank,
                    "is_contract": h.is_contract,
                    "label": h.label,
                    "tags": list(h.tags),
                    "excluded": h.excluded,
                    "exclude_reason": h.exclude_reason,
                }
                for h in self.holders
            ],
            "top1_pct": self.top1_pct,
            "top5_pct": self.top5_pct,
            "top10_pct": self.top10_pct,
            "whale_pct": self.whale_pct,
            "whale10_pct": self.whale10_pct,
            "whale_address": self.whale_address,
            "whale_label": self.whale_label,
            "score": self.score,
            "scanned_ms": self.scanned_ms,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data):
        holders = [
            Holder(
                address=item.get("address", ""),
                balance=_as_float(item.get("balance")),
                pct=_as_float(item.get("pct")),
                rank=int(item.get("rank") or 0),
                is_contract=bool(item.get("is_contract")),
                label=str(item.get("label") or ""),
                tags=tuple(item.get("tags") or ()),
                excluded=bool(item.get("excluded")),
                exclude_reason=str(item.get("exclude_reason") or ""),
            )
            for item in (data.get("holders") or [])
        ]
        return cls(
            chain=str(data.get("chain") or ""),
            token=str(data.get("token") or ""),
            symbol=str(data.get("symbol") or ""),
            name=str(data.get("name") or ""),
            decimals=int(data.get("decimals") or 18),
            supply=_as_float(data.get("supply")),
            holder_count=int(data.get("holder_count") or 0),
            price_usd=_as_float(data.get("price_usd")),
            holders=holders,
            top1_pct=_as_float(data.get("top1_pct")),
            top5_pct=_as_float(data.get("top5_pct")),
            top10_pct=_as_float(data.get("top10_pct")),
            whale_pct=_as_float(data.get("whale_pct")),
            whale10_pct=_as_float(data.get("whale10_pct")),
            whale_address=str(data.get("whale_address") or ""),
            whale_label=str(data.get("whale_label") or ""),
            score=_as_float(data.get("score")),
            scanned_ms=int(data.get("scanned_ms") or 0),
            error=str(data.get("error") or ""),
        )

class ChainAdapter:
    """链适配器基类。"""

    kind = "generic"

    def __init__(self, chain, name, client):
        self.chain = chain
        self.name = name
        self.client = client
        self._meta_cache = {}

    def supports_scan(self):
        """是否支持持仓榜扫描（余额监控不受影响）。"""
        return True

    def supports_search(self):
        """是否支持按符号模糊检索合约地址。"""
        return False

    def supports_transactions(self):
        """是否支持拉取该地址的链上成交明细。"""
        return False

    def fetch_transactions(self, token, address, limit=20):
        raise DataSourceError(f"{self.name} 暂不支持成交监控")

    def search_tokens(self, query, limit=10):
        return []

    def fetch_token_meta(self, token):
        raise NotImplementedError

    def fetch_top_holders(self, token, limit=50, decimals=None):
        raise NotImplementedError

    def fetch_balance(self, token, address, decimals=None):
        raise NotImplementedError

    def token_url(self, token):
        return ""

    def address_url(self, token, address):
        return ""


def _hex_to_int(value):
    text = str(value or "").strip()
    if not text or text == "0x":
        return 0
    try:
        return int(text, 16)
    except ValueError:
        return 0


class BlockscoutAdapter(ChainAdapter):
    """Blockscout v2 API：EVM 持仓榜，并附带交易所/跨链桥/协议标签。"""

    kind = "evm"
    PAGE_SIZE = 50

    def __init__(self, chain, name, base_url, chain_id, client):
        super().__init__(chain, name, client)
        self.base_url = str(base_url).rstrip("/")
        self.chain_id = int(chain_id)

    def supports_search(self):
        return True

    def search_tokens(self, query, limit=10):
        text = str(query or "").strip()
        if len(text) < 2:
            return []
        data = self.client.get_json(
            f"{self.base_url}/api/v2/search", params={"q": text}
        )
        items = (data or {}).get("items") or []
        return rank_token_candidates(text, items, self.chain, limit=limit)

    def supports_transactions(self):
        return True

    def fetch_transactions(self, token, address, limit=20):
        limit = max(1, min(50, int(limit)))
        if is_native_token(self.chain, token):
            return self._native_transactions(address, limit)
        return self._token_transfers(token, address, limit)

    @staticmethod
    def _address_label(obj):
        """从 Blockscout 的地址对象里取展示名和标签类别。

        成交接口的 from/to 会带 metadata.tags，所以标签是随成交免费拿到的，
        不需要为每个对手方再发一次请求。
        """
        if not isinstance(obj, dict):
            return "", ()
        name_tag = ""
        protocol_tag = ""
        tags = []
        for tag in ((obj.get("metadata") or {}).get("tags") or []):
            if not isinstance(tag, dict):
                continue
            tag_type = str(tag.get("tagType") or "")
            tag_name = str(tag.get("name") or "")
            slug = str(tag.get("slug") or "")
            if tag_type == "name" and tag_name and not name_tag:
                name_tag = tag_name
            elif tag_type == "protocol" and tag_name and not protocol_tag:
                protocol_tag = tag_name
            if tag_type == "generic" and slug:
                tags.append(slug.lower())
        label = name_tag or str(obj.get("name") or "") or protocol_tag
        return label, tuple(dict.fromkeys(tags))

    def _tx_row(self, address, sender_obj, receiver_obj, value, asset, item):
        sender = str((sender_obj or {}).get("hash") or "")
        receiver = str((receiver_obj or {}).get("hash") or "")
        me = str(address).lower()
        outgoing = sender.lower() == me
        incoming = receiver.lower() == me
        if outgoing and incoming:
            direction = "self"
        elif outgoing:
            direction = "out"
        else:
            direction = "in"
        tx_hash = str(item.get("transaction_hash") or item.get("hash") or "")
        sender_label, sender_tags = self._address_label(sender_obj)
        receiver_label, receiver_tags = self._address_label(receiver_obj)
        return {
            "hash": tx_hash,
            "time_ms": _parse_iso_ms(item.get("timestamp")),
            "direction": direction,
            "counterparty": receiver if outgoing else sender,
            "value": value,
            "asset": asset,
            "url": f"{self.base_url}/tx/{tx_hash}" if tx_hash else "",
            "sender": sender,
            "receiver": receiver,
            "sender_label": sender_label,
            "sender_tags": sender_tags,
            "receiver_label": receiver_label,
            "receiver_tags": receiver_tags,
        }

    def _token_transfers(self, token, address, limit):
        data = self.client.get_json(
            f"{self.base_url}/api/v2/addresses/{address}/token-transfers",
            params={"items_count": limit},
        )
        wanted = str(token).lower()
        rows = []
        for item in (data or {}).get("items") or []:
            info = item.get("token") or {}
            if str(info.get("address_hash") or "").lower() != wanted:
                continue
            total = item.get("total") or {}
            decimals = int(
                _as_float(total.get("decimals"), _as_float(info.get("decimals"), 18)) or 18
            )
            rows.append(
                self._tx_row(
                    address,
                    item.get("from") or {},
                    item.get("to") or {},
                    raw_to_units(total.get("value") or 0, decimals),
                    str(info.get("symbol") or token),
                    item,
                )
            )
        return rows

    def _native_transactions(self, address, limit):
        data = self.client.get_json(
            f"{self.base_url}/api/v2/addresses/{address}/transactions",
            params={"items_count": limit},
        )
        symbols = NATIVE_SYMBOLS.get(self.chain) or (self.name,)
        rows = []
        for item in (data or {}).get("items") or []:
            value = raw_to_units(item.get("value") or 0, 18)
            # 原生币的 0 值交易基本都是合约调用，不算成交。
            if value <= 0:
                continue
            rows.append(
                self._tx_row(
                    address,
                    item.get("from") or {},
                    item.get("to") or {},
                    value,
                    symbols[0],
                    item,
                )
            )
        return rows

    def token_url(self, token):
        return f"{self.base_url}/token/{token}"

    def address_url(self, token, address):
        return f"{self.base_url}/address/{address}"

    def fetch_token_meta(self, token):
        key = str(token).lower()
        cached = self._meta_cache.get(key)
        if cached is not None:
            return cached
        if is_native_token(self.chain, token):
            meta = TokenMeta(
                symbol=self.name,
                name=self.name,
                decimals=18,
                kind="native",
            )
            self._meta_cache[key] = meta
            return meta
        data = self.client.get_json(f"{self.base_url}/api/v2/tokens/{token}")
        if not isinstance(data, dict):
            raise DataSourceError("Blockscout 返回了非预期的代币数据")
        decimals = int(_as_float(data.get("decimals"), 18) or 18)
        meta = TokenMeta(
            symbol=str(data.get("symbol") or ""),
            name=str(data.get("name") or ""),
            decimals=decimals,
            supply=raw_to_units(data.get("total_supply") or 0, decimals),
            holder_count=int(_as_float(data.get("holders_count"), 0)),
            kind=str(data.get("type") or "erc20").lower(),
            price_usd=_as_float(data.get("exchange_rate")),
        )
        self._meta_cache[key] = meta
        return meta

    @staticmethod
    def _parse_holder(item, decimals):
        addr = item.get("address")
        implementations = []
        if isinstance(addr, dict):
            address = str(addr.get("hash") or "")
            is_contract = bool(addr.get("is_contract"))
            metadata = addr.get("metadata") or {}
            raw_tags = metadata.get("tags") or []
            implementations = addr.get("implementations") or []
            label = str(addr.get("name") or addr.get("ens_domain_name") or "")
        else:
            address = str(addr or "")
            is_contract = False
            raw_tags = []
            label = ""
        if not address:
            return None

        tags = []
        name_tag = ""
        protocol_tag = ""
        for tag in raw_tags:
            if not isinstance(tag, dict):
                continue
            tag_type = str(tag.get("tagType") or "")
            tag_name = str(tag.get("name") or "")
            slug = str(tag.get("slug") or "")
            if tag_type == "name" and tag_name and not name_tag:
                name_tag = tag_name
            elif tag_type == "protocol" and tag_name and not protocol_tag:
                protocol_tag = tag_name
            if tag_type == "generic" and slug:
                tags.append(slug.lower())

        # 名称标签比合约类型名（如 ERC1967Proxy）更有信息量，优先使用。
        label = name_tag or label or protocol_tag
        if label in GENERIC_PROXY_LABELS and implementations:
            first = implementations[0]
            if isinstance(first, dict):
                impl_name = str(first.get("name") or "")
                if impl_name:
                    label = impl_name

        return Holder(
            address=address,
            balance=raw_to_units(item.get("value") or 0, decimals),
            is_contract=is_contract,
            label=label,
            tags=tuple(dict.fromkeys(tags)),
        )

    def fetch_top_holders(self, token, limit=50, decimals=None):
        if is_native_token(self.chain, token):
            raise DataSourceError(
                f"{self.name} 原生币没有持仓榜接口，只能监控已知地址的余额"
            )
        limit = max(1, int(limit))
        if decimals is None:
            decimals = self.fetch_token_meta(token).decimals
        holders = []
        params = {"items_count": self.PAGE_SIZE}
        pages = max(1, (limit + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        for _ in range(pages):
            url = f"{self.base_url}/api/v2/tokens/{token}/holders"
            data = self.client.get_json(url, params=params)
            if not isinstance(data, dict):
                raise DataSourceError("Blockscout 返回了非预期的持仓数据")
            for item in data.get("items") or []:
                holder = self._parse_holder(item, decimals)
                if holder is not None:
                    holders.append(holder)
                if len(holders) >= limit:
                    break
            if len(holders) >= limit:
                break
            next_params = data.get("next_page_params")
            if not next_params:
                break
            params = dict(next_params)
        return holders[:limit]

    def _rpc(self, method, params):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            data = self.client.post_json(f"{self.base_url}/api/eth-rpc", body)
        except DataSourceError as exc:
            raise DataSourceError(f"{self.name} RPC {method} 失败: {exc}") from exc
        if not isinstance(data, dict) or "result" not in data:
            raise DataSourceError(f"{self.name} RPC {method} 返回异常: {data}")
        return data.get("result")

    def fetch_balance(self, token, address, decimals=None):
        if is_native_token(self.chain, token):
            return raw_to_units(_hex_to_int(self._rpc("eth_getBalance", [address, "latest"])), 18)
        if decimals is None:
            decimals = self.fetch_token_meta(token).decimals
        body = str(address)
        if body.lower().startswith("0x"):
            body = body[2:]
        call_data = BALANCE_OF_SELECTOR + body.lower().rjust(64, "0")
        result = self._rpc("eth_call", [{"to": token, "data": call_data}, "latest"])
        return raw_to_units(_hex_to_int(result), int(decimals or 18))

class SolanaRpcAdapter(ChainAdapter):
    """Solana JSON-RPC：getTokenLargestAccounts + 持仓账户 owner 解析。

    公共节点普遍对 getTokenLargestAccounts 限流，建议在 [whales] 里
    配置自己的 RPC 地址。
    """

    kind = "solana"

    def __init__(self, chain, name, rpc_url, client, native_symbol="SOL"):
        super().__init__(chain, name, client)
        self.rpc_url = str(rpc_url)
        self.native_symbol = native_symbol

    def token_url(self, token):
        return f"https://solscan.io/token/{token}"

    def address_url(self, token, address):
        return f"https://solscan.io/account/{address}"

    def _rpc(self, method, params):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            data = self.client.post_json(self.rpc_url, body)
        except DataSourceError as exc:
            raise DataSourceError(f"Solana RPC {method} 失败: {exc}") from exc
        if not isinstance(data, dict):
            raise DataSourceError(f"Solana RPC {method} 返回异常: {data}")
        return data.get("result")

    def fetch_token_meta(self, token):
        key = str(token)
        cached = self._meta_cache.get(key)
        if cached is not None:
            return cached
        if is_native_token(self.chain, token):
            meta = TokenMeta(
                symbol=self.native_symbol,
                name=self.native_symbol,
                decimals=9,
                kind="native",
            )
            self._meta_cache[key] = meta
            return meta
        result = self._rpc("getTokenSupply", [token]) or {}
        value = result.get("value") or {}
        meta = TokenMeta(
            symbol="",
            name="",
            decimals=int(value.get("decimals") or 0),
            supply=_as_float(value.get("uiAmountString") or value.get("uiAmount")),
            kind="spl",
        )
        self._enrich_symbol(token, meta)
        self._meta_cache[key] = meta
        return meta

    def _enrich_symbol(self, token, meta):
        """尽量补上代币符号：优先 DAS，其次 Mint 账户扩展字段。"""
        try:
            asset = self._rpc("getAsset", [{"id": token}]) or {}
            content = ((asset.get("content") or {}).get("metadata") or {})
            meta.symbol = str(content.get("symbol") or meta.symbol or "")
            meta.name = str(content.get("name") or meta.name or "")
            if meta.symbol or meta.name:
                return
        except Exception:
            pass
        try:
            info = self._rpc("getAccountInfo", [token, {"encoding": "jsonParsed"}]) or {}
            parsed = (((info.get("value") or {}).get("data") or {}).get("parsed") or {})
            meta_info = parsed.get("info") or {}
            meta.symbol = str(meta_info.get("symbol") or meta.symbol or "")
            meta.name = str(meta_info.get("name") or meta.name or "")
        except Exception:
            pass

    def _owners_for(self, keys):
        owners = {}
        if not keys:
            return owners
        try:
            data = self._rpc(
                "getMultipleAccounts", [keys, {"encoding": "jsonParsed"}]
            ) or {}
        except Exception:
            return owners
        for key, item in zip(keys, data.get("value") or []):
            if not isinstance(item, dict):
                continue
            parsed = ((item.get("data") or {}).get("parsed") or {})
            owner = str((parsed.get("info") or {}).get("owner") or "")
            if owner:
                owners[key] = owner
        return owners

    def fetch_top_holders(self, token, limit=50, decimals=None):
        if is_native_token(self.chain, token):
            raise DataSourceError("Solana 原生 SOL 没有持仓榜接口")
        meta = self.fetch_token_meta(token)
        result = self._rpc("getTokenLargestAccounts", [token]) or {}
        accounts = result.get("value") or []
        if not accounts:
            return []
        keys = [str(item.get("address")) for item in accounts if item.get("address")]
        owners = self._owners_for(keys)
        holders = []
        for item in accounts[: max(1, int(limit))]:
            account = str(item.get("address") or "")
            decimals_value = item.get("decimals", meta.decimals)
            holders.append(
                Holder(
                    address=owners.get(account, account),
                    balance=raw_to_units(item.get("amount") or 0, decimals_value),
                )
            )
        return holders

    def fetch_balance(self, token, address, decimals=None):
        if is_native_token(self.chain, token):
            result = self._rpc("getBalance", [address]) or {}
            return raw_to_units(result.get("value") or 0, 9)
        result = self._rpc(
            "getTokenAccountsByOwner",
            [address, {"mint": token}, {"encoding": "jsonParsed"}],
        ) or {}
        total = 0.0
        for item in result.get("value") or []:
            parsed = (((item.get("account") or {}).get("data") or {}).get("parsed") or {})
            info = parsed.get("info") or {}
            amount = info.get("tokenAmount") or {}
            total += _as_float(amount.get("uiAmountString") or amount.get("uiAmount"))
        return total


class BlockchairAdapter(ChainAdapter):
    """Blockchair 富豪榜：UTXO 链的地址持仓排名。

    免费额度有限且共享出口 IP 容易被临时拉黑，因此自带了供应量缓存；
    在 [whales] 配置 blockchair_key 可提高额度。
    """

    kind = "utxo"
    SUPPLY_TTL = 600.0

    def __init__(self, chain, name, symbol, decimals, base_url, client, api_key=""):
        super().__init__(chain, name, client)
        self.symbol = symbol
        self.decimals = int(decimals)
        self.base_url = str(base_url).rstrip("/")
        self.api_key = str(api_key or "").strip()
        self._supply = 0.0
        self._supply_at = 0.0
        self._price = 0.0
        self._holders = 0

    def token_url(self, token):
        return f"https://blockchair.com/{self.chain}"

    def address_url(self, token, address):
        return f"https://blockchair.com/{self.chain}/address/{address}"

    def _get(self, path, params=None):
        query = dict(params or {})
        if self.api_key:
            query["key"] = self.api_key
        url = f"{self.base_url}/{self.chain}/{path}"
        data = self.client.get_json(url, params=query)
        context = (data or {}).get("context") or {}
        code = context.get("code")
        if code != 200:
            message = str(context.get("error") or f"Blockchair 返回 code={code}")
            if code == 430:
                message += "（可配置 [whales] blockchair_key，或降低扫描频率）"
            raise DataSourceError(message)
        return data

    def _load_stats(self):
        now = time.time()
        if self._supply > 0 and now - self._supply_at < self.SUPPLY_TTL:
            return
        stats = self._get("stats").get("data") or {}
        price = _as_float(stats.get("market_price_usd"))
        cap = _as_float(stats.get("market_cap_usd"))
        supply = cap / price if price > 0 and cap > 0 else 0.0
        if supply <= 0:
            # Zcash 等链的 circulation 是屏蔽池口径的负数，只在兜底时使用。
            supply = _as_float(stats.get("circulation"))
        self._supply = max(0.0, supply)
        self._price = price
        self._holders = int(_as_float(stats.get("hodling_addresses"), 0))
        self._supply_at = now

    def fetch_token_meta(self, token):
        cached = self._meta_cache.get("native")
        if cached is not None:
            return cached
        self._load_stats()
        meta = TokenMeta(
            symbol=self.symbol,
            name=self.name,
            decimals=self.decimals,
            supply=self._supply,
            holder_count=self._holders,
            price_usd=self._price,
            kind="native",
        )
        self._meta_cache["native"] = meta
        return meta

    def fetch_top_holders(self, token, limit=50, decimals=None):
        limit = max(1, int(limit))
        data = self._get("addresses", {"limit": limit, "s": "balance(desc)"})
        holders = []
        for row in data.get("data") or []:
            if not isinstance(row, dict):
                continue
            address = str(row.get("address") or "")
            if not address:
                continue
            holders.append(
                Holder(
                    address=address,
                    balance=raw_to_units(row.get("balance") or 0, self.decimals),
                )
            )
        return holders[:limit]

    def fetch_balance(self, token, address, decimals=None):
        data = self._get(f"dashboards/address/{address}")
        node = (data.get("data") or {}).get(address) or {}
        info = node.get("address") or {}
        return raw_to_units(info.get("balance") or 0, self.decimals)

    def supports_transactions(self):
        return True

    def _utxo_tx_row(self, address, tx_hash, info):
        me = str(address)
        received = 0.0
        sent = 0.0
        peer = ""
        for out in info.get("outputs") or []:
            who = str(out.get("recipient") or "")
            if who == me:
                received += raw_to_units(out.get("value") or 0, self.decimals)
            elif who and not peer:
                peer = who
        for inp in info.get("inputs") or []:
            who = str(inp.get("recipient") or "")
            if who == me:
                sent += raw_to_units(inp.get("value") or 0, self.decimals)
            elif who and not peer:
                peer = who
        if received and sent:
            direction = "self"
        elif sent:
            direction = "out"
        else:
            direction = "in"
        tx = info.get("transaction") or {}
        return {
            "hash": tx_hash,
            "time_ms": _parse_iso_ms(tx.get("time") or tx.get("date")),
            "direction": direction,
            "counterparty": peer,
            "value": abs(received - sent) if (received or sent) else 0.0,
            "asset": self.symbol,
            "url": f"https://blockchair.com/{self.chain}/transaction/{tx_hash}",
        }

    def fetch_transactions(self, token, address, limit=20):
        limit = max(1, min(50, int(limit)))
        data = self._get(f"dashboards/address/{address}", {"limit": limit})
        node = (data.get("data") or {}).get(address) or {}
        hashes = [h for h in (node.get("transactions") or []) if isinstance(h, str)][:limit]
        if not hashes:
            return []
        detail = self._get("dashboards/transactions/" + ",".join(hashes))
        payload = (detail.get("data") or {})
        return [
            self._utxo_tx_row(address, tx_hash, payload.get(tx_hash) or {})
            for tx_hash in hashes
        ]


class EvmRpcAdapter(ChainAdapter):
    """只提供 JSON-RPC 的 EVM 链：可做余额监控，但没有免费持仓榜。"""

    kind = "evm-rpc"

    def __init__(self, chain, name, rpc_url, chain_id, client, native_symbol=""):
        super().__init__(chain, name, client)
        self.rpc_url = str(rpc_url)
        self.chain_id = int(chain_id)
        self.native_symbol = native_symbol or "ETH"

    def supports_scan(self):
        return False

    def _rpc(self, method, params):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            data = self.client.post_json(self.rpc_url, body)
        except DataSourceError as exc:
            raise DataSourceError(f"{self.name} RPC {method} 失败: {exc}") from exc
        if not isinstance(data, dict) or "result" not in data:
            raise DataSourceError(f"{self.name} RPC {method} 返回异常: {data}")
        return data.get("result")

    def _erc20_decimals(self, token):
        try:
            result = self._rpc(
                "eth_call", [{"to": token, "data": "0x313ce567"}, "latest"]
            )
        except DataSourceError:
            return 18
        value = _hex_to_int(result)
        return value if 0 < value <= 36 else 18

    def fetch_token_meta(self, token):
        key = str(token).lower()
        cached = self._meta_cache.get(key)
        if cached is not None:
            return cached
        if is_native_token(self.chain, token):
            meta = TokenMeta(
                symbol=self.native_symbol,
                name=self.name,
                decimals=18,
                kind="native",
            )
        else:
            meta = TokenMeta(
                symbol="",
                name="",
                decimals=self._erc20_decimals(token),
                kind="erc20",
            )
        self._meta_cache[key] = meta
        return meta

    def fetch_top_holders(self, token, limit=50, decimals=None):
        raise DataSourceError(
            f"{self.name} 没有免费的持仓榜接口，只能监控已知地址的余额"
        )

    def fetch_balance(self, token, address, decimals=None):
        if is_native_token(self.chain, token):
            result = self._rpc("eth_getBalance", [address, "latest"])
            return raw_to_units(_hex_to_int(result), 18)
        if not is_hex_address(token):
            raise DataSourceError(
                f"{self.name} 的代币参数需要合约地址（0x 开头 40 位十六进制）；"
                f"监控原生币请填 native，本链原生币是 {self.native_symbol}"
            )
        if decimals is None:
            decimals = self.fetch_token_meta(token).decimals
        body = str(address)
        if body.lower().startswith("0x"):
            body = body[2:]
        call_data = BALANCE_OF_SELECTOR + body.lower().rjust(64, "0")
        result = self._rpc("eth_call", [{"to": token, "data": call_data}, "latest"])
        return raw_to_units(_hex_to_int(result), int(decimals or 18))

def build_adapters(whale_cfg, proxy_url=None):
    """按配置构建 ``chain -> adapter`` 映射表。"""
    client = HttpClient(
        proxy_url=proxy_url,
        timeout=_as_float(getattr(whale_cfg, "timeout", 25.0), 25.0),
        retries=int(getattr(whale_cfg, "retries", 2) or 0),
    )
    overrides = dict(getattr(whale_cfg, "chain_urls", None) or {})
    disabled = {str(item).lower() for item in (getattr(whale_cfg, "disabled_chains", None) or [])}
    adapters = {}

    for chain, (name, base_url, chain_id) in BLOCKSCOUT_CHAINS.items():
        if chain in disabled:
            continue
        adapters[chain] = BlockscoutAdapter(
            chain, name, overrides.get(chain) or base_url, chain_id, client
        )

    for chain, (name, rpc_url, chain_id) in EVM_RPC_CHAINS.items():
        if chain in disabled:
            continue
        adapters[chain] = EvmRpcAdapter(
            chain,
            name,
            overrides.get(chain) or rpc_url,
            chain_id,
            client,
            native_symbol=str(getattr(whale_cfg, "hyperevm_symbol", "") or "HYPE"),
        )

    solana_rpc = str(getattr(whale_cfg, "solana_rpc", "") or "").strip()
    if solana_rpc and "solana" not in disabled:
        adapters["solana"] = SolanaRpcAdapter(
            "solana", "Solana", solana_rpc, client
        )

    blockchair_url = str(
        getattr(whale_cfg, "blockchair_url", "") or "https://api.blockchair.com"
    ).rstrip("/")
    blockchair_key = str(getattr(whale_cfg, "blockchair_key", "") or "")
    wanted = getattr(whale_cfg, "blockchair_chains", None) or list(BLOCKCHAIR_CHAINS)
    for chain in wanted:
        chain = str(chain).lower()
        spec = BLOCKCHAIR_CHAINS.get(chain)
        if not spec or chain in disabled:
            continue
        name, symbol, decimals = spec
        adapters[chain] = BlockchairAdapter(
            chain, name, symbol, decimals, blockchair_url, client, blockchair_key
        )
    return adapters


def _classify_holder(holder, exclude_tags, exclude_addresses, exclude_keywords=()):
    """判断持仓地址是否为多人共用基础设施或销毁地址。"""
    lowered = str(holder.address or "").lower()
    if lowered in BURN_ADDRESSES:
        return True, "销毁地址"
    if lowered in exclude_addresses:
        return True, "手动排除"
    for tag in holder.tags:
        if str(tag).lower() in exclude_tags:
            return True, f"标签:{tag}"
    label = str(holder.label or "").lower()
    if label:
        for keyword in exclude_keywords:
            keyword = str(keyword or "").strip().lower()
            if keyword and keyword in label:
                return True, f"名称含 {keyword}"
    return False, ""


def concentration_score(whale_pct, whale10_pct):
    """0-100 集中度评分：单个非基础设施地址 35%、前十大 80% 记满分。"""
    single = min(max(_as_float(whale_pct), 0.0) / 35.0, 1.0)
    cluster = min(max(_as_float(whale10_pct), 0.0) / 80.0, 1.0)
    return round((0.65 * single + 0.35 * cluster) * 100.0, 1)


def rank_token_candidates(query, items, chain, limit=10):
    """给搜索结果排序：符号精确命中优先，其次看市值，最后才是名称包含。"""
    needle = str(query or "").strip().lower()
    rows = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "token":
            continue
        token_type = str(item.get("token_type") or "").upper()
        if token_type and token_type != "ERC-20":
            continue
        address = str(item.get("address_hash") or item.get("address") or "").strip()
        if not is_hex_address(address):
            continue
        symbol = str(item.get("symbol") or "").strip()
        name = str(item.get("name") or "").strip()
        lowered_symbol = symbol.lower()
        lowered_name = name.lower()
        if lowered_symbol == needle:
            tier = 0
        elif lowered_name == needle:
            tier = 1
        elif lowered_symbol.startswith(needle):
            tier = 2
        elif needle and needle in lowered_symbol:
            tier = 3
        elif needle and lowered_name.startswith(needle):
            tier = 4
        else:
            # 关键词在符号和名称里都找不到就直接丢掉：
            # Blockscout 没有匹配时会回退成热门代币列表，不能照单全收。
            continue
        rows.append(
            {
                "chain": chain,
                "address": address,
                "symbol": symbol,
                "name": name,
                "token_type": token_type or "ERC-20",
                "market_cap": _as_float(item.get("circulating_market_cap")),
                "price_usd": _as_float(item.get("exchange_rate")),
                "tier": tier,
            }
        )
    rows.sort(key=lambda row: (row["tier"], -row["market_cap"], row["symbol"]))
    return rows[: max(1, int(limit))]


@dataclass
class TokenResolution:
    """符号 -> 合约地址 的解析结果。"""

    query: str = ""
    address: str = ""
    symbol: str = ""
    name: str = ""
    ambiguous: bool = False
    exact_count: int = 0
    candidates: list = field(default_factory=list)

    @property
    def ok(self):
        return bool(self.address)

    @property
    def changed(self):
        return self.ok and self.query.lower() != self.address.lower()

    def to_dict(self):
        return {
            "query": self.query,
            "address": self.address,
            "symbol": self.symbol,
            "name": self.name,
            "ambiguous": self.ambiguous,
            "exact_count": self.exact_count,
            "changed": self.changed,
            "candidates": self.candidates,
        }


def search_tokens(adapters, query, chain=None, limit=10):
    """按关键词检索代币；给了链就只查该链，否则并发查所有支持的链。"""
    text = str(query or "").strip()
    if len(text) < 2:
        return []
    if chain:
        adapter = adapters.get(str(chain).lower())
        targets = [adapter] if adapter and adapter.supports_search() else []
    else:
        targets = [item for item in adapters.values() if item.supports_search()]
    if not targets:
        return []

    rows = []
    workers = max(1, min(6, len(targets)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(adapter.search_tokens, text, limit): adapter
            for adapter in targets
        }
        for future in as_completed(futures):
            try:
                rows.extend(future.result() or [])
            except Exception:
                continue
    rows.sort(key=lambda row: (row["tier"], -row["market_cap"], row["chain"]))
    for row in rows:
        row.pop("tier", None)
    return rows[: max(1, int(limit))]


def resolve_token(adapter, token, limit=8):
    """把代币符号解析成合约地址。

    已经是合约地址、或属于本链原生币时原样返回；否则用模糊检索，
    唯一精确命中就直接用，多个候选则交回上层让用户选。
    """
    text = str(token or "").strip()
    result = TokenResolution(query=text)
    if not text or is_native_token(adapter.chain, text) or is_hex_address(text):
        result.address = text
        return result
    if not adapter.supports_search():
        result.address = text
        return result

    try:
        candidates = adapter.search_tokens(text, limit=limit)
    except Exception:
        result.address = text
        return result

    result.candidates = candidates
    exact = [item for item in candidates if item["symbol"].lower() == text.lower()]
    result.exact_count = len(exact)
    if len(exact) == 1:
        picked = exact[0]
    elif len(exact) > 1:
        # 同名代币很常见（大量假币会抄符号）。Blockscout 能给出市值，
        # 市值最高的那个基本就是正规代币，其余的空市值一一律不选。
        top, second = exact[0], exact[1]
        dominant = top["market_cap"] > 0 and (
            second["market_cap"] <= 0 or top["market_cap"] >= second["market_cap"] * 5
        )
        if not dominant:
            result.ambiguous = True
            return result
        picked = top
    elif len(candidates) == 1:
        picked = candidates[0]
    else:
        result.ambiguous = bool(candidates)
        return result

    result.address = picked["address"]
    result.symbol = picked["symbol"]
    result.name = picked["name"]
    return result


def scan_token(
    adapter,
    token,
    limit=50,
    exclude_tags=None,
    exclude_addresses=None,
    exclude_keywords=None,
):
    """扫描单个代币的持仓集中度。

    交易所、跨链桥、DEX 池等多人共用地址会被剔除出“单地址集中度”，
    但仍然出现在原始前十大占比里，便于区分“庄家控盘”和“交易所代持”。
    """
    tags = {
        str(item).lower()
        for item in (
            exclude_tags if exclude_tags is not None else DEFAULT_EXCLUDE_TAGS
        )
    }
    excluded = {str(item).lower() for item in (exclude_addresses or [])}
    keywords = tuple(
        exclude_keywords
        if exclude_keywords is not None
        else DEFAULT_EXCLUDE_LABEL_KEYWORDS
    )

    report = ConcentrationReport(
        chain=adapter.chain,
        token=str(token),
        scanned_ms=int(time.time() * 1000),
    )

    try:
        meta = adapter.fetch_token_meta(token)
    except Exception as exc:
        report.error = f"读取代币信息失败: {exc}"
        return report

    report.symbol = meta.symbol
    report.name = meta.name
    report.decimals = meta.decimals
    report.supply = meta.supply
    report.holder_count = meta.holder_count
    report.price_usd = meta.price_usd

    try:
        holders = adapter.fetch_top_holders(
            token, limit=max(1, int(limit)), decimals=meta.decimals
        )
    except Exception as exc:
        report.error = f"读取持仓榜失败: {exc}"
        return report

    supply = meta.supply
    if supply > 0:
        for holder in holders:
            holder.pct = holder.balance / supply * 100.0
    else:
        # 拿不到流通量时按前十大自身归一，避免整张表都是 0%。
        total = sum(item.balance for item in holders) or 1.0
        for holder in holders:
            holder.pct = holder.balance / total * 100.0

    for index, holder in enumerate(holders, 1):
        holder.rank = index
        holder.excluded, holder.exclude_reason = _classify_holder(
            holder, tags, excluded, keywords
        )
    report.holders = holders

    report.top1_pct = holders[0].pct if holders else 0.0
    report.top5_pct = sum(item.pct for item in holders[:5])
    report.top10_pct = sum(item.pct for item in holders[:10])

    clean = [item for item in holders if not item.excluded]
    if clean:
        report.whale_address = clean[0].address
        report.whale_label = clean[0].label
        report.whale_pct = clean[0].pct
        report.whale10_pct = sum(item.pct for item in clean[:10])
    report.score = concentration_score(report.whale_pct, report.whale10_pct)
    return report

def _short_addr(address, head=10, tail=6):
    text = str(address or "")
    if len(text) <= head + tail + 1:
        return text
    return f"{text[:head]}…{text[-tail:]}"


def _fmt_amount(value):
    """紧凑数量显示，方便在窄屏对齐。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if number == 0:
        return "0"
    sign = "-" if number < 0 else ""
    magnitude = abs(number)
    if magnitude >= 1_000_000_000:
        return f"{sign}{magnitude / 1_000_000_000:.2f}B"
    if magnitude >= 1_000_000:
        return f"{sign}{magnitude / 1_000_000:.2f}M"
    if magnitude >= 1_000:
        return f"{sign}{magnitude:,.0f}"
    if magnitude >= 1:
        return f"{sign}{magnitude:,.2f}"
    return f"{sign}{magnitude:.6f}".rstrip("0").rstrip(".")


def describe_chains(adapters):
    """列出可扫描持仓榜的链和仅支持余额监控的链。"""
    scanable = []
    watch_only = []
    for chain, adapter in sorted(adapters.items()):
        entry = f"{chain}({adapter.name})"
        if adapter.supports_scan():
            scanable.append(entry)
        else:
            watch_only.append(entry)
    lines = []
    if scanable:
        lines.append("可扫描持仓榜：" + "、".join(scanable))
    if watch_only:
        lines.append("仅余额监控：" + "、".join(watch_only))
    if not lines:
        lines.append("没有启用任何链，请检查 [whales] 配置。")
    return "\n".join(lines)


def format_scan_html(report, trend=None, max_rows=12):
    """把集中度扫描结果排版成 Telegram HTML。"""
    symbol = report.symbol or report.name or report.token
    lines = [f"<b>🐋 {html.escape(str(symbol))} 筹码集中度</b>"]

    if report.error:
        lines.append(
            f"链 <code>{html.escape(report.chain)}</code> 扫描失败："
            f"{html.escape(report.error)}"
        )
        return "\n".join(lines)

    lines.append(
        f"链 <code>{html.escape(report.chain)}</code> · "
        f"最大非基础设施地址 <b>{report.whale_pct:.2f}%</b> · "
        f"非基础设施前十大 <b>{report.whale10_pct:.2f}%</b> · "
        f"评分 <b>{report.score:.0f}</b>/100"
    )

    detail = []
    if report.supply > 0:
        detail.append(f"流通 {_fmt_amount(report.supply)}")
    if report.holder_count:
        detail.append(f"持币地址 {report.holder_count:,}")
    if report.price_usd > 0:
        price = f"{report.price_usd:,.4f}".rstrip("0").rstrip(".")
        detail.append(f"价格 ${price}")
    if detail:
        lines.append(" · ".join(detail))

    lines.append(
        f"全部地址口径：前1 {report.top1_pct:.2f}% · "
        f"前5 {report.top5_pct:.2f}% · 前10 {report.top10_pct:.2f}%"
    )

    if report.whale_address:
        label = f"（{html.escape(report.whale_label)}）" if report.whale_label else ""
        lines.append(
            "最大非基础设施地址："
            f"<code>{html.escape(_short_addr(report.whale_address))}</code>"
            f"{label}"
        )

    if trend:
        lines.append(
            f"对比上次（{html.escape(str(trend.get('time') or '-'))}）："
            f"{_as_float(trend.get('whale_pct')):.2f}% → {report.whale_pct:.2f}%"
        )

    rows = ["  #    地址               数量       占比  标签"]
    for holder in report.holders[: max(1, int(max_rows))]:
        mark = "🚫" if holder.excluded else "  "
        label = (holder.label or ("合约" if holder.is_contract else ""))[:18]
        rows.append(
            f"{holder.rank:>3} {mark} {_short_addr(holder.address, 8, 5):<16}"
            f"{_fmt_amount(holder.balance):>12} {holder.pct:>6.2f}%  {label}"
        )
    if len(rows) > 1:
        lines.append("")
        lines.append("<pre>" + "\n".join(rows) + "</pre>")

    lines.append("🚫 = 交易所/跨链桥/DEX 池等多人共用地址，不计入单地址集中度")
    return "\n".join(lines)


def format_watchlist_html(entries, balances=None):
    """已监控地址列表；balances 是 (chain, token, address) -> 数量。"""
    if not entries:
        return "还没有监控任何链上地址。"
    balances = balances or {}
    lines = []
    for index, entry in enumerate(entries, 1):
        chain = str(entry.get("chain") or "")
        token = str(entry.get("token") or "")
        address = str(entry.get("address") or "")
        label = entry.get("label") or entry.get("symbol") or ""
        line = (
            f"{index}. <b>{html.escape(str(label))}</b> "
            f"<code>{html.escape(chain)}</code> "
            f"<code>{html.escape(_short_addr(address))}</code>"
        )
        current = balances.get((chain, token, address))
        if current is not None:
            line += f" · {_fmt_amount(current)}"
        lines.append(line)
        error = str(entry.get("last_error") or entry.get("error") or "").strip()
        if error:
            lines.append(f"    ⚠️ {html.escape(error[:200])}")
    return "\n".join(lines)

@dataclass
class WhaleAlert:
    """一条待发送的链上告警。"""

    chat_id: str
    kind: str
    text: str
    data: dict = field(default_factory=dict)


class WhaleWatcher:
    """轮询已跟踪的链上地址，余额变化超过阈值时产生告警。

    首次检查只写入基线，之后才按 ``min_delta_pct`` / ``min_delta_abs``
    判断是否需要通知；扫描失败的地址会记录错误但不会中断整轮。
    """

    def __init__(
        self,
        adapters,
        store,
        interval=300.0,
        exclude_tags=None,
        exclude_addresses=None,
        exclude_keywords=None,
        concentration_threshold=3.0,
        monitor_transactions=True,
        tx_limit=20,
        log=None,
    ):
        self.adapters = adapters
        self.store = store
        self.interval = max(30.0, float(interval))
        self.exclude_tags = exclude_tags
        self.exclude_addresses = exclude_addresses
        self.exclude_keywords = exclude_keywords
        self.concentration_threshold = max(0.1, float(concentration_threshold))
        self.monitor_transactions = bool(monitor_transactions)
        self.tx_limit = max(1, min(50, int(tx_limit)))
        self._log = log or (lambda message: None)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="whale-watch", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.check_addresses()
            except Exception as exc:
                self._log(f"[whale] 地址轮询失败: {exc}")
            try:
                self.check_tokens()
            except Exception as exc:
                self._log(f"[whale] 代币复扫失败: {exc}")
            if self._stop.wait(self.interval):
                return

    def _adapter_for(self, chain):
        return self.adapters.get(str(chain or "").lower())

    # ---------------------------------------------------------------- 地址余额

    def check_addresses(self, force=False, chat_id=None, targets=None):
        """检查余额。

        targets 为 (chain, token, address) 集合时只查这些条目。
        必须带上链和代币：同一个地址可能在不同链上被分别监控。
        """
        alerts = []
        now_ms = int(time.time() * 1000)
        wanted = None
        if targets is not None:
            wanted = {(str(c), str(t), str(a)) for c, t, a in targets}
            if not wanted:
                return alerts
        for entry in self.store.due_whale_watches(now_ms, force=force, chat_id=chat_id):
            if wanted is not None:
                key = (
                    str(entry.get("chain") or ""),
                    str(entry.get("token") or ""),
                    str(entry.get("address") or ""),
                )
                if key not in wanted:
                    continue
            try:
                alerts.extend(self._check_watch(entry, now_ms) or [])
            except Exception as exc:
                self._log(f"[whale] 检查 {entry.get('address')} 失败: {exc}")
                self._record_watch_error(entry, now_ms, exc)
        return alerts

    def _record_watch_error(self, entry, now_ms, exc):
        """把检查失败的原因写进库，供页面和 Telegram 展示。"""
        try:
            self.store.mark_whale_watch(
                str(entry.get("chat_id") or ""),
                str(entry.get("chain") or ""),
                str(entry.get("token") or ""),
                str(entry.get("address") or ""),
                now_ms,
                error=_error_text(exc),
            )
        except Exception as store_exc:
            self._log(f"[whale] 记录失败原因时出错: {store_exc}")

    def _record_token_error(self, entry, now_ms, exc):
        try:
            self.store.mark_whale_token(
                str(entry.get("chat_id") or ""),
                str(entry.get("chain") or ""),
                str(entry.get("token") or ""),
                now_ms,
                error=_error_text(exc),
            )
        except Exception as store_exc:
            self._log(f"[whale] 记录复扫失败原因时出错: {store_exc}")

    def _check_watch(self, entry, now_ms):
        """返回该条目的告警列表：余额变动 + 新的链上成交。"""
        chain = str(entry.get("chain") or "")
        token = str(entry.get("token") or "")
        address = str(entry.get("address") or "")
        chat_id = str(entry.get("chat_id") or "")
        adapter = self._adapter_for(chain)
        if adapter is None:
            self.store.mark_whale_watch(
                chat_id, chain, token, address, now_ms, error=f"未知链 {chain}"
            )
            return []

        alerts = []
        balance = None
        try:
            balance = adapter.fetch_balance(token, address, entry.get("decimals"))
        except Exception as exc:
            self.store.mark_whale_watch(
                chat_id, chain, token, address, now_ms, error=_error_text(exc)
            )

        if balance is not None:
            previous = entry.get("last_balance")
            self.store.mark_whale_watch(
                chat_id, chain, token, address, now_ms, balance=balance
            )
            if previous is not None:
                previous = float(previous)
                delta = balance - previous
                base = abs(previous)
                pct = (delta / base * 100.0) if base > 0 else 100.0
                big_enough = abs(delta) >= _as_float(
                    entry.get("min_delta_abs"), 0.0
                )
                min_pct = _as_float(entry.get("min_delta_pct"), 0.0)
                pct_ok = min_pct <= 0 or abs(pct) >= min_pct
                if abs(delta) > 0 and big_enough and pct_ok:
                    alerts.append(
                        WhaleAlert(
                            chat_id=chat_id,
                            kind="whale_move",
                            text=self._format_move(
                                entry, previous, balance, delta, pct
                            ),
                            data={
                                "chain": chain,
                                "token": token,
                                "address": address,
                                "balance": balance,
                                "previous": previous,
                                "delta": delta,
                                "pct": pct,
                            },
                        )
                    )

        # 成交检查独立于余额：有些数据源余额走 RPC、成交走 REST，
        # 一边限流不应该把另一边也拖没。
        if self.monitor_transactions and adapter.supports_transactions():
            try:
                alerts.extend(self._check_watch_transactions(entry, adapter, now_ms))
            except Exception as exc:
                self._log(f"[whale] 拉取成交失败 {address}: {exc}")
                try:
                    self.store.mark_whale_watch_tx(
                        chat_id, chain, token, address, error=_error_text(exc)
                    )
                except Exception:
                    pass
        return alerts

    def _check_watch_transactions(self, entry, adapter, now_ms):
        """对比成交游标，返回新增成交的告警。"""
        chain = str(entry.get("chain") or "")
        token = str(entry.get("token") or "")
        address = str(entry.get("address") or "")
        chat_id = str(entry.get("chat_id") or "")
        rows = adapter.fetch_transactions(token, address, limit=self.tx_limit)
        if not rows:
            # 拉取成功但没有成交，顺手清掉上一次的错误。
            self.store.mark_whale_watch_tx(
                chat_id, chain, token, address, error=""
            )
            return []

        self.store.save_whale_txs(chat_id, chain, token, address, rows, now_ms)
        self._cache_tx_labels(chain, rows)
        newest = max(int(row.get("time_ms") or 0) for row in rows)
        previous = int(entry.get("last_tx_ms") or 0)
        if newest > 0:
            self.store.mark_whale_watch_tx(
                chat_id, chain, token, address, now_ms, newest, error=""
            )
        # 第一次拿到成交只建立基线，否则会把历史记录全推一遍。
        if previous <= 0:
            return []

        fresh = [
            row
            for row in rows
            if int(row.get("time_ms") or 0) > previous
        ]
        if not fresh:
            return []
        fresh.sort(key=lambda row: int(row.get("time_ms") or 0))
        return [self._format_tx_alert(entry, fresh)]

    def _cache_tx_labels(self, chain, rows):
        """把成交响应里自带的地址标签存进库，供对手方分析使用。"""
        entries = []
        seen = set()
        for row in rows:
            for side in ("sender", "receiver"):
                address = str(row.get(side) or "")
                label = str(row.get(side + "_label") or "")
                tags = row.get(side + "_tags") or ()
                if not address:
                    continue
                key = address.lower()
                if key in seen or (not label and not tags):
                    continue
                seen.add(key)
                entries.append(
                    {
                        "chain": chain,
                        "address": address,
                        "label": label,
                        "category": ",".join(str(item) for item in tags),
                        "source": "blockscout",
                    }
                )
        if entries:
            self.store.upsert_address_labels(entries)

    @staticmethod
    def _format_tx_alert(entry, rows):
        chain = str(entry.get("chain") or "")
        address = str(entry.get("address") or "")
        symbol = str(entry.get("symbol") or entry.get("token") or "")
        label = str(entry.get("label") or "")
        title = symbol if not label else f"{symbol} · {label}"
        words = {"in": ("📥", "转入"), "out": ("📤", "转出"), "self": ("🔁", "自转")}
        lines = [
            f"🐋 <b>链上成交 · {html.escape(title)}</b>",
            (
                f"链 <code>{html.escape(chain)}</code> · "
                f"地址 <code>{html.escape(_short_addr(address))}</code>"
            ),
            f"新增 <b>{len(rows)}</b> 笔：",
        ]
        for row in rows[:6]:
            arrow, word = words.get(str(row.get("direction")), ("🔁", "交易"))
            peer = html.escape(_short_addr(str(row.get("counterparty") or "")) or "—")
            asset = html.escape(str(row.get("asset") or symbol))
            amount = _fmt_amount(row.get("value"))
            stamp = fmt_time(row.get("time_ms")) if row.get("time_ms") else "-"
            lines.append(f"{arrow} {word} <b>{amount} {asset}</b> · {peer} · {stamp}")
            if row.get("url"):
                tx_short = html.escape(_short_addr(str(row.get("hash") or "")))
                lines.append(f'    <a href="{html.escape(str(row["url"]))}">{tx_short}</a>')
        if len(rows) > 6:
            lines.append(f"…另有 {len(rows) - 6} 笔")
        return WhaleAlert(
            chat_id=str(entry.get("chat_id") or ""),
            kind="whale_tx",
            text="\n".join(lines),
            data={"chain": chain, "address": address, "count": len(rows)},
        )

    @staticmethod
    def _format_move(entry, previous, balance, delta, pct):
        chain = str(entry.get("chain") or "")
        address = str(entry.get("address") or "")
        symbol = str(entry.get("symbol") or entry.get("token") or "")
        label = str(entry.get("label") or "")
        up = delta > 0
        title = symbol if not label else f"{symbol} · {label}"
        lines = [
            f"{'📈' if up else '📉'} <b>链上大户{'增持' if up else '减持'}</b>",
            f"<b>{html.escape(title)}</b>",
            (
                f"链 <code>{html.escape(chain)}</code> · "
                f"地址 <code>{html.escape(_short_addr(address))}</code>"
            ),
            (
                f"{_fmt_amount(previous)} → <b>{_fmt_amount(balance)}</b>"
                f"  ({_fmt_amount(delta)}, {pct:+.2f}%)"
            ),
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------ 代币集中度

    def check_tokens(self, force=False, chat_id=None, tokens=None):
        """复扫订阅代币；tokens 为 (chain, token) 集合时只扫这些。"""
        alerts = []
        now_ms = int(time.time() * 1000)
        wanted = None
        if tokens is not None:
            wanted = {(str(c), str(t)) for c, t in tokens}
            if not wanted:
                return alerts
        for entry in self.store.due_whale_tokens(now_ms, force=force, chat_id=chat_id):
            if wanted is not None:
                key = (str(entry.get("chain") or ""), str(entry.get("token") or ""))
                if key not in wanted:
                    continue
            try:
                alert = self._check_token(entry, now_ms)
            except Exception as exc:
                self._log(f"[whale] 复扫 {entry.get('token')} 失败: {exc}")
                self._record_token_error(entry, now_ms, exc)
                alert = None
            if alert is not None:
                alerts.append(alert)
        return alerts

    def _check_token(self, entry, now_ms):
        chain = str(entry.get("chain") or "")
        token = str(entry.get("token") or "")
        chat_id = str(entry.get("chat_id") or "")
        adapter = self._adapter_for(chain)
        if adapter is None or not adapter.supports_scan():
            self.store.mark_whale_token(
                chat_id, chain, token, now_ms, error=f"{chain} 不支持持仓榜扫描"
            )
            return None

        report = scan_token(
            adapter,
            token,
            limit=50,
            exclude_tags=self.exclude_tags,
            exclude_addresses=self.exclude_addresses,
            exclude_keywords=self.exclude_keywords,
        )
        if report.error:
            self.store.mark_whale_token(
                chat_id, chain, token, now_ms, error=str(report.error)
            )
            return None

        previous_addr = str(entry.get("last_top_address") or "")
        previous_pct = _as_float(entry.get("last_top_pct"))
        self.store.mark_whale_token(
            chat_id,
            chain,
            token,
            now_ms,
            top_address=report.whale_address,
            top_pct=report.whale_pct,
            score=report.score,
        )
        if not previous_addr:
            return None

        switched = previous_addr != report.whale_address
        moved = abs(report.whale_pct - previous_pct)
        if not switched and moved < self.concentration_threshold:
            return None

        symbol = report.symbol or token
        if switched:
            reason = (
                f"最大非基础设施地址已更换：\n"
                f"<code>{html.escape(_short_addr(previous_addr))}</code> "
                f"{previous_pct:.2f}% → "
                f"<code>{html.escape(_short_addr(report.whale_address))}</code> "
                f"{report.whale_pct:.2f}%"
            )
        else:
            reason = (
                f"最大非基础设施地址占比 {previous_pct:.2f}% → "
                f"<b>{report.whale_pct:.2f}%</b>（{report.whale_pct - previous_pct:+.2f}）"
            )
        return WhaleAlert(
            chat_id=chat_id,
            kind="whale_scan",
            text="\n".join(
                [
                    f"🐋 <b>{html.escape(str(symbol))} 筹码结构变化</b>",
                    f"链 <code>{html.escape(chain)}</code>",
                    reason,
                    f"当前评分 <b>{report.score:.0f}</b>/100",
                ]
            ),
            data=report.to_dict(),
        )