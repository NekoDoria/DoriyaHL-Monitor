# Hyperliquid 地址监控

一个只读监控程序，用于持续观察指定的 Hyperliquid 地址，并在发生成交、清算、资金费、资金流、持仓变化或账户净值变化时告警。

## 功能

- 通过 Hyperliquid WebSocket 实时订阅 `userFills`、`userEvents`、`userNonFundingLedgerUpdates`。
- 定期通过 Info REST API 拉取 `clearinghouseState` 和 `spotClearinghouseState`，检测账户净值、合约持仓与现货余额变化。
- 事件去重并持久化到本地 SQLite（`data/hlmonitor.sqlite3`）。
- 支持控制台、通用 Webhook、Discord、Slack、Telegram 通知。
- 支持通过本地 SOCKS/HTTP 代理访问 Hyperliquid API。

## 快速开始

```powershell
python -m pip install -r requirements.txt
Copy-Item config.example.toml config.toml
```

编辑 `config.toml`，在 `[general] addresses` 中填入要监控的地址。然后运行：

```powershell
python -m hlmonitor
```

也可以在命令行直接指定地址：

```powershell
python -m hlmonitor --address 0x你的地址
```

只拉取一次当前状态并退出：

```powershell
python -m hlmonitor --once --address 0x你的地址
```

## Telegram Bot

也可以把它作为交互式 Telegram Bot 运行：

1. 在 `config.toml` 的 `[alerts.telegram]` 中填写 `bot_token`。
2. 运行：

```powershell
python -m hlmonitor.tgbot
```

在 Telegram 中给 Bot 发送 `/start`，然后使用：

```text
/add 0x地址 别名
/remove 0x地址
/removeall
/list
/status [0x地址]
/stats [0x地址]
/history [0x地址]
/tpsl [0x地址]
/orders [0x地址]
/recent [条数]
/coins
/mute
/unmute
```

告警会发送到添加地址时所在的聊天。`chat_id` 留空时，只要在聊天里添加地址即可；`allowed_chat_ids` 可用于限制只有指定聊天可以使用 Bot。

持仓变化会合并成一条简报，而不是每个币种分别发送。每条简报下方有两个按钮，可以直接切换按仓位价值或按开仓时间排序。

发送 `/coins` 会先选择分类：主流币种、贵金属、其他币种。进入分类后点击币种即可勾选或取消勾选。只有勾选的币种才会发送成交通知；默认全部勾选。

成交通知不会逐笔轰炸，而是自动汇总成多档窗口的实时统计消息（5分钟/15分钟/1小时/4小时/1天/3天/1周）；可以在统计消息下方按钮切换窗口。5分钟、15分钟直接用实时数据，更长的周期会从 Hyperliquid 历史成交接口补全统计。

发送 `/tpsl` 可以查看某个地址当前挂着的止盈止损单（包括跟随仓位的止盈止损和括号单里的子单），下方按钮可以直接切换查看不同地址。

发送 `/orders` 可以查看某个地址当前挂着的普通挂单（止盈止损已单独剔除）。发送后会先选择账户，再通过币种按钮选择标的；也可以直接 `/orders 命名` 跳过账户选择。同一标的里价格相近的挂单会自动合并成密集区间，显示区间最高/最低价、数量加权均价、总数量和总金额，避免逐笔刷屏；点"查看全部"可以一次看所有标的。

合并阈值不是写死的：程序会拉取每个币种最近 48 小时的小时 K 线，用中位波动估计该币种的典型波动，阈值取"典型小时波动 × 1.5"（下限 0.2%、上限 2%）。这样主流币维持 0.2%–0.3% 的严格合并，山寨币自动放宽到 0.5%–1%+，更符合它们真实的挂单间距。同时单个区间有最大宽度限制（默认 = 合并阈值 × 3），避免间距均匀的网格被链式合并成一条横跨好几个百分点的巨型区间。相关参数可在配置文件的 `[orders]` 节调整。

针对网格机器人那种"几十上百笔、间距完全均匀、横跨很大价格范围"的挂单，程序会自动识别为均匀网格，并把整段网格合并成一行（显示"买入网格 · N 笔"、区间、均价和总金额），而不是拆成几十个区间。报告下方还有粒度按钮：**细**（逐笔看）、**自动**（网格合并+波动自适应）、**粗**（更宽松），随时在同一消息里切换，选择会记住。

如果只想用命令行模式做单向 Telegram 通知，需要先给 Bot 发送任意消息，然后运行以下命令获取 `chat_id`：

```powershell
python -m hlmonitor --get-chat-id
```

## 部署到 Debian 13 服务器

不需要打包二进制：服务器上直接跑源码 + 虚拟环境即可，用 systemd 托管实现开机自启和自动重启。

1. 安装系统依赖：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

2. 把项目放到服务器（用 git clone、scp 或 rsync 都行，不要带本地的 `.venv`、`data`、`config.toml`），例如 `/opt/hlmonitor`，并创建运行用户：

```bash
sudo useradd -r -m -s /usr/sbin/nologin hlmonitor
sudo mkdir -p /opt/hlmonitor
sudo chown -R hlmonitor:hlmonitor /opt/hlmonitor
# 把项目文件传到 /opt/hlmonitor 后：
cd /opt/hlmonitor
sudo -u hlmonitor python3 -m venv .venv
sudo -u hlmonitor .venv/bin/pip install -r requirements.txt
```

3. 生成配置。**国外服务器不需要代理**，务必把 `[proxy] enabled` 设为 `false`，否则程序会去连不存在的 `127.0.0.1:7890`：

```bash
sudo -u hlmonitor cp config.example.toml config.toml
sudo -u hlmonitor nano config.toml   # 填 bot_token，proxy.enabled = false
```

4. 先试运行确认没问题：

```bash
cd /opt/hlmonitor
sudo -u hlmonitor .venv/bin/python -m hlmonitor --once --address 0x要监控的地址
sudo -u hlmonitor .venv/bin/python -m hlmonitor.tgbot   # Ctrl+C 退出
```

5. 用 systemd 托管（仓库里已带好 [deploy/hlmonitor.service](deploy/hlmonitor.service)）：

```bash
sudo cp deploy/hlmonitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hlmonitor
sudo systemctl status hlmonitor
journalctl -u hlmonitor -f
```

服务按 `hlmonitor` 用户运行，工作目录是 `/opt/hlmonitor`，数据（SQLite）会存在 `/opt/hlmonitor/data/`，记得备份这个目录。

Bot 使用长轮询主动连接 Telegram API，服务器不需要开放任何入站端口，也不需要域名或反向代理，只要出站 HTTPS 正常即可。

### 想打包成单个二进制？

可以用 PyInstaller 在 **Debian 服务器上**生成单文件（PyInstaller 不能跨平台交叉编译，Windows 上打不出 Linux 可执行文件）：

```bash
cd /opt/hlmonitor
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller --onefile --name hlmonitor_bot --paths . deploy/bot_entry.py
./dist/hlmonitor_bot
```

注意：二进制要在项目目录下运行（它读取同目录的 `config.toml`）；文件更大、每次改代码都要重新打包，对服务器来说并没有比源码 + systemd 更省事，一般不建议。

## 配置

完整示例见 [config.example.toml](config.example.toml)。

常用项：

- `general.network`：`mainnet` 或 `testnet`。
- `general.addresses`：监控地址列表，支持 `0x` 开头或省略 `0x`。
- `proxy.enabled` / `proxy.url`：本地代理，例如 `socks5://127.0.0.1:7890`。
- `alerts.mode`：通知方式。
- `rules.account_value_change_pct`：账户净值告警阈值。

## 注意事项

- 该程序只使用公开的 Info/WebSocket 接口，不需要私钥，也不能下单。
- 首次运行会先写入一份基线快照，之后才根据变化告警。
- WebSocket 连接时的历史快照默认忽略，避免重复告警。
