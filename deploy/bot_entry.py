"""PyInstaller 入口：把 Telegram Bot 打包成单个可执行文件时使用。

用法（在项目根目录，且已在 .venv 里装好依赖）：
    .venv/bin/pip install pyinstaller
    .venv/bin/pyinstaller --onefile --name hlmonitor_bot --paths . deploy/bot_entry.py

产物在 dist/hlmonitor_bot，运行时要在项目目录下执行（它读取 ./config.toml）：
    cd /opt/hlmonitor && ./dist/hlmonitor_bot
"""

from hlmonitor.tgbot import main


if __name__ == "__main__":
    raise SystemExit(main())
