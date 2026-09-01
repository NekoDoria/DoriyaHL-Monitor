"""Hyperliquid WebSocket 客户端：按地址订阅、自动重连、静默检测。"""

import json
import threading
import time

import websocket

from .net import websocket_proxy_kwargs

MAINNET_WS_URL = "wss://api.hyperliquid.xyz/ws"
TESTNET_WS_URL = "wss://api.hyperliquid-testnet.xyz/ws"

USER_CHANNELS = ("userFills", "userEvents", "userNonFundingLedgerUpdates")


class WebSocketMonitor:
    """单个地址的 WebSocket 订阅。

    on_message 回调签名: on_message(address, channel, data)
    """

    def __init__(
        self,
        url,
        address,
        on_message,
        ping_interval=30,
        max_silence=None,
        proxy_url=None,
    ):
        self.url = url
        self.address = address.lower()
        self.on_message = on_message
        self.ping_interval = ping_interval
        self.max_silence = max_silence
        self.proxy_kwargs = websocket_proxy_kwargs(proxy_url)
        self._ws = None
        self._stop = threading.Event()
        self._thread = None
        self._watchdog = None
        self._last_msg = time.time()
        self._lock = threading.Lock()

    def start(self):
        self._thread = threading.Thread(
            target=self._loop, name=f"hl-ws-{self.address[:6]}", daemon=True
        )
        self._thread.start()
        if self.max_silence:
            self._watchdog = threading.Thread(
                target=self._watchdog_loop, name="hl-ws-watchdog", daemon=True
            )
            self._watchdog.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            ws = self._ws
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def _set_ws(self, ws):
        with self._lock:
            self._ws = ws

    def _subscribe_all(self, ws):
        for channel in USER_CHANNELS:
            payload = {
                "method": "subscribe",
                "subscription": {"type": channel, "user": self.address},
            }
            ws.send(json.dumps(payload))

    def _loop(self):
        backoff = 1
        while not self._stop.is_set():
            try:
                self._run_once()
            except Exception as exc:
                print(f"[ws] 连接异常 ({self.address[:6]}...): {exc}")
            if self._stop.is_set():
                break
            time.sleep(min(backoff, 60))
            backoff = min(backoff * 2, 60)

    def _run_once(self):
        app = websocket.WebSocketApp(
            self.url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._set_ws(app)
        app.run_forever(
            ping_interval=self.ping_interval,
            ping_timeout=20,
            **self.proxy_kwargs,
        )
        self._set_ws(None)

    def _watchdog_loop(self):
        while not self._stop.wait(5):
            if time.time() - self._last_msg > self.max_silence:
                print(f"[ws] 超过 {self.max_silence}s 无消息，触发重连 ({self.address[:6]}...)")
                self._last_msg = time.time()
                with self._lock:
                    ws = self._ws
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass

    def _on_open(self, ws):
        print(f"[ws] 已连接 ({self.address[:6]}...)，开始订阅…")
        self._subscribe_all(ws)

    def _on_message(self, ws, message):
        self._last_msg = time.time()
        try:
            msg = json.loads(message)
        except ValueError:
            return
        channel = msg.get("channel")
        data = msg.get("data")
        if channel == "subscriptionResponse":
            return
        if channel and data is not None:
            try:
                self.on_message(self.address, channel, data)
            except Exception as exc:
                print(f"[ws] 处理消息失败 ({self.address[:6]}...): {exc}")

    def _on_error(self, ws, error):
        print(f"[ws] 错误 ({self.address[:6]}...): {error}")

    def _on_close(self, ws, code, reason):
        print(f"[ws] 连接关闭 ({self.address[:6]}..., code={code}, reason={reason})")
