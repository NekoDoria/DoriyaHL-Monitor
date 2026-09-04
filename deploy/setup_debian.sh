#!/usr/bin/env bash
#
# Hyperliquid 地址监控 —— Debian 13 (ARM) 一键部署脚本
#
# 自动完成：
#   1. 安装系统依赖 (python3 / python3-venv / python3-pip)
#   2. 把项目安装到 /opt/hlmonitor（可用 -d 自定义）
#   3. 创建专用运行用户 hlmonitor
#   4. 创建 .venv 虚拟环境并安装 requirements.txt
#   5. 首次生成 config.toml（无本地代理时自动改为直连）
#   6. 运行自检
#   7. 安装 systemd 服务并设为开机自启
#
# 用法（在项目 deploy/ 目录下或项目内任意位置）：
#   sudo bash setup_debian.sh                       # 默认安装到 /opt/hlmonitor
#   sudo bash setup_debian.sh -d /srv/hlmonitor     # 自定义安装目录
#   sudo bash setup_debian.sh --start               # 完成后立即启动服务
#   sudo bash setup_debian.sh -p                    # 保留示例配置里的代理设置
#
set -euo pipefail

APP_DIR="/opt/hlmonitor"
SERVICE_USER="hlmonitor"
AUTO_START=0
KEEP_PROXY=0

# ---------- 输出与参数 ----------
if [ -t 1 ]; then
  C_INFO=$'\033[1;36m'
  C_OK=$'\033[1;32m'
  C_WARN=$'\033[1;33m'
  C_ERR=$'\033[1;31m'
  C_OFF=$'\033[0m'
else
  C_INFO=""; C_OK=""; C_WARN=""; C_ERR=""; C_OFF=""
fi

say()  { printf "%b[setup]%b %s\n" "$C_INFO" "$C_OFF" "$*"; }
ok()   { printf "%b[  OK ]%b %s\n" "$C_OK" "$C_OFF" "$*"; }
warn() { printf "%b[警告]%b %s\n" "$C_WARN" "$C_OFF" "$*"; }
die()  { printf "%b[错误]%b %s\n" "$C_ERR" "$C_OFF" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
用法: sudo bash setup_debian.sh [选项]

一键部署 Hyperliquid 地址监控到 Debian 13 (ARM) 服务器。

选项:
  -d, --dir DIR      安装目录（默认 /opt/hlmonitor）
  -s, --start        部署完成后立即启动服务
  -p, --keep-proxy   保留示例配置中的代理设置（默认自动探测本机
                      127.0.0.1:7890，探测不到就关闭代理直连）
  -h, --help         显示帮助
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    -d|--dir)
      [ "$#" -ge 2 ] || die "选项 $1 需要一个目录参数"
      APP_DIR="$2"
      shift 2
      ;;
    -s|--start)
      AUTO_START=1
      shift
      ;;
    -p|--keep-proxy)
      KEEP_PROXY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "未知选项: $1（用 -h 查看帮助）"
      ;;
  esac
done

# ---------- 前置检查 ----------
[ "$(id -u)" -eq 0 ] || die "需要 root 权限，请用 sudo 运行：sudo bash $0"

if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
fi
if [ "${ID:-}" != "debian" ]; then
  die "当前系统不是 Debian（检测到: ${ID:-未知}），本脚本只支持 Debian。"
fi
DEB_MAJOR="${VERSION_ID:-0}"
DEB_MAJOR="${DEB_MAJOR%%.*}"
case "$DEB_MAJOR" in
  ''|*[!0-9]*) DEB_MAJOR=0 ;;
esac
if [ "$DEB_MAJOR" -lt 13 ]; then
  warn "当前是 ${PRETTY_NAME:-Debian $VERSION_ID}，脚本面向 Debian 13；继续前请确认系统软件可用。"
fi

case "$(uname -m)" in
  aarch64|arm64|armv7l|armv6l)
    say "检测到架构 $(uname -m)（ARM）"
    ;;
  *)
    warn "当前架构是 $(uname -m)，不是 ARM；依赖均为纯 Python，一般也能运行，但请自行确认。"
    ;;
esac

# 定位项目根目录（脚本放在项目 deploy/ 下，或项目任意子目录均可）
resolve_project_root() {
  local d
  d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  while [ ! -f "$d/requirements.txt" ] || [ ! -d "$d/hlmonitor" ]; do
    [ "$d" = "/" ] && return 1
    d="$(dirname "$d")"
  done
  printf '%s\n' "$d"
}
PROJECT_ROOT="$(resolve_project_root)" \
  || die "找不到项目根目录：请确认脚本位于项目内（项目包含 hlmonitor/ 与 requirements.txt）"

APP_DIR="$(readlink -f "$APP_DIR")"

say "项目根目录: $PROJECT_ROOT"
say "安装目录  : $APP_DIR"

# ---------- 1/8 系统依赖 ----------
say "[1/8] 安装系统依赖 (python3 / python3-venv / python3-pip) ..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq || apt-get update
apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip ca-certificates git
ok "系统依赖安装完成"

# ---------- 2/8 复制项目 ----------
mkdir -p "$APP_DIR"
say "[2/8] 准备安装目录 $APP_DIR ..."
if [ "$PROJECT_ROOT" != "$APP_DIR" ]; then
  say "从项目目录同步文件（保留 .git，跳过 .venv / data / config.toml）"
  tar -C "$PROJECT_ROOT" \
      --exclude='.venv' \
      --exclude='venv' \
      --exclude='data' \
      --exclude='config.toml' \
      --exclude='__pycache__' \
      --exclude='*.pyc' \
      --exclude='*.zip' \
      --exclude='*.log' \
      -cf - . | tar -C "$APP_DIR" -xf -
else
  say "项目已在目标目录，跳过复制"
fi
cd "$APP_DIR"
ok "项目文件就绪"

# ---------- 3/8 运行用户 ----------
say "[3/8] 创建运行用户 $SERVICE_USER ..."
if ! getent passwd "$SERVICE_USER" >/dev/null; then
  getent group "$SERVICE_USER" >/dev/null || groupadd --system "$SERVICE_USER"
  useradd --system -g "$SERVICE_USER" -d "$APP_DIR" -s /usr/sbin/nologin "$SERVICE_USER"
  ok "已创建用户 $SERVICE_USER"
else
  say "用户 $SERVICE_USER 已存在，复用"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

# ---------- 4/8 虚拟环境 ----------
VENV_PY="$APP_DIR/.venv/bin/python"
say "[4/8] 创建 Python 虚拟环境 .venv ..."
if [ -x "$VENV_PY" ]; then
  say "虚拟环境已存在，跳过创建"
else
  runuser -u "$SERVICE_USER" -- \
    env HOME="$APP_DIR" XDG_CACHE_HOME="$APP_DIR/.cache" \
    python3 -m venv "$APP_DIR/.venv"
fi
ok "虚拟环境就绪"

# ---------- 5/8 Python 依赖 ----------
say "[5/8] 安装 Python 依赖 (pip install -r requirements.txt) ..."
if ! runuser -u "$SERVICE_USER" -- \
    env HOME="$APP_DIR" XDG_CACHE_HOME="$APP_DIR/.cache" \
    "$VENV_PY" -m pip install --disable-pip-version-check \
    -r "$APP_DIR/requirements.txt"; then
  warn "依赖安装失败。若为网络原因，可重试："
  printf '  国外服务器直连:\n    runuser -u %s -- env HOME=%s %s -m pip install -r %s/requirements.txt\n' \
    "$SERVICE_USER" "$APP_DIR" "$VENV_PY" "$APP_DIR"
  printf '  国内服务器用镜像:\n    runuser -u %s -- env HOME=%s %s -m pip install -r %s/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple\n' \
    "$SERVICE_USER" "$APP_DIR" "$VENV_PY" "$APP_DIR"
  exit 1
fi
ok "Python 依赖安装完成"

# ---------- 6/8 配置文件 ----------
say "[6/8] 处理配置文件 config.toml ..."
if [ -f "$APP_DIR/config.toml" ]; then
  say "config.toml 已存在，保留现有配置不动"
else
  cp "$APP_DIR/config.example.toml" "$APP_DIR/config.toml"
  chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/config.toml"
  if [ "$KEEP_PROXY" -eq 1 ]; then
    say "已按 -p 保留示例配置中的代理设置"
  elif timeout 2 bash -c 'exec 3<>/dev/tcp/127.0.0.1/7890' 2>/dev/null; then
    say "检测到本机 7890 代理端口，保留 proxy.enabled = true"
  else
    sed -i '/^\[proxy\]/,/^\[/ s/^enabled = true/enabled = false/' "$APP_DIR/config.toml"
    say "未检测到本机 7890 代理，已设置 proxy.enabled = false（服务器直连）"
  fi
fi

# ---------- 7/8 自检 ----------
say "[7/8] 运行自检 (python -m hlmonitor --version) ..."
if ! runuser -u "$SERVICE_USER" -- \
    env HOME="$APP_DIR" XDG_CACHE_HOME="$APP_DIR/.cache" \
    "$VENV_PY" -m hlmonitor --version; then
  die "自检失败，请根据上方报错排查（或把报错发出来）"
fi
ok "自检通过"

# ---------- 8/8 systemd 服务 ----------
if command -v systemctl >/dev/null 2>&1; then
  say "[8/8] 安装 systemd 服务（开机自启）..."
  if [ -f "$APP_DIR/deploy/hlmonitor.service" ]; then
    sed "s|/opt/hlmonitor|$APP_DIR|g" \
      "$APP_DIR/deploy/hlmonitor.service" > /etc/systemd/system/hlmonitor.service
    systemctl daemon-reload
    systemctl enable hlmonitor >/dev/null 2>&1
    if [ "$AUTO_START" -eq 1 ]; then
      systemctl restart hlmonitor
      ok "服务已启动（systemctl status hlmonitor 查看状态）"
    else
      say "服务已设为开机自启；改好配置后执行：sudo systemctl start hlmonitor"
    fi
  else
    warn "未找到 deploy/hlmonitor.service，跳过 systemd 配置"
  fi
else
  warn "当前系统没有 systemctl，跳过 systemd 配置"
fi

cat <<EOF

============================================================
  部署完成

  安装目录 : $APP_DIR
  运行用户 : $SERVICE_USER
  配置文件 : $APP_DIR/config.toml
  虚拟环境 : $APP_DIR/.venv
  系统服务 : hlmonitor.service（已开机自启）

  接下来：
    1. 编辑配置：
         sudo nano $APP_DIR/config.toml
       至少填写 [alerts.telegram] 的 bot_token；按需修改地址与告警设置。
    2. 启动服务：
         sudo systemctl start hlmonitor
    3. 查看日志：
         journalctl -u hlmonitor -f
    4. 命令行快速验证一次：
         sudo runuser -u $SERVICE_USER -- $VENV_PY -m hlmonitor --once --address 0x你的地址

  提示：服务通过出站连接工作，不需要开放任何入站端口。
============================================================
EOF