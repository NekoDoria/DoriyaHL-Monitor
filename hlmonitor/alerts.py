"""通知器：控制台 / 通用 Webhook / Discord / Slack / Telegram。"""

import json
import threading
import urllib.request

from .format import fmt_time
from .net import build_opener


class Notifier:
    def notify(self, event):
        raise NotImplementedError


class MultiNotifier(Notifier):
    def __init__(self, notifiers):
        self.notifiers = notifiers
        self._lock = threading.Lock()

    def notify(self, event):
        with self._lock:
            for n in self.notifiers:
                try:
                    n.notify(event)
                except Exception as exc:
                    print(f"[alert] 通知失败 ({type(n).__name__}): {exc}")


class ConsoleNotifier(Notifier):
    def __init__(self, quiet=False):
        self.quiet = quiet

    def notify(self, event):
        if self.quiet:
            return
        print(f"[{fmt_time(event.get('time'))}] {event.get('text', '')}")


class WebhookNotifier(Notifier):
    def __init__(self, url, fmt="generic", timeout=10, proxy_url=None):
        self.url = url
        self.fmt = fmt
        self.timeout = timeout
        self.opener = build_opener(proxy_url)

    def notify(self, event):
        if not self.url:
            return
        if self.fmt == "discord":
            body = {"content": event.get("text", "")}
        elif self.fmt == "slack":
            body = {"text": event.get("text", "")}
        else:
            body = {
                "message": event.get("text", ""),
                "kind": event.get("kind"),
                "address": event.get("address"),
                "time": event.get("time"),
            }
        req = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener.open(req, timeout=self.timeout) as resp:
            resp.read()


class TelegramNotifier(Notifier):
    def __init__(self, bot_token, chat_id, timeout=10, proxy_url=None):
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = str(chat_id)
        self.timeout = timeout
        self.opener = build_opener(proxy_url)

    def notify(self, event):
        body = json.dumps(
            {"chat_id": self.chat_id, "text": event.get("text", "")}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener.open(req, timeout=self.timeout) as resp:
            resp.read()


def build_notifier(config, proxy_url=None):
    """根据配置构建通知器链，至少保留控制台输出。"""
    alerts = config.get("alerts", {})
    mode = alerts.get("mode", "console")
    notifiers = []
    if mode in ("console", "all"):
        notifiers.append(ConsoleNotifier())
    if mode in ("webhook", "all"):
        wh = alerts.get("webhook", {})
        if wh.get("url"):
            notifiers.append(
                WebhookNotifier(
                    wh["url"],
                    wh.get("format", "generic"),
                    proxy_url=proxy_url,
                )
            )
    if mode in ("telegram", "all"):
        tg = alerts.get("telegram", {})
        if tg.get("bot_token") and tg.get("chat_id"):
            notifiers.append(
                TelegramNotifier(
                    tg["bot_token"],
                    tg["chat_id"],
                    proxy_url=proxy_url,
                )
            )
    if not notifiers:
        notifiers.append(ConsoleNotifier())
    return MultiNotifier(notifiers)
