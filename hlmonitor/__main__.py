"""Command-line entrypoint for the Hyperliquid address monitor."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import load_config, normalize_addresses
from .monitor import AddressMonitor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hlmonitor",
        description="Monitor Hyperliquid addresses for fills, liquidations, "
        "funding, ledger updates, positions, and account value.",
    )
    parser.add_argument(
        "--config",
        help="Path to a TOML config file. Defaults to ./config.toml when present.",
    )
    parser.add_argument(
        "--address",
        action="append",
        default=[],
        help="Address to monitor. May be repeated. Overrides config addresses.",
    )
    parser.add_argument(
        "--network",
        choices=("mainnet", "testnet"),
        help="Override the Hyperliquid network.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        help="Override REST polling interval in seconds.",
    )
    parser.add_argument(
        "--proxy",
        help="Override proxy URL, e.g. socks5://127.0.0.1:7890.",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Disable proxy even if one is configured.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Poll once and exit without starting WebSocket subscriptions.",
    )
    parser.add_argument(
        "--get-chat-id",
        action="store_true",
        help="Read recent Telegram chat ids for this bot and exit.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    args = build_parser().parse_args(argv)

    config_path = args.config
    if not config_path and Path("config.toml").exists():
        config_path = "config.toml"

    config = load_config(config_path)

    if args.address:
        config.addresses = normalize_addresses(args.address)
    if args.network:
        config.network = args.network
    if args.poll_interval is not None:
        config.poll_interval = max(1.0, args.poll_interval)
    if args.no_proxy:
        config.proxy_url = None
    elif args.proxy:
        config.proxy_url = args.proxy.strip()

    if args.get_chat_id:
        return _print_telegram_chat_ids(config)

    if not config.addresses:
        print(
            "没有配置监控地址。请使用 --address 0x... 或在 config.toml 的 "
            "[general] addresses 中填写。",
            file=sys.stderr,
        )
        return 2

    alerts = config.alerts
    if alerts.get("mode") in ("telegram", "all"):
        telegram = alerts.get("telegram", {})
        if telegram.get("bot_token") and not str(telegram.get("chat_id", "")).strip():
            print(
                "提示：命令行模式下 Telegram 通知需要填写 [alerts.telegram] chat_id。"
                "如果使用交互式 Bot，请运行 python -m hlmonitor.tgbot，"
                "在聊天里发送 /start 后 /add 地址。",
                file=sys.stderr,
            )

    monitor = AddressMonitor(config)
    if args.once:
        monitor.poll_once()
        monitor.store.close()
        return 0

    try:
        monitor.start()
        monitor.run_forever()
    except KeyboardInterrupt:
        monitor.stop()
    except Exception as exc:
        print(f"[monitor] 启动失败: {exc}", file=sys.stderr)
        return 1
    return 0


def _print_telegram_chat_ids(config) -> int:
    from .telegram_bot import TelegramClient

    telegram = config.alerts.get("telegram", {})
    token = str(telegram.get("bot_token", "")).strip()
    if not token:
        print("缺少 Telegram bot_token，无法查询 chat_id。", file=sys.stderr)
        return 2

    try:
        client = TelegramClient(token, proxy_url=config.proxy_url)
        updates = client.get_updates(timeout=0) or []
    except Exception as exc:
        print(f"查询 Telegram 更新失败: {exc}", file=sys.stderr)
        return 1

    found = []
    for update in updates:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        text = (message.get("text") or "").strip()
        found.append((chat_id, chat.get("type", ""), text))

    if not found:
        print(
            "没有读取到待处理消息。请先给 Bot 发送任意一条消息，"
            "然后重新运行：python -m hlmonitor --get-chat-id"
        )
        return 0

    print("检测到以下 Telegram chat_id：")
    for chat_id, chat_type, text in found:
        preview = text[:60] if text else ""
        print(f"  chat_id={chat_id}  type={chat_type}  text={preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
