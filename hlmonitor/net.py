"""Shared networking helpers for optional local SOCKS/HTTP proxy support."""

from __future__ import annotations

import urllib.parse
import urllib.request


def normalize_proxy_url(url: str | None) -> str | None:
    """Return a usable proxy URL, defaulting to socks5 when no scheme is given."""
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    if "://" not in url:
        url = "socks5://" + url
    return url


def _socks_opener(parsed, scheme):
    """用 PySocks 的 SocksiPyHandler 建 opener。

    urllib 自带的 ProxyHandler 对 socks:// 支持不完整：遇到 http（非 https）
    目标时会把请求 scheme 改写成 socks5，随后找不到对应 handler，报
    ``unknown url type: socks5``。这里改用真正的 SOCKS 实现。
    """
    try:
        import socks
        from sockshandler import SocksiPyHandler
    except Exception:
        return None
    if not parsed.hostname:
        return None

    port = parsed.port or 1080
    proxy_type = (
        socks.SOCKS4 if scheme in {"socks4", "socks4a"} else socks.SOCKS5
    )
    # 默认让代理解析域名，避免本地 DNS 被污染。
    kwargs = {"rdns": scheme != "socks4"}
    if parsed.username:
        kwargs["username"] = urllib.parse.unquote(parsed.username)
        kwargs["password"] = urllib.parse.unquote(parsed.password or "")
    try:
        return urllib.request.build_opener(
            SocksiPyHandler(proxy_type, parsed.hostname, port, **kwargs)
        )
    except TypeError:
        try:
            return urllib.request.build_opener(
                SocksiPyHandler(proxy_type, parsed.hostname, port)
            )
        except Exception:
            return None
    except Exception:
        return None


def build_opener(proxy_url: str | None) -> urllib.request.OpenerDirector:
    """Build a urllib opener that routes http(s) traffic through the proxy."""
    proxy_url = normalize_proxy_url(proxy_url)
    if not proxy_url:
        return urllib.request.build_opener()

    parsed = urllib.parse.urlparse(proxy_url)
    scheme = (parsed.scheme or "").lower()
    if scheme in {"socks", "socks4", "socks4a", "socks5", "socks5h"}:
        opener = _socks_opener(parsed, scheme)
        if opener is not None:
            return opener
        # PySocks 不可用时退回“把 SOCKS 端口当 HTTP 隧道用”的写法。
        if parsed.hostname:
            fallback = f"http://{parsed.hostname}:{parsed.port or 7890}"
            return urllib.request.build_opener(
                urllib.request.ProxyHandler(
                    {"http": fallback, "https": fallback}
                )
            )

    handler = urllib.request.ProxyHandler(
        {
            "http": proxy_url,
            "https": proxy_url,
        }
    )
    return urllib.request.build_opener(handler)


def websocket_proxy_kwargs(proxy_url: str | None) -> dict:
    """Translate a proxy URL into websocket-client keyword arguments."""
    proxy_url = normalize_proxy_url(proxy_url)
    if not proxy_url:
        return {}

    parsed = urllib.parse.urlparse(proxy_url)
    scheme = (parsed.scheme or "socks5").lower()
    host = parsed.hostname
    if not host:
        return {}

    default_ports = {
        "http": 80,
        "https": 443,
        "socks": 1080,
        "socks4": 1080,
        "socks5": 1080,
        "socks5h": 1080,
    }
    port = parsed.port or default_ports.get(scheme, 1080)

    if scheme in {"socks", "socks5"}:
        proxy_type = "socks5"
    elif scheme == "socks5h":
        proxy_type = "socks5h"
    elif scheme in {"socks4", "socks4a"}:
        proxy_type = scheme
    else:
        proxy_type = "http"

    kwargs = {
        "http_proxy_host": host,
        "http_proxy_port": port,
        "proxy_type": proxy_type,
    }
    if parsed.username:
        kwargs["http_proxy_auth"] = (
            urllib.parse.unquote(parsed.username),
            urllib.parse.unquote(parsed.password or ""),
        )
    return kwargs
