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


## Web UI

也可以启动本地 Web 仪表盘：

```powershell
python -m hlmonitor.web
```

默认地址是 <http://127.0.0.1:8787>。仪表盘使用当前目录的 `config.toml`，提供账户总览、K 线图、成交统计、挂单密集区间、止盈止损、持仓历史、Autohunt 自动收集进程和最近事件。侧栏的「链上筹码」页对应 `[whales]` 功能：选择链并填入代币符号或合约即可扫描持仓集中度（填符号会自动解析，命中多个时列出候选供点选），扫描结果里每一行都能一键加入余额监控，也可以手动指定链、代币和地址；监控地址会按币种自动分组（不同链上的同名币归到同一组），点组头可折叠，折叠状态会记住；每条监控和每个分组都有独立的刷新按钮，可以只重查某条或某一组，不必整批请求；除了余额变化，还会监控这些地址的**链上成交**——转入/转出、对手方、数量和时间都会记录下来，新成交会在页面底部的「最近链上成交」列出并推送告警（可在设置页关闭）；检查失败的原因会汇总在顶部卡片里，卡片和单条原因都能点击收起／展开。页面下方的监控列表与订阅代币和 Telegram 端共用同一份数据。侧栏的「设置」页可以改网站标题、金额显示风格（英文紧凑 `1.23M`／中文单位 `1234.56万`／完整数字 `1,234,567.89`，全站统一，报告里也生效）、主题色、背景/面板色、K 线涨跌色（同时用于盈亏数字），以及代理开关与地址；外观改动会即时预览，代理保存后立即对 REST 与链上请求生效（WebSocket 需要重启进程）。这些设置存在 SQLite 的 `app_settings` 表里，和 `config.toml` 相互独立：`恢复默认` 会回落到 `config.toml` 的初始值。K 线基于 Lightweight Charts，可切换周期和币种，并把当前账户的成交区间、止盈止损和持仓均价叠加到价格轴；挂单密集区间和成交区间都会以长方形价格带叠加：多单绿色、空单红色，两类区间用相近但可区分的色系；成交区间在价格带上标注开多/平多/开空/平空，价格带太窄时标签自动移到上方。长方形支持悬停摘要和点击详情；多个区间重叠时，点击目标按价格坐标判定而不是靠图层前后顺序，价格跨度最小的那个优先；同一个位置叠了好几个区间时，按住 Alt 点击可以在它们之间循环切换（弹窗里会提示这里叠了几个）。区间本身不拦截鼠标事件，因此不会影响图表的缩放、平移和十字线。图表的「Autohunt 区间」开关还能把 autohunt 已收集大户在同一币种上的挂单聚合成区间（蓝色虚线，买入/卖出分别标注大户多/大户空），结果缓存 60 秒。「区间叠加」下方的聚合程度滑块可以实时调整挂单区间和大户区间的合并力度（0.25x 最细、4x 最粗），取值会保存在浏览器里，刷新后仍然生效。侧栏的「成交区间回看」是独立于 K 线周期的：K 线周期只决定每根蜡烛的时间跨度，回看窗口只决定叠加的成交区间往前追溯多久（1 小时～1 周），两者互不影响，选择同样会记住。图表支持全屏模式，全屏时可收起右侧叠加面板。Web 面板展示的是**所有来源的账户并集**：`config.toml` 里配的、网页面板加的、以及 Telegram 里 `/add` 的，都会出现在左侧列表里，并用 `Web` / `TG` / `TG+Web` 徽章标出来源（`config.toml` 里的不带徽章）。在网页上移除某个账户会同时取消它在所有聊天里的订阅，配置里写死的地址只能在 `config.toml` 里改。所有数据都存在同一个 SQLite 数据库里。服务默认只监听 `127.0.0.1`，如需远程访问请使用反向代理并自行增加认证。

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
/update
/coins
/mute
/unmute
/whale — 链上筹码集中度与巨鲸监控
/whale scan <链>:<代币> — 扫描单地址控盘比例
/whale watch <链>:<代币> — 订阅筹码结构变化
/whale add <编号> — 把扫描到的地址加入监控
/whale list — 监控列表
```

告警会发送到添加地址时所在的聊天。`chat_id` 留空时，只要在聊天里添加地址即可；`allowed_chat_ids` 可用于限制只有指定聊天可以使用 Bot。

`/update` 会从当前 Git 分支的 `origin` 拉取最新版本，做快进更新；如果 `requirements.txt` 有变化会先安装依赖，语法自检通过后自动重启。这个命令只允许 `update_admin_chat_ids` 里的聊天使用；未配置时回落到 `allowed_chat_ids` 和 `chat_id`。如果三个配置都为空，为了安全，`/update` 会拒绝执行。注意：如果更新修改了 `deploy/hlmonitor.service`，仍需要手动执行 `sudo systemctl daemon-reload && sudo systemctl restart hlmonitor`。

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

## 链上筹码集中度与巨鲸监控

除了 Hyperliquid 账户，程序还能扫描其他链上的现货筹码分布，找出"单个地址持有大部分流通盘"的币，并持续监控这些地址。

与 Hyperliquid 地址监控的区别：`/add` 监控的是 Hyperliquid 账户的合约持仓与现货余额；`/whale` 关注的是**链上代币的持仓集中度**和**巨鲸地址的余额变动**，两者共用同一套 Telegram 告警。

### 支持的链

| 链 | 数据源 | 持仓榜扫描 | 余额监控 |
| --- | --- | --- | --- |
| Ethereum / Base / Arbitrum / OP / Polygon / Gnosis / Scroll / zkSync / Celo | Blockscout v2（免费免密钥） | 支持 | 支持 |
| Bitcoin / Zcash / Litecoin / Dogecoin / Dash | Blockchair（免费免密钥，有限流） | 支持 | 支持 |
| Solana | 自建 JSON-RPC | 支持 | 支持 |
| HyperEVM | JSON-RPC（免费） | 不支持 | 支持 |

数据源的选择原因：Blockscout 的持仓榜接口免费且自带地址标签（交易所、跨链桥、DEX、协议），可以直接用来区分"庄家控盘"和"交易所代持"；Blockchair 是少数免费提供 UTXO 链地址富豪榜排序的接口；而 HyperEVM 目前没有免费的持仓榜 API，只能监控已知地址的余额。

### 集中度怎么算

扫描会先剔除以下地址，再计算"单地址集中度"：

- 交易所、跨链桥、DEX 池、借贷协议、质押、托管等多人共用地址（按标签识别）
- 名称里带交易所/桥关键词的地址（兜底识别，因为部分交易所钱包在 Blockscout 上没有 exchange 分类标签）
- 销毁地址与 `exclude_addresses` 里手动列出的地址

报告里会同时给出两种口径：

- **全部地址口径**：前 1 / 前 5 / 前 10 大地址合计占比，包含交易所
- **最大非基础设施地址**：剔除上述地址后，单个地址占流通盘的百分比，这才是真正的控盘信号
- **评分**：`max(单地址占比/35%, 1) × 65 + max(非基础设施前十大占比/80%, 1) × 35`，满分 100

### 命令

```text
/whale scan <链>:<代币> [数量]       扫描持仓集中度，代币可填符号或合约，例如 /whale scan arbitrum:ARB
/whale find [链] <关键词>            模糊检索代币合约，例如 /whale find arbitrum ARB
/whale add <编号> [别名]             把扫描结果里第 N 个地址加入余额监控
/whale add <链>:<代币> <地址> [别名]  直接监控某个链上地址
/whale list                          查看监控地址与订阅代币
/whale check                         立即查询一次链上余额
/whale del <编号|地址>               移除监控地址
/whale watch <链>:<代币> [别名]      订阅代币，定期复扫筹码结构
/whale unwatch <编号|链:代币>        取消订阅
/whale chains                        查看当前启用的链
```

代币标识的写法是 `链:代币`；UTXO 链没有合约地址，用 `native` 表示主币，例如 `zcash:native`、`bitcoin:native`。

### 代币怎么写

`链:代币` 里的代币支持三种写法，不用去翻合约地址：

1. **符号** —— `arbitrum:ARB`、`ethereum:USDC`。程序会用 Blockscout 的检索接口解析成合约地址，解析结果标注在报告顶部（`ARB → 0x912CE591…49E6548`）。
2. **合约地址** —— `0x` 开头 40 位十六进制，直接使用，不做检索。
3. **原生币** —— `native`，或本链符号（`HYPE`、`SOL`、`ETH`、`MATIC`、`ZEC` 等）。

同名代币很常见（大量假币会抄符号），解析规则是：符号精确匹配优先，其次按名称，最后按市值排序；如果精确同名有多个，只有当市值最高那个明显占优时才自动选中，否则列出候选让你点选。Web 面板里点一下候选就会自动填入合约地址并重新扫描。

### 链上成交监控

被跟踪地址的转入/转出会被记录成明细，包含方向、对手方、数量、时间和区块浏览器链接。首次检查只建立基线，之后出现新成交才会告警，避免把历史记录一次性推完。

数据来源与持仓榜一致：EVM 链走 Blockscout，UTXO 链走 Blockchair。**HyperEVM 目前没有免费的成交接口，只做余额监控。**

成交监控的请求量和余额检查相当（每地址每轮 1～2 次），如果数据源开始限流，可以把 `watch_interval_minutes` 调大，或者在设置页直接关掉成交监控。

### 告警行为

- 地址余额首次检查只写入基线，之后变化超过 `min_delta_pct`（默认 2%）或 `min_delta_abs` 才告警。
- 订阅代币会按 `scan_interval_hours`（默认 6 小时）复扫；当"最大非基础设施地址"换人或占比变动超过 `concentration_threshold`（默认 3 个百分点）时告警。
- 监控地址的轮询间隔由 `watch_interval_minutes`（默认 10 分钟）控制。

### 注意事项

- **Zcash 的链上集中度有天然盲区**：屏蔽池（shielded pool）里的余额不属于任何透明地址，所以透明地址的集中度会显著低于实际持仓集中度。用 `/whale scan zcash:native` 看到的是透明地址口径。
- **Blockchair 限流**：免费额度按 IP 计算，共享出口 IP 容易被临时拉黑。程序遇到限流会明确报错并跳过这一轮，不影响其他链；可以配置 `blockchair_key` 或减少 `blockchair_chains`。
- **Solana 必须自备 RPC**：公共节点普遍禁用了 `getTokenLargestAccounts`，请在 `[whales] solana_rpc` 填入自己的 RPC 地址，否则 Solana 不会出现在可用链里。
- **HyperEVM 只能监控不能扫描**：没有免费持仓榜接口，但可以用 `/whale add hyperevm:native <地址>` 监控 HYPE 余额。
- 所有请求都会走 `[proxy]` 里配置的代理。
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

5. 用 systemd 托管。仓库里带两个单元，**它们是独立的服务**：

| 单元 | 作用 | 默认监听 |
| --- | --- | --- |
| `hlmonitor.service` | Telegram Bot | 无（长轮询出站） |
| `hlmonitor-web.service` | Web 面板 | `127.0.0.1:8787` |

```bash
cd /opt/hlmonitor
sudo cp deploy/hlmonitor.service deploy/hlmonitor-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hlmonitor hlmonitor-web
sudo systemctl status hlmonitor hlmonitor-web
journalctl -u hlmonitor -f          # Bot 日志
journalctl -u hlmonitor-web -f      # Web 日志
```

拆成两个单元是有意的：静态文件改动只需刷新浏览器，但 Python 代码改动要重启进程才能生效，两边可以各自重启，互不影响。

服务按 `hlmonitor` 用户运行，工作目录是 `/opt/hlmonitor`，数据（SQLite）会存在 `/opt/hlmonitor/data/`，记得备份这个目录。两个服务共用同一个库，程序已开启 WAL 模式并设置 `busy_timeout`，可以安全并发读写。

Bot 使用长轮询主动连接 Telegram API，服务器不需要开放任何入站端口，只要出站 HTTPS 正常即可。

### 访问 Web 面板

`hlmonitor-web.service` 默认只监听 `127.0.0.1:8787`，也就是只能在服务器本机访问。**Web 面板本身没有任何鉴权**，所以不要直接把 `--host` 改成 `0.0.0.0` 暴露到公网。

推荐在服务器前面加一层带认证的反向代理，例如 Caddy：

```caddy
hl.example.com {
    basic_auth {
        yourname <bcrypt哈希>
    }
    reverse_proxy 127.0.0.1:8787
}
```

只想临时从本地看，用 SSH 端口转发更省事：

```bash
ssh -N -L 8787:127.0.0.1:8787 hlmonitor@你的服务器
# 然后本地打开 http://127.0.0.1:8787
```

### 改完代码后怎么生效

- **只改了前端**（`web_static/` 下的 html/css/js）：浏览器刷新即可，不用重启。
- **改了 Python**：`sudo systemctl restart hlmonitor hlmonitor-web`。
- **改了 `deploy/*.service`**：`sudo systemctl daemon-reload && sudo systemctl restart hlmonitor hlmonitor-web`。

Telegram 里的 `/update` 只会拉代码并重启 Bot 进程，**不会重启 Web 服务**（重启 systemd 单元需要 root）。所以用 `/update` 更新后，记得手动执行一次 `sudo systemctl restart hlmonitor-web`，否则 Web 会继续跑旧代码。

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
