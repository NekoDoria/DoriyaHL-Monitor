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


def build_opener(proxy_url: str | None) -> urllib.request.OpenerDirector:
    """Build a urllib opener that routes http(s) traffic through the proxy."""
    proxy_url = normalize_proxy_url(proxy_url)
    if not proxy_url:
        return urllib.request.build_opener()
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
