"""Command-line entrypoint for the interactive Telegram bot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import load_config
from .telegram_bot import TelegramBot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hlmonitor.tgbot",
        description="Run the interactive Hyperliquid address monitoring Telegram bot.",
    )
    parser.add_argument(
        "--config",
        help="Path to a TOML config file. Defaults to ./config.toml when present.",
    )
    parser.add_argument(
        "--token",
        help="Telegram bot token. Overrides [alerts.telegram] bot_token.",
    )
    parser.add_argument(
        "--chat-id",
        help="Fallback chat id for alerts. Overrides [alerts.telegram] chat_id.",
    )
    parser.add_argument(
        "--network",
        choices=("mainnet", "testnet"),
        help="Override the Hyperliquid network.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        help="Override Hyperliquid REST polling interval in seconds.",
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

    if args.network:
        config.network = args.network
    if args.poll_interval is not None:
        config.poll_interval = max(1.0, args.poll_interval)
    if args.no_proxy:
        config.proxy_url = None
    elif args.proxy:
        config.proxy_url = args.proxy.strip()

    telegram = config.alerts.setdefault("telegram", {})
    if args.token:
        telegram["bot_token"] = args.token.strip()
    if args.chat_id:
        telegram["chat_id"] = args.chat_id.strip()

    if not telegram.get("bot_token"):
        print(
            "缺少 Telegram bot_token。请在 config.toml 的 [alerts.telegram] "
            "中填写，或使用 --token 参数。",
            file=sys.stderr,
        )
        return 2

    bot = TelegramBot(config)
    try:
        bot.start()
        bot.run_forever()
    except KeyboardInterrupt:
        bot.stop()
    except Exception as exc:
        print(f"[telegram] 启动失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
