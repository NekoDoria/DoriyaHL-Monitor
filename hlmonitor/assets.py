"""Hyperliquid asset display-name helpers."""

from __future__ import annotations

import threading
import time


class SpotPairNames:
    """Resolve Hyperliquid spot pair ids such as @107 to BASE/QUOTE."""

    def __init__(self, api, ttl=300.0):
        self.api = api
        self.ttl = float(ttl)
        self._lock = threading.RLock()
        self._names: dict[str, str] = {}
        self._loaded_at = 0.0

    def get(self):
        now = time.time()
        with self._lock:
            if self._names and now - self._loaded_at < self.ttl:
                return self._names

        try:
            data = self.api._post({"type": "spotMeta"})
            names = self._parse(data)
            with self._lock:
                self._names = names
                self._loaded_at = now
            return names
        except Exception:
            # Keep names from the previous successful fetch during a
            # transient API failure, so live panels do not regress to @ids.
            with self._lock:
                return dict(self._names)

    @staticmethod
    def _parse(data):
        if not isinstance(data, dict):
            return {}

        tokens = {
            item.get("index"): str(item.get("name") or "")
            for item in data.get("tokens") or []
            if isinstance(item, dict)
        }
        names = {}
        for pair in data.get("universe") or []:
            if not isinstance(pair, dict):
                continue
            index = pair.get("index")
            if index is None:
                continue
            coin = f"@{index}"
            parts = []
            for token_index in pair.get("tokens") or []:
                name = tokens.get(token_index)
                parts.append(name or f"#{token_index}")
            if parts:
                names[coin] = "/".join(parts)
        return names


def spot_coin_label(coin, spot_names):
    """Return a display label while preserving ordinary perp coin names."""
    coin = str(coin or "?")
    if not coin.startswith("@"):
        return coin
    name = (spot_names or {}).get(coin)
    return f"{name}（现货）" if name else f"现货{coin[1:] or '?'}"
