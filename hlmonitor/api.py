"""Hyperliquid Info REST API 封装（只读，不需要密钥）。"""

import json
import urllib.request

from .net import build_opener

MAINNET_INFO_URL = "https://api.hyperliquid.xyz/info"
TESTNET_INFO_URL = "https://api.hyperliquid-testnet.xyz/info"


class HyperliquidAPI:
    def __init__(self, base_url=MAINNET_INFO_URL, timeout=15, proxy_url=None):
        self.base_url = base_url
        self.timeout = timeout
        self.opener = build_opener(proxy_url)

    def _post(self, payload):
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener.open(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def meta(self):
        return self._post({"type": "meta"})

    def perp_dexs(self):
        """List all builder-deployed perp dexes (HIP-3)."""
        return self._post({"type": "perpDexs"})

    def meta_by_dex(self, dex):
        """Return the perp universe for a specific perp dex."""
        payload = {"type": "meta"}
        if dex:
            payload["dex"] = dex
        return self._post(payload)

    def all_mids(self):
        return self._post({"type": "allMids"})

    def clearinghouse_state(self, address, dex=None):
        payload = {"type": "clearinghouseState", "user": address}
        if dex:
            payload["dex"] = dex
        return self._post(payload)

    def spot_state(self, address):
        return self._post({"type": "spotClearinghouseState", "user": address})

    def user_fills(self, address):
        return self._post({"type": "userFills", "user": address})

    def user_fills_by_time(self, address, start_time, end_time=None):
        payload = {
            "type": "userFillsByTime",
            "user": address,
            "startTime": int(start_time),
        }
        if end_time is not None:
            payload["endTime"] = int(end_time)
        return self._post(payload)

    def frontend_open_orders(self, address):
        return self._post({"type": "frontendOpenOrders", "user": address})

    def user_funding(self, address):
        return self._post({"type": "userFunding", "user": address})

    def portfolio(self, address):
        return self._post({"type": "portfolio", "user": address})
