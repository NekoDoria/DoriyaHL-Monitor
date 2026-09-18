const state = {
  accounts: [],
  selected: localStorage.getItem("hl.selected") || "",
  view: "overview",
  fillsWindow: "1440",
  ordersLevel: "auto",
  chartCoin: "",
  chartInterval: "15m",
  fillWindow: localStorage.getItem("hl.fillWindow") || "1440",
  merge: Math.min(4, Math.max(0.25, parseFloat(localStorage.getItem("hl.merge")) || 1)),
  chartData: null,
  whaleChain: localStorage.getItem("hl.whaleChain") || "",
  webChatId: "__web__",
  whaleData: null,
  whaleScan: null,
  settingsData: null,
  wtaAsset: localStorage.getItem("hl.wtaAsset") || "",
  wtaWindow: "30d",
  settingsInputs: null,
  theme: null,
  overlays: { orders: true, fills: true, tpsl: true, volume: true, whaleOrders: false, whaleFills: false },
  busy: false,
  chart: null,
  candleSeries: null,
  volumeSeries: null,
  priceLines: [],
  zoneRects: [],
  zonePopupRow: null,
  activeZone: null,
  overlayFrame: null,
};

const els = {
  sidebar: document.getElementById("sidebar"),
  sidebarToggle: document.getElementById("sidebar-toggle"),
  sidebarBackdrop: document.getElementById("sidebar-backdrop"),
  refresh: document.getElementById("refresh-button"),
  accountForm: document.getElementById("account-form"),
  accountFormToggle: document.getElementById("toggle-account-form"),
  accountAddress: document.getElementById("account-address"),
  accountAlias: document.getElementById("account-alias"),
  accountList: document.getElementById("account-list"),
  viewNav: document.getElementById("view-nav"),
  network: document.getElementById("network-badge"),
  version: document.getElementById("version"),
  currentAccount: document.getElementById("current-account"),
  currentAddress: document.getElementById("current-address"),
  updatedAt: document.getElementById("updated-at"),
  fillsWindow: document.getElementById("fills-window"),
  ordersLevel: document.getElementById("orders-level"),
  chartSymbol: document.getElementById("chart-symbol"),
  chartSymbolLabel: document.getElementById("chart-symbol-label"),
  chartInterval: document.getElementById("chart-interval"),
  chartOverlays: document.getElementById("chart-overlays"),
  chartContainer: document.getElementById("chart-container"),
  priceChart: document.getElementById("price-chart"),
  zoneLayer: document.getElementById("zone-layer"),
  zoneTooltip: document.getElementById("zone-tooltip"),
  zonePopup: document.getElementById("zone-popup"),
  chartLegend: document.getElementById("chart-legend"),
  chartRefresh: document.getElementById("chart-refresh"),
  chartFullscreen: document.getElementById("chart-fullscreen"),
  chartSideToggle: document.getElementById("chart-side-toggle"),
  autohuntProcess: document.getElementById("autohunt-process"),
  chartFillWindow: document.getElementById("chart-fill-window"),
  fillWindowValue: document.getElementById("fill-window-value"),
  mergeSlider: document.getElementById("merge-slider"),
  mergeValue: document.getElementById("merge-value"),
  positionHitbox: document.getElementById("position-hitbox"),
  positionTooltip: document.getElementById("position-tooltip"),
  positionPopup: document.getElementById("position-popup"),
  priceAutoButton: document.getElementById("price-auto-button"),
  whaleChain: document.getElementById("whale-chain"),
  whaleToken: document.getElementById("whale-token"),
  whaleScan: document.getElementById("whale-scan"),
  whaleCheck: document.getElementById("whale-check"),
  settingsSave: document.getElementById("settings-save"),
  settingsReset: document.getElementById("settings-reset"),
  wtaAsset: document.getElementById("wta-asset"),
  wtaWindow: document.getElementById("wta-window"),
  wtaRefresh: document.getElementById("wta-refresh"),
  brandText: document.getElementById("brand-text"),
};

function chartPanel() {
  return panel("chart");
}

function setSidebarOpen(open) {
  els.sidebar.classList.toggle("open", open);
  els.sidebarBackdrop.hidden = !open;
}
function syncChartFullscreen(active) {
  const node = chartPanel();
  node.classList.toggle("fullscreen", active);
  els.chartSideToggle.hidden = !active;
  node.classList.remove("side-collapsed");
  setTimeout(() => {
    if (state.chart) {
      state.chart.applyOptions({
        width: els.priceChart.clientWidth,
        height: els.priceChart.clientHeight,
      });
    }
  }, 0);
}

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

const qty = new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 });
const priceUsd = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 8,
});

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function priceText(value) {
  const number = Number(value);
  return number > 0 ? priceUsd.format(number) : "-";
}

function shortAddress(address) {
  return address ? `${address.slice(0, 6)}...${address.slice(-4)}` : "";
}

// 金额风格由设置页统一控制，全站只走这一条格式化路径。
const AMOUNT_FORMATS = ["cn", "compact", "full"];
const AMOUNT_FORMAT_LABELS = { cn: "中文单位", compact: "英文紧凑", full: "完整数字" };

function amountFormat() {
  const style = (state.theme && state.theme.amount_format) || "compact";
  return AMOUNT_FORMATS.includes(style) ? style : "compact";
}

function formatAmount(value) {
  const raw = Number(value);
  const number = Number.isFinite(raw) ? raw : 0;
  const abs = Math.abs(number);
  const sign = number < 0 ? "-" : "";
  const style = amountFormat();
  if (style === "full") return sign + usd.format(abs);
  if (style === "cn") {
    if (abs >= 100000000) return sign + "$" + (abs / 100000000).toFixed(2) + "亿";
    if (abs >= 10000000) return sign + "$" + (abs / 10000000).toFixed(2) + "千万";
    if (abs >= 1000000) return sign + "$" + (abs / 1000000).toFixed(2) + "百万";
    if (abs >= 10000) return sign + "$" + (abs / 10000).toFixed(2) + "万";
    return sign + usd.format(abs);
  }
  if (abs >= 1000000000) return sign + "$" + (abs / 1000000000).toFixed(2) + "B";
  if (abs >= 1000000) return sign + "$" + (abs / 1000000).toFixed(2) + "M";
  if (abs >= 1000) return sign + "$" + (abs / 1000).toFixed(2) + "K";
  return sign + usd.format(abs);
}

function priceFormat(value) {
  value = Number(value) || 0;
  const precision = value >= 1000 ? 2 : value >= 100 ? 3 : value >= 1 ? 4 : value >= 0.01 ? 5 : 7;
  return { type: "price", precision, minMove: Number((0.1 ** precision).toFixed(precision)) };
}

function signed(value, formatter = formatAmount) {
  const number = Number(value) || 0;
  const text = formatter(Math.abs(number));
  return number > 0 ? `+${text}` : number < 0 ? `-${text}` : text;
}

function pnlClass(value) {
  const number = Number(value) || 0;
  return number > 0 ? "positive" : number < 0 ? "negative" : "";
}

function timeText(value, withDate = true) {
  if (!value) return "-";
  const options = withDate
    ? { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }
    : { hour: "2-digit", minute: "2-digit" };
  return new Intl.DateTimeFormat("zh-CN", options).format(new Date(Number(value)));
}

function sideText(row) {
  if (row.dir) return row.dir;
  if (Number(row.szi) > 0) return "做多";
  if (Number(row.szi) < 0) return "做空";
  const side = String(row.side || "").toUpperCase();
  return side === "B" ? "做多" : side === "A" ? "做空" : "-";
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

// 静态文件是热更新的，但 Python 路由只在新进程里生效；
// 命中这个提示说明页面比后端新，需要重启服务。
const RESTART_HINT =
  "后端进程仍是旧版本，请重启 python -m hlmonitor.web 后刷新页面"
  + "（静态文件会热更新，Python 路由不会）。";

function apiErrorText(error) {
  const message = String((error && error.message) || error || "未知错误");
  return /API not found/i.test(message) ? RESTART_HINT : message;
}

function selectedAccount() {
  return state.accounts.find((account) => account.address === state.selected) || null;
}

function accountLabel(account) {
  return account.alias || shortAddress(account.address);
}

function renderContext() {
  const account = selectedAccount();
  els.currentAccount.textContent = account ? accountLabel(account) : "选择账户";
  els.currentAddress.textContent = account ? account.address : "—";
}

// 仪表盘展示的是所有来源的账户并集，标出来源避免误会。
const ACCOUNT_SOURCE_BADGES = {
  telegram: {
    label: "TG",
    hint: (account) => `来自 Telegram（${account.chat_count || 1} 个聊天），移除会同时取消那边的订阅`,
  },
  both: {
    label: "TG+Web",
    hint: (account) => `网页和 Telegram（${account.chat_count || 2} 个聊天）都订阅了，移除会一并取消`,
  },
  web: {
    label: "Web",
    hint: () => "在网页面板添加",
  },
};

function renderAccounts() {
  els.accountList.replaceChildren();
  if (!state.accounts.length) {
    els.accountList.append(make("div", "empty-note", "暂无账户"));
    return;
  }
  for (const account of state.accounts) {
    const item = make("div", `account-item${account.address === state.selected ? " active" : ""}`);
    item.setAttribute("role", "button");
    item.setAttribute("tabindex", "0");
    const text = make("div", "account-text");
    const name = make("div", "account-name", accountLabel(account));
    const sourceBadge = ACCOUNT_SOURCE_BADGES[account.source];
    if (sourceBadge) {
      const badge = make("span", `account-source ${account.source}`, sourceBadge.label);
      badge.title = sourceBadge.hint(account);
      name.append(badge);
    }
    text.append(name);
    text.append(make("div", "account-address", shortAddress(account.address)));
    item.append(
      make("span", "account-avatar", (account.alias || account.address.slice(2, 4)).slice(0, 2).toUpperCase()),
      text,
    );
    if (account.source !== "config") {
      const remove = make("button", "remove-account", "×");
      remove.title = account.source === "web" ? "移除" : "移除（会同时取消 Telegram 那边的订阅）";
      remove.addEventListener("click", async (event) => {
        event.stopPropagation();
        try {
          await request(`/api/accounts/${account.address}`, { method: "DELETE" });
          if (state.selected === account.address) state.selected = "";
          await loadState();
          loadView(true);
        } catch (error) {
          showState(state.view, "error", error.message);
        }
      });
      item.append(remove);
    }
    const select = () => {
      state.selected = account.address;
      localStorage.setItem("hl.selected", state.selected);
      state.chartCoin = "";
      renderAccounts();
      renderContext();
      setSidebarOpen(false);
      loadView(true);
    };
    item.addEventListener("click", select);
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select();
      }
    });
    els.accountList.append(item);
  }
}

function panel(view) {
  return document.querySelector(`.panel[data-panel="${view}"]`);
}

function setStateLoading(view) {
  const stateNode = panel(view).querySelector(".panel-state");
  stateNode.replaceChildren();
  const loading = make("div", "state-loading");
  loading.append(make("i"), make("i"), make("i"), make("span", "", "加载中"));
  stateNode.append(loading);
}

function showState(view, kind, message) {
  const stateNode = panel(view).querySelector(".panel-state");
  stateNode.replaceChildren();
  if (kind === "error") stateNode.append(make("div", "state-error", message));
  else if (kind === "empty") stateNode.append(make("div", "state-empty", message));
}

function clearState(view) {
  panel(view).querySelector(".panel-state").replaceChildren();
}

function setUpdatedAt(value) {
  els.updatedAt.textContent = `更新 ${timeText(Number(value) || Date.now(), false)}`;
}

function metric(label, value, className = "") {
  const item = make("div", "metric");
  item.append(make("div", "metric-label", label));
  item.append(make("div", `metric-value ${className}`.trim(), value));
  return item;
}

function table(headers, rows) {
  const wrap = make("div", "data-table-wrap");
  const node = make("table", "data-table");
  const thead = make("thead");
  const headRow = make("tr");
  headers.forEach((header) => headRow.append(make("th", "", header)));
  thead.append(headRow);
  const tbody = make("tbody");
  if (!rows.length) {
    const row = make("tr");
    const cell = make("td", "table-note", "暂无数据");
    cell.colSpan = headers.length;
    row.append(cell);
    tbody.append(row);
  } else {
    rows.forEach((cells) => {
      const row = make("tr");
      cells.forEach((cell) => row.append(cell));
      tbody.append(row);
    });
  }
  node.append(thead, tbody);
  wrap.append(node);
  return wrap;
}

function cell(value, className = "") {
  return make("td", className, value);
}

function sectionTitle(text) {
  return make("div", "section-title", text);
}

function renderOverview(data, body) {
  const summary = data.summary || {};
  const metrics = make("div", "metrics");
  metrics.append(
    metric("账户净值", formatAmount(summary.account_value)),
    metric("可提取", formatAmount(summary.withdrawable)),
    metric("浮动盈亏", signed(summary.unrealized_pnl), pnlClass(summary.unrealized_pnl)),
    metric("持仓名义", formatAmount(summary.total_ntl_pos)),
  );
  body.append(metrics, sectionTitle("合约持仓"));
  const rows = data.positions.map((row) => [
    cell(row.coin),
    cell(sideText(row)),
    cell(qty.format(Math.abs(row.szi))),
    cell(formatAmount(row.notional)),
    cell(row.entry || "-"),
    cell(row.leverage ? `${row.leverage}x` : "-"),
    cell(signed(row.pnl), pnlClass(row.pnl)),
  ]);
  body.append(table(["币种", "方向", "数量", "价值", "开仓均价", "杠杆", "浮动盈亏"], rows));
  if (data.spot.length) {
    body.append(sectionTitle("现货余额"));
    body.append(table(["币种", "余额", "冻结"], data.spot.slice(0, 30).map((row) => [
      cell(row.coin), cell(qty.format(row.total)), cell(qty.format(row.hold)),
    ])));
  }
}

function renderFills(data, body) {
  const metrics = make("div", "metrics");
  metrics.append(
    metric("成交额", formatAmount(data.notional)),
    metric("成交笔数", String(data.count)),
    metric("已实现盈亏", signed(data.realized_pnl), pnlClass(data.realized_pnl)),
    metric("窗口", data.window_label),
  );
  body.append(metrics, sectionTitle("币种统计"));
  body.append(table(["币种", "笔数", "成交额", "买入", "卖出", "盈亏"], data.coins.slice(0, 20).map((row) => [
    cell(row.coin), cell(String(row.count)), cell(formatAmount(row.notional)),
    cell(formatAmount(row.buy)), cell(formatAmount(row.sell)), cell(signed(row.pnl), pnlClass(row.pnl)),
  ])));
  body.append(sectionTitle("最近成交"));
  body.append(table(["时间", "币种", "方向", "数量", "价格", "金额", "盈亏"], data.recent.slice(0, 30).map((row) => [
    cell(timeText(row.time)), cell(row.coin), cell(sideText(row)), cell(qty.format(row.size)),
    cell(qty.format(row.price)), cell(formatAmount(row.notional)), cell(signed(row.closed_pnl), pnlClass(row.closed_pnl)),
  ])));
}

function renderEvents(data, body) {
  const list = make("div", "event-list");
  if (!data.events.length) list.append(make("div", "event-item", "暂无事件"));
  for (const event of data.events) {
    const item = make("div", "event-item");
    const meta = make("div", "event-meta");
    meta.append(make("span", "", event.kind || "event"), make("span", "", timeText(event.time)));
    item.append(meta, make("div", "", event.text || ""));
    list.append(item);
  }
  body.append(list);
}

function ensureChart() {
  if (!window.LightweightCharts) throw new Error("图表库未加载");
  if (state.chart) return;
  state.chart = LightweightCharts.createChart(els.priceChart, {
    layout: { background: { type: "solid", color: "#181818" }, textColor: "#9b9b9b", fontSize: 12 },
    grid: { vertLines: { color: "#252525" }, horzLines: { color: "#252525" } },
    rightPriceScale: { borderColor: "#303030", scaleMargins: { top: 0.08, bottom: 0.24 } },
    timeScale: { borderColor: "#303030", timeVisible: true, secondsVisible: false, rightOffset: 6 },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    handleScroll: { mouseWheel: true, pressedMouseMove: true },
    handleScale: { mouseWheel: true, pinch: true },
  });
  state.candleSeries = state.chart.addSeries(LightweightCharts.CandlestickSeries, {
    upColor: "#1d8f70", downColor: "#b54848", borderVisible: false,
    wickUpColor: "#1d8f70", wickDownColor: "#b54848",
  });
  state.volumeSeries = state.chart.addSeries(LightweightCharts.HistogramSeries, {
    priceScaleId: "volume", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false,
  });
  state.chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  const observer = new ResizeObserver(() => {
    state.chart.applyOptions({
      width: els.priceChart.clientWidth,
      height: els.priceChart.clientHeight,
    });
    updatePositionOverlay();
    updateOrderZoneOverlays();
  });
  observer.observe(els.priceChart);
  state.chart.subscribeCrosshairMove(() => {
    updatePositionOverlay();
    updateOrderZoneOverlays();
  });
  state.chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
    updatePositionOverlay();
    updateOrderZoneOverlays();
  });
  startOverlayLoop();
  applyTheme(state.theme);
}

function clearPriceLines() {
  for (const line of state.priceLines) {
    try { state.candleSeries.removePriceLine(line); } catch (_) {}
  }
  state.priceLines = [];
}

function addPriceLine(price, color, title, width = 1, dashed = true) {
  if (!(Number(price) > 0) || !state.candleSeries) return;
  state.priceLines.push(state.candleSeries.createPriceLine({
    price: Number(price),
    color,
    lineWidth: width,
    lineStyle: dashed ? LightweightCharts.LineStyle.Dashed : LightweightCharts.LineStyle.Solid,
    axisLabelVisible: true,
    title,
  }));
}

function zoneColor(row) {
  if (row.kind === "order") return row.side_raw === "B" ? "#38d1a7" : "#ff7a7a";
  return row.side_raw === "B" ? "#7ee0c0" : "#ffa2a2";
}

function addRange(row) {
  const color = zoneColor(row);
  const label = `${row.side} ${row.count}笔`;
  if (Math.abs(row.max_px - row.min_px) < 1e-12) {
    addPriceLine(row.avg_px, color, `${label} ${priceText(row.avg_px)}`, 2);
    return;
  }
  addPriceLine(row.max_px, color, `${label} 上沿`, 1);
  addPriceLine(row.min_px, color, `${label} 下沿`, 1);
  addPriceLine(row.avg_px, color, `${label} 均价`, 2);
}

function hideZoneTooltip() {
  els.zoneTooltip.hidden = true;
}

function hideZonePopup() {
  els.zonePopup.hidden = true;
  els.zonePopup.replaceChildren();
  state.zonePopupRow = null;
}

function clearOrderZoneOverlays() {
  els.zoneLayer.replaceChildren();
  state.zoneRects = [];
  state.activeZone = null;
}

function startOverlayLoop() {
  if (state.overlayFrame !== null) return;
  const tick = () => {
    updatePositionOverlay();
    updateOrderZoneOverlays();
    updateAutoButton();
    state.overlayFrame = requestAnimationFrame(tick);
  };
  state.overlayFrame = requestAnimationFrame(tick);
}

function updateAutoButton() {
  const geometry = plotGeometry();
  if (!geometry) {
    els.priceAutoButton.hidden = true;
    return;
  }
  const priceWidth = state.chart.priceScale("right").width();
  const timeHeight = state.chart.timeScale().height();
  els.priceAutoButton.hidden = false;
  els.priceAutoButton.style.right = `${priceWidth + 7}px`;
  els.priceAutoButton.style.bottom = `${timeHeight + 8}px`;
}

function plotGeometry() {
  if (!state.chart) return null;
  const priceWidth = state.chart.priceScale("right").width();
  const timeHeight = state.chart.timeScale().height();
  return {
    width: Math.max(0, els.priceChart.clientWidth - priceWidth),
    height: Math.max(0, els.priceChart.clientHeight - timeHeight),
  };
}

function updateOrderZoneOverlays() {
  const geometry = plotGeometry();
  if (!geometry || !state.candleSeries) return;
  els.zoneLayer.style.width = `${geometry.width}px`;
  els.zoneLayer.style.height = `${geometry.height}px`;

  const placed = [];
  for (const item of state.zoneRects) {
    let top;
    let bottom;
    try {
      top = state.candleSeries.priceToCoordinate(Number(item.row.max_px));
      bottom = state.candleSeries.priceToCoordinate(Number(item.row.min_px));
    } catch (_) {
      top = NaN;
      bottom = NaN;
    }
    if (!Number.isFinite(top) || !Number.isFinite(bottom)) {
      item.node.hidden = true;
      continue;
    }
    const rectTop = Math.max(0, Math.min(top, bottom));
    const rectBottom = Math.min(geometry.height, Math.max(top, bottom));
    const height = Math.max(6, rectBottom - rectTop);
    if (rectTop > geometry.height || rectBottom < 0) {
      item.node.hidden = true;
      continue;
    }
    item.node.hidden = false;
    item.node.style.top = `${rectTop}px`;
    item.node.style.height = `${height}px`;
    item.node.style.width = `${geometry.width}px`;
    if (item.label) item.label.hidden = true;
    item.top = rectTop;
    item.height = height;
    placed.push({ item, top: rectTop, height });
  }

  // 只在与上一个标签不重叠时显示方向文字，避免密集价格带文字互相压住。
  placed.sort((a, b) => a.top - b.top);
  let lastBottom = -Infinity;
  for (const entry of placed) {
    if (entry.height < 6) continue;
    const above = entry.height < 15 && entry.top >= 15;
    const center = entry.top + entry.height / 2;
    const anchor = above ? entry.top - 7 : center;
    if (anchor - 7 < lastBottom) continue;
    const label = entry.item.label;
    label.hidden = false;
    label.classList.toggle("above", above);
    lastBottom = anchor + 7;
  }
}

// 成交区间回看窗口，与 K 线周期互相独立。
// 后端把窗口限制在 60 ~ 10080 分钟，这里只提供该区间内的选项。
const FILL_WINDOW_OPTIONS = [
  [60, "1小时"],
  [240, "4小时"],
  [1440, "1天"],
  [4320, "3天"],
  [10080, "1周"],
];

function syncFillWindowLabel() {
  const found = FILL_WINDOW_OPTIONS.find(([value]) => String(value) === String(state.fillWindow));
  if (els.fillWindowValue) els.fillWindowValue.textContent = found ? found[1] : "1天";
}

function initFillWindowSelect() {
  const select = els.chartFillWindow;
  if (!select) return;
  select.replaceChildren();
  for (const [value, label] of FILL_WINDOW_OPTIONS) {
    const option = make("option", "", label);
    option.value = String(value);
    select.append(option);
  }
  const allowed = FILL_WINDOW_OPTIONS.map(([value]) => String(value));
  if (!allowed.includes(String(state.fillWindow))) state.fillWindow = "1440";
  select.value = String(state.fillWindow);
  syncFillWindowLabel();
}
const ZONE_DIR_MAP = {
  "Open Long": "开多",
  "Close Long": "平多",
  "Open Short": "开空",
  "Close Short": "平空",
};

function zoneDirectionLabel(row) {
  if (row.kind === "whale") return row.side_raw === "B" ? "大户多" : "大户空";
  if (row.kind === "whale_fill") {
    const mapped = ZONE_DIR_MAP[String(row.dir || "")];
    if (mapped) return `大户${mapped}`;
    return row.side_raw === "B" ? "大户买入" : "大户卖出";
  }
  if (row.kind === "fill") {
    const mapped = ZONE_DIR_MAP[String(row.dir || "")];
    if (mapped) return mapped;
    return row.side_raw === "B" ? "开多" : "开空";
  }
  if (row.kind === "tpsl") return row.label || "止盈止损";
  return row.side_raw === "B" ? "挂多" : "挂空";
}

function zoneKindLabel(row) {
  if (row.kind === "whale") return "Autohunt 挂单区间";
  if (row.kind === "whale_fill") return "Autohunt 成交区间";
  if (row.kind === "fill") return "成交区间";
  if (row.kind === "tpsl") return row.label || "止盈止损";
  return "挂单区间";
}
function zoneTooltipText(row) {
  const accounts = row.accounts ? ` · ${row.accounts}账户` : "";
  return `${zoneKindLabel(row)} · ${zoneDirectionLabel(row)} · ${row.count}笔${accounts} · ${formatAmount(row.total_value)}`;
}

function showZoneTooltip(event, row) {
  const tooltip = els.zoneTooltip;
  const containerRect = els.chartContainer.getBoundingClientRect();
  tooltip.textContent = zoneTooltipText(row);
  tooltip.hidden = false;
  const left = Math.min(
    Math.max(8, event.clientX - containerRect.left - tooltip.offsetWidth / 2),
    Math.max(8, els.chartContainer.clientWidth - tooltip.offsetWidth - 8),
  );
  const top = Math.min(
    Math.max(8, event.clientY - containerRect.top - tooltip.offsetHeight - 12),
    Math.max(8, els.chartContainer.clientHeight - tooltip.offsetHeight - 8),
  );
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
  tooltip.style.right = "";
}

function makeChartPopupDraggable(popup, handle) {
  handle.addEventListener("pointerdown", (start) => {
    if (start.button !== 0 || start.target.closest(".position-close")) return;
    const startX = start.clientX;
    const startY = start.clientY;
    const startLeft = popup.offsetLeft;
    const startTop = popup.offsetTop;
    handle.setPointerCapture(start.pointerId);
    handle.classList.add("dragging");

    const move = (moveEvent) => {
      const nextLeft = Math.min(
        Math.max(0, startLeft + moveEvent.clientX - startX),
        Math.max(0, els.chartContainer.clientWidth - popup.offsetWidth),
      );
      const nextTop = Math.min(
        Math.max(0, startTop + moveEvent.clientY - startY),
        Math.max(0, els.chartContainer.clientHeight - popup.offsetHeight),
      );
      popup.style.left = `${nextLeft}px`;
      popup.style.top = `${nextTop}px`;
    };
    const stop = () => {
      handle.classList.remove("dragging");
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  });
}

function renderZonePopup(row, event) {
  const popup = els.zonePopup;
  const title = make("div", "position-popup-head");
  const titleText = make("div", "position-popup-title");
  titleText.append(
    make("span", `position-side ${row.side_raw === "B" ? "long" : "short"}`, zoneDirectionLabel(row)),
    make("span", "", zoneKindLabel(row)),
  );
  const close = make("button", "position-close", "×");
  close.type = "button";
  close.setAttribute("aria-label", "关闭挂单区间详情");
  close.addEventListener("click", hideZonePopup);
  title.append(titleText, close);

  const single = Math.abs(Number(row.max_px) - Number(row.min_px)) < 1e-12;
  const details = make("div", "position-detail");
  details.append(
    positionDetailRow("笔数", String(row.count)),
    positionDetailRow(single ? "价格" : "价格区间", single ? priceText(row.min_px) : `${priceText(row.min_px)} – ${priceText(row.max_px)}`),
    positionDetailRow("加权均价", priceText(row.avg_px)),
    positionDetailRow("总数量", qty.format(row.total_sz)),
    positionDetailRow("总金额", formatAmount(row.total_value)),
  );
  const overlaps = zoneOverlapsAt(zonePointerY(event));
  if (overlaps.length > 1) {
    details.append(
      make(
        "div",
        "position-hint",
        `此处叠着 ${overlaps.length} 个区间，按住 Alt 点击可切换到下一个`,
      ),
    );
  }
  popup.replaceChildren(title, details);
  popup.hidden = false;
  popup.style.left = "12px";
  popup.style.top = "12px";

  const containerRect = els.chartContainer.getBoundingClientRect();
  const left = Math.min(
    Math.max(8, event.clientX - containerRect.left - popup.offsetWidth / 2),
    Math.max(8, els.chartContainer.clientWidth - popup.offsetWidth - 8),
  );
  const top = Math.min(
    Math.max(8, event.clientY - containerRect.top + 14),
    Math.max(8, els.chartContainer.clientHeight - popup.offsetHeight - 8),
  );
  popup.style.left = `${left}px`;
  popup.style.top = `${top}px`;
  makeChartPopupDraggable(popup, title);
}

function zonePointerY(event) {
  const rect = els.priceChart.getBoundingClientRect();
  return event.clientY - rect.top;
}

function setActiveZone(item) {
  if (state.activeZone === item) return;
  if (state.activeZone && state.activeZone.node) {
    state.activeZone.node.classList.remove("active");
  }
  state.activeZone = item || null;
  if (state.activeZone && state.activeZone.node) {
    state.activeZone.node.classList.add("active");
  }
}

// 同一纵向位置上可能叠着好几个区间（都是全宽横条），
// 按高度升序返回，越小的越具体，排前面。
function zoneOverlapsAt(y) {
  const hits = [];
  for (const item of state.zoneRects) {
    if (!item.node || item.node.hidden) continue;
    if (!Number.isFinite(item.top) || !Number.isFinite(item.height)) continue;
    if (y < item.top || y > item.top + item.height) continue;
    hits.push(item);
  }
  hits.sort((a, b) => a.height - b.height);
  return hits;
}

function handleZoneHover(event) {
  const hits = zoneOverlapsAt(zonePointerY(event));
  const pick = hits[0] || null;
  setActiveZone(pick);
  if (pick) showZoneTooltip(event, pick.row);
  else hideZoneTooltip();
}

function handleZoneClick(event) {
  const hits = zoneOverlapsAt(zonePointerY(event));
  // 没点中任何区间就放行，让 document 上的监听把弹窗关掉。
  if (!hits.length) return;
  event.stopPropagation();
  let pick = hits[0];
  // 按住 Alt 逐个切换这里重叠的区间；起点取当前正在看的那个，
  // 这样连按可以一直循环下去。
  if (event.altKey && hits.length > 1) {
    const from = hits.some((item) => item.row === state.zonePopupRow)
      ? state.zonePopupRow
      : pick.row;
    const current = hits.findIndex((item) => item.row === from);
    pick = hits[(current + 1 + hits.length) % hits.length] || pick;
  }
  state.zonePopupRow = pick.row;
  setActiveZone(pick);
  renderZonePopup(pick.row, event);
}

function addZoneRect(row, className) {
  const node = make("div", className);
  node.dataset.zoneIndex = String(state.zoneRects.length);
  els.zoneLayer.append(node);
  const label = make("span", "zone-label", zoneDirectionLabel(row));
  node.append(label);
  state.zoneRects.push({ row, node, label });
}
function pnlLabel(value) {
  const number = Number(value) || 0;
  if (number > 0) return `浮盈 +${usd.format(number)}`;
  if (number < 0) return `浮亏 -${usd.format(Math.abs(number))}`;
  return "浮盈 $0.00";
}

function hidePositionTooltip() {
  els.positionTooltip.hidden = true;
}

function hidePositionPopup() {
  els.positionPopup.hidden = true;
  els.positionPopup.replaceChildren();
}

function positionDetailRow(label, value, className = "") {
  const row = make("div", "position-detail-row");
  row.append(make("span", "position-detail-label", label));
  row.append(make("span", `position-detail-value ${className}`.trim(), value));
  return row;
}

function renderPositionPopup(data, position, event) {
  const leverage = Number(position.leverage) || 0;
  const entryValue = Number(position.entry) * Number(position.size);
  const margin = leverage > 0 ? Number(position.notional) / leverage : entryValue;
  const roi = margin > 0 ? Number(position.pnl) / margin * 100 : 0;
  const popup = els.positionPopup;
  const title = make("div", "position-popup-head");
  const titleText = make("div", "position-popup-title");
  titleText.append(
    make("span", `position-side ${position.side === "做多" ? "long" : "short"}`, position.side),
    make("span", "", `${state.chartData.coin} 仓位`),
  );
  const close = make("button", "position-close", "×");
  close.type = "button";
  close.setAttribute("aria-label", "关闭仓位详情");
  close.addEventListener("click", hidePositionPopup);
  title.append(titleText, close);

  const details = make("div", "position-detail");
  details.append(
    positionDetailRow("名义价值", formatAmount(position.notional)),
    positionDetailRow("杠杆", leverage > 0 ? `${leverage}x` : "-"),
    positionDetailRow("收益率", `${roi >= 0 ? "+" : "-"}${Math.abs(roi).toFixed(2)}%`, pnlClass(roi)),
    positionDetailRow("更新时间", timeText(data.generated_at)),
  );

  popup.replaceChildren(title, details);
  popup.hidden = false;
  popup.style.right = "";
  popup.style.left = "12px";
  popup.style.top = "12px";

  const containerRect = els.chartContainer.getBoundingClientRect();
  const left = Math.min(
    Math.max(8, (event?.clientX ?? containerRect.left + 80) - containerRect.left - popup.offsetWidth / 2),
    Math.max(8, els.chartContainer.clientWidth - popup.offsetWidth - 8),
  );
  const top = Math.min(
    Math.max(8, (event?.clientY ?? containerRect.top + 80) - containerRect.top + 12),
    Math.max(8, els.chartContainer.clientHeight - popup.offsetHeight - 8),
  );
  popup.style.left = `${left}px`;
  popup.style.top = `${top}px`;

  title.addEventListener("pointerdown", (dragStart) => {
    if (dragStart.button !== 0 || dragStart.target.closest(".position-close")) return;
    const startX = dragStart.clientX;
    const startY = dragStart.clientY;
    const startLeft = popup.offsetLeft;
    const startTop = popup.offsetTop;
    title.setPointerCapture(dragStart.pointerId);
    title.classList.add("dragging");

    const move = (moveEvent) => {
      const nextLeft = Math.min(
        Math.max(0, startLeft + moveEvent.clientX - startX),
        Math.max(0, els.chartContainer.clientWidth - popup.offsetWidth),
      );
      const nextTop = Math.min(
        Math.max(0, startTop + moveEvent.clientY - startY),
        Math.max(0, els.chartContainer.clientHeight - popup.offsetHeight),
      );
      popup.style.left = `${nextLeft}px`;
      popup.style.top = `${nextTop}px`;
    };
    const stop = () => {
      title.classList.remove("dragging");
      title.removeEventListener("pointermove", move);
      title.removeEventListener("pointerup", stop);
      title.removeEventListener("pointercancel", stop);
    };
    title.addEventListener("pointermove", move);
    title.addEventListener("pointerup", stop);
    title.addEventListener("pointercancel", stop);
  });
}

function updatePositionOverlay() {
  const data = state.chartData;
  const position = data?.position;
  if (!position || !(Number(position.entry) > 0) || !state.candleSeries) {
    els.positionHitbox.hidden = true;
    hidePositionTooltip();
    return;
  }
  let coordinate;
  try {
    coordinate = state.candleSeries.priceToCoordinate(Number(position.entry));
  } catch (_) {
    coordinate = NaN;
  }
  const height = els.priceChart.clientHeight;
  if (!Number.isFinite(coordinate) || coordinate < 10 || coordinate > height - 10) {
    els.positionHitbox.hidden = true;
    hidePositionTooltip();
    return;
  }

  const top = Math.max(0, Math.min(height - 18, coordinate - 9));
  els.positionHitbox.hidden = false;
  els.positionHitbox.style.top = `${top}px`;
  els.positionHitbox.className = `position-hitbox ${position.side === "做多" ? "long" : "short"}`;
}
function legendChip(label, value, color) {
  const item = make("div", "legend-item");
  item.append(make("span", "legend-dot"), make("span", "legend-text", `${label} ${value}`));
  item.querySelector(".legend-dot").style.background = color;
  return item;
}

function drawChartOverlays(data) {
  clearPriceLines();
  clearOrderZoneOverlays();
  hidePositionTooltip();
  hidePositionPopup();
  hideZoneTooltip();
  hideZonePopup();
  els.chartLegend.replaceChildren();
  const visibleOrders = state.overlays.orders ? data.order_zones.slice(0, 12) : [];
  const visibleFills = state.overlays.fills ? data.fill_zones.slice(0, 12) : [];
  const visibleTpsl = state.overlays.tpsl ? data.tpsl_lines.slice(0, 12) : [];
  const visibleWhaleOrders = state.overlays.whaleOrders ? (data.whale_order_zones || data.whale_zones || []).slice(0, 20) : [];
  const visibleWhaleFills = state.overlays.whaleFills ? (data.whale_fill_zones || []).slice(0, 30) : [];
  // 区间都是全宽横条，先挂大区间、后挂小区间，
  // 这样价格跨度小的叠在上层，鼠标才点得到。
  const zoneSpans = (row) => Math.abs(Number(row.max_px) - Number(row.min_px)) || 0;
  const zoneRows = [
    ...visibleOrders.map((row) => [row, "order"]),
    ...visibleFills.map((row) => [row, "fill"]),
    ...visibleWhaleOrders.map((row) => [row, "whale"]),
    ...visibleWhaleFills.map((row) => [row, "whalefill"]),
  ].sort((a, b) => zoneSpans(b[0]) - zoneSpans(a[0]));
  for (const [row, kind] of zoneRows) {
    const side = row.side_raw === "B" ? "long" : "short";
    addZoneRect(row, `zone-rect ${kind}-zone ${side}`);
  }

  for (const row of visibleTpsl) {
    const color = row.label === "止盈" ? "#7c9cff" : "#ffb86b";
    const size = row.size ? ` ${qty.format(row.size)}` : "";
    addPriceLine(row.price, color, `${row.label} ${row.side}${size}`, 2);
  }
  if (data.position && Number(data.position.entry) > 0) {
    addPriceLine(data.position.entry, "#c8b0ff", data.position.side, 2);
  }
  state.volumeSeries.applyOptions({ visible: state.overlays.volume });

  if (visibleOrders.length) {
    els.chartLegend.append(legendChip("挂单区间", `${visibleOrders.length} 组`, "#38d1a7"));
  }
  if (visibleFills.length) {
    els.chartLegend.append(legendChip("成交区间", `${visibleFills.length} 组`, "#7ee0c0"));
  }
  if (visibleWhaleOrders.length || visibleWhaleFills.length) {
    const label = data.whale_process ? `Autohunt(${data.whale_process})` : "Autohunt";
    const accounts = data.whale_account_count ? ` · ${data.whale_account_count}账户` : "";
    if (visibleWhaleOrders.length) {
      els.chartLegend.append(legendChip(`${label} 挂单`, `${visibleWhaleOrders.length} 组${accounts}`, "#6eaaff"));
    }
    if (visibleWhaleFills.length) {
      els.chartLegend.append(legendChip(`${label} 成交`, `${visibleWhaleFills.length} 组${accounts}`, "#9d8cff"));
    }
  }
  if (visibleTpsl.length) {
    els.chartLegend.append(legendChip("止盈止损", `${visibleTpsl.length} 条`, "#7c9cff"));
  }
  if (!visibleOrders.length && !visibleFills.length && !visibleTpsl.length && !visibleWhaleOrders.length && !visibleWhaleFills.length) {
    els.chartLegend.append(make("div", "legend-empty", "当前无叠加区间"));
  }
}

function renderChart(data) {
  ensureChart();
  state.chartData = data;
  state.candleSeries.applyOptions({ priceFormat: priceFormat(data.current_price || data.candles.at(-1)?.close || 1) });
  state.candleSeries.setData(data.candles);
  state.volumeSeries.setData(data.volumes);
  els.chartSymbolLabel.textContent = `${data.coin} · ${data.interval}`;
  els.autohuntProcess.textContent = data.whale_process ? `进程 ${data.whale_process}` : "未选择";
  drawChartOverlays(data);
  requestAnimationFrame(() => {
    updatePositionOverlay();
    updateOrderZoneOverlays();
  });
  setTimeout(() => {
    updatePositionOverlay();
    updateOrderZoneOverlays();
  }, 80);
  if (data.candles.length) {
    state.chart.timeScale().fitContent();
    state.chart.timeScale().setVisibleLogicalRange({
      from: Math.max(0, data.candles.length - 180),
      to: data.candles.length + 6,
    });
  }
  state.chart.applyOptions({ width: els.priceChart.clientWidth, height: els.priceChart.clientHeight });
}

function renderChartSymbols(data) {
  const symbols = data.symbols?.length ? data.symbols : [data.coin];
  if (!state.chartCoin) state.chartCoin = data.coin;
  if (!symbols.includes(state.chartCoin)) symbols.unshift(state.chartCoin);
  els.chartSymbol.replaceChildren();
  for (const symbol of symbols.slice(0, 80)) {
    const option = make("option", "", symbol);
    option.value = symbol;
    els.chartSymbol.append(option);
  }
  els.chartSymbol.value = state.chartCoin;
}

function relativeTime(ms) {
  const value = Number(ms) || 0;
  if (!value) return "-";
  const diff = Date.now() - value;
  if (diff < 0) {
    const mins = Math.round(-diff / 60000);
    return mins <= 0 ? "即将执行" : `${mins} 分钟后`;
  }
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

function processStatusText(row) {
  if (row.running) return "扫描中";
  if (row.enabled) return row.last_run ? "运行中" : "等待首轮";
  return "已停止";
}

function renderAutohunt(data, body) {
  if (!data.processes.length) {
    body.append(make("div", "state-empty", "还没有自动收集进程。可在 Telegram 用 /autohunt new 名称 创建。"));
  }

  for (const row of data.processes) {
    const card = make("div", "process-card");
    const head = make("div", "process-head");
    const title = make("div", "process-title");
    title.append(make("span", "process-name", row.name));
    title.append(make("span", `process-status ${row.running ? "running" : row.enabled ? "on" : "off"}`, processStatusText(row)));
    head.append(title);
    head.append(make("div", "process-scope", row.coins.length ? row.coins.join("、") : "综合"));
    card.append(head);

    const meta = make("div", "process-meta");
    meta.append(
      make("span", "", `每轮 ${row.limit}`),
      make("span", "", `间隔 ${Number(row.interval_h).toFixed(1).replace(/\.0$/, "")}h`),
      make("span", "", `已收集 ${row.account_count}`),
      make("span", "", `上次 ${relativeTime(row.last_run)}`),
    );
    if (row.enabled && !row.running && row.next_run) {
      meta.append(make("span", "", `下轮 ${relativeTime(row.next_run)}`));
    }
    card.append(meta);

    if (row.running) {
      const total = Math.max(row.progress_total, 1);
      const done = Math.min(Math.max(row.progress_done, 0), total);
      const pct = Math.round((done / total) * 100);
      const bar = make("div", "progress");
      const fill = make("div", "progress-fill");
      fill.style.width = `${pct}%`;
      bar.append(fill);
      card.append(bar, make("div", "progress-text", `已精算 ${done}/${total}（${pct}%）`));
    }

    if (row.accounts.length) {
      const rows = row.accounts.map((acc) => [
        cell(acc.alias || "—"),
        cell(shortAddress(acc.address)),
        cell(formatAmount(acc.account_value)),
        cell(relativeTime(acc.scanned_at)),
      ]);
      card.append(table(["命名", "地址", "账户价值", "收录时间"], rows));
    } else {
      card.append(make("div", "process-empty", "该进程还没有收录账户"));
    }
    body.append(card);
  }

  if (data.collected.length) {
    body.append(sectionTitle(`已收录大户（${data.collected.length}）`));
    const rows = data.collected.slice(0, 100).map((row) => [
      cell(row.alias || "—"),
      cell(shortAddress(row.address)),
      cell(formatAmount(row.account_value)),
      cell(formatAmount(row.volume)),
      cell(signed(row.pnl), pnlClass(row.pnl)),
      cell(`${(Number(row.roi) || 0).toFixed(1)}%`, pnlClass(row.roi)),
      cell(`${((Number(row.win_rate) || 0) * 100).toFixed(1)}%`),
      cell((Number(row.score) || 0).toFixed(2)),
    ]);
    body.append(table(["命名", "地址", "账户价值", "成交量", "盈亏", "ROI", "胜率", "评分"], rows));
  }
}
// ---------------------------------------------------------------- 链上筹码

function amountText(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) return "0";
  const abs = Math.abs(number);
  if (abs >= 1e9) return `${(number / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(number / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return number.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (abs >= 1) return number.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return number.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
}

function percentText(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(digits)}%` : "—";
}

function addressCell(address) {
  const node = cell(shortAddress(address));
  node.title = address || "";
  return node;
}

function rowActionButton(text, className, handler) {
  const node = make("button", `row-button ${className}`.trim(), text);
  node.type = "button";
  node.addEventListener("click", handler);
  return node;
}

function briefError(text) {
  const raw = String(text || "").replace(/\s+/g, " ").trim();
  if (!raw) return "";
  return raw.length > 72 ? `${raw.slice(0, 72)}…` : raw;
}

function statusCell(row) {
  const failed = Boolean(row.error);
  const node = cell("", `onchain-status ${failed ? "error" : "ok"}`);
  node.append(make("span", "onchain-status-tag", failed ? "失败" : "正常"));
  if (failed) {
    node.title = row.error;
    node.append(make("span", "onchain-error-brief", briefError(row.error)));
  }
  return node;
}

const WHALE_ERROR_GROUP = "__errors__";

async function refreshWhaleTargets(targets, button, busyText) {
  const original = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    button.textContent = busyText || "刷新中…";
  }
  try {
    const data = await request("/api/whale/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targets }),
    });
    state.whaleData = data;
    clearState("whale");
    renderWhale(data);
    setUpdatedAt(data.generated_at);
  } catch (error) {
    showState("whale", "error", apiErrorText(error));
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
  }
}

async function rescanWhaleToken(chain, token, button) {
  const original = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    button.textContent = "复扫中…";
  }
  try {
    const data = await request("/api/whale/rescan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chain, token }),
    });
    state.whaleData = data;
    clearState("whale");
    renderWhale(data);
    setUpdatedAt(data.generated_at);
  } catch (error) {
    showState("whale", "error", apiErrorText(error));
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
  }
}

function clickableToggle(node, collapsed, onToggle) {
  node.setAttribute("role", "button");
  node.setAttribute("tabindex", "0");
  node.addEventListener("click", onToggle);
  node.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onToggle();
  });
  return node;
}

function renderWhaleErrors(info, body) {
  const failures = [];
  for (const row of info.watches) {
    if (!row.error) continue;
    failures.push({
      kind: "监控地址",
      name: row.label || row.symbol || row.address,
      target: `${row.chain} · ${row.address}`,
      error: row.error,
      at: row.checked_ms,
    });
  }
  for (const row of info.watches) {
    if (!row.tx_error) continue;
    failures.push({
      kind: "成交监控",
      name: row.label || row.symbol || row.address,
      target: `${row.chain} · ${row.address}`,
      error: row.tx_error,
      at: row.checked_ms,
    });
  }
  for (const row of info.tokens) {
    if (!row.error) continue;
    failures.push({
      kind: "订阅代币",
      name: row.symbol || row.token,
      target: `${row.chain} · ${row.token}`,
      error: row.error,
      at: row.scanned_ms,
    });
  }
  if (!failures.length) return;

  const card = make("div", "onchain-card onchain-failure-card");
  const cardCollapsed = collapsedGroups().has(WHALE_ERROR_GROUP);
  const caret = make("span", `onchain-caret${cardCollapsed ? " collapsed" : ""}`, "▾");
  const head = make("div", "onchain-card-head");
  head.append(caret);
  head.append(make("span", "onchain-title", `检查失败（${failures.length}）`));
  head.append(make("span", "onchain-hint-inline", "点击收起 / 展开"));
  card.append(head);

  const list = make("div", `onchain-failure-list${cardCollapsed ? " collapsed" : ""}`);
  for (const item of failures) {
    const node = make("div", "onchain-failure-item");
    const itemHead = make("div", "onchain-failure-head");
    itemHead.append(make("span", "onchain-failure-kind", item.kind));
    itemHead.append(make("span", "onchain-failure-name", item.name));
    if (item.at) itemHead.append(make("span", "onchain-failure-time", relativeTime(item.at)));
    node.append(itemHead);
    node.append(make("div", "onchain-failure-target", item.target));

    const message = make("div", "onchain-failure-message clamped", item.error);
    node.append(message);
    const toggle = make("div", "onchain-failure-toggle", "展开完整原因");
    node.append(toggle);
    clickableToggle(node, true, () => {
      const clamped = message.classList.toggle("clamped");
      toggle.textContent = clamped ? "展开完整原因" : "收起";
    });
    list.append(node);
  }
  card.append(list);

  clickableToggle(head, cardCollapsed, () => {
    const nowCollapsed = !collapsedGroups().has(WHALE_ERROR_GROUP);
    setGroupCollapsed(WHALE_ERROR_GROUP, nowCollapsed);
    list.classList.toggle("collapsed", nowCollapsed);
    caret.classList.toggle("collapsed", nowCollapsed);
  });
  body.append(card);
}

function syncWhaleChains(chains) {
  const select = els.whaleChain;
  if (!select) return;
  const wanted = state.whaleChain || select.value;
  select.replaceChildren();
  for (const chain of chains) {
    const option = make("option", "", chain.scan ? chain.name : `${chain.name}（仅监控）`);
    option.value = chain.id;
    select.append(option);
  }
  const available = chains.map((chain) => chain.id);
  const picked = available.includes(wanted) ? wanted : (available[0] || "");
  select.value = picked;
  state.whaleChain = picked;
}

function candidateButton(candidate) {
  const node = make("button", "onchain-candidate");
  node.type = "button";
  node.title = `点击使用 ${candidate.address}`;
  const head = make("div", "onchain-candidate-head");
  head.append(make("span", "onchain-candidate-symbol", candidate.symbol || "?"));
  head.append(make("span", "onchain-candidate-chain", candidate.chain || ""));
  node.append(head);
  if (candidate.name) node.append(make("div", "onchain-candidate-name", candidate.name));
  const meta = [shortAddress(candidate.address)];
  if (Number(candidate.market_cap) > 0) meta.push(`市值 ${formatAmount(candidate.market_cap)}`);
  node.append(make("div", "onchain-candidate-meta", meta.join(" · ")));
  node.addEventListener("click", () => {
    if (candidate.chain) {
      state.whaleChain = candidate.chain;
      els.whaleChain.value = candidate.chain;
    }
    els.whaleToken.value = candidate.address;
    runWhaleScan();
  });
  return node;
}

function renderWhaleScan(scan, body) {
  const report = scan.report || {};
  const card = make("div", "onchain-card");
  const head = make("div", "onchain-head");
  head.append(make("div", "onchain-title", `${report.symbol || scan.token} · ${scan.chain}`));
  head.append(make("div", "onchain-score", `评分 ${Math.round(Number(report.score) || 0)}/100`));
  card.append(head);

  const resolved = scan.resolved || {};
  if (resolved.changed && scan.token) {
    const line = make("div", "onchain-hint");
    line.append(make("span", "", `${resolved.symbol || scan.query || ""} 解析为 `));
    line.append(make("code", "", scan.token));
    card.append(line);
  }

  if (report.error) {
    card.append(make("div", "state-error", report.error));
    const candidates = resolved.candidates || [];
    if (candidates.length) {
      card.append(make("div", "onchain-hint", "点击下方候选填入合约地址后重新扫描："));
      const list = make("div", "onchain-candidates");
      for (const candidate of candidates) list.append(candidateButton(candidate));
      card.append(list);
    }
    body.append(card);
    return;
  }

  const metrics = make("div", "metrics");
  metrics.append(
    metric("最大非基础设施地址", percentText(report.whale_pct)),
    metric("非基础设施前十大", percentText(report.whale10_pct)),
    metric("全部口径 前1 / 前10", `${percentText(report.top1_pct)} / ${percentText(report.top10_pct)}`),
    metric("流通量", amountText(report.supply)),
    metric("持币地址", Number(report.holder_count || 0).toLocaleString("en-US")),
    metric("价格", Number(report.price_usd) > 0 ? priceText(report.price_usd) : "—"),
    metric("抓取地址数", String((report.holders || []).length)),
    metric("扫描时间", timeText(scan.generated_at, false)),
  );
  card.append(metrics);

  if (report.whale_address) {
    const line = make("div", "onchain-hint");
    line.append(make("span", "", "最大非基础设施地址："));
    line.append(make("code", "", report.whale_address));
    if (report.whale_label) line.append(make("span", "", `（${report.whale_label}）`));
    card.append(line);
  }

  const rows = (report.holders || []).map((row) => {
    const action = make("td");
    action.append(rowActionButton(row.excluded ? "仍要监控" : "加入监控", "primary", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        await request("/api/whale/watch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "add",
            chain: scan.chain,
            token: scan.token,
            address: row.address,
            symbol: report.symbol || scan.token,
            label: row.label || "",
            decimals: report.decimals,
          }),
        });
        await refreshWhale();
      } catch (error) {
        showState("whale", "error", apiErrorText(error));
        button.disabled = false;
      }
    }));
    return [
      cell(String(row.rank)),
      addressCell(row.address),
      cell(amountText(row.balance)),
      cell(percentText(row.pct)),
      cell(row.excluded ? `🚫 ${row.exclude_reason || "已排除"}` : (row.label || "—")),
      action,
    ];
  });
  card.append(table(["#", "地址", "数量", "占比", "标签", ""], rows));

  const foot = make("div", "onchain-actions");
  foot.append(rowActionButton("订阅该币筹码复扫", "primary", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await request("/api/whale/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "add",
          chain: scan.chain,
          token: scan.token,
          label: report.symbol || "",
        }),
      });
      await refreshWhale();
    } catch (error) {
      showState("whale", "error", apiErrorText(error));
    } finally {
      button.disabled = false;
    }
  }));
  foot.append(make("span", "onchain-note", "🚫 交易所/跨链桥/DEX 池等多人共用地址不计入单地址集中度"));
  card.append(foot);
  body.append(card);
}

function whaleAddForm(info) {
  const wrap = make("div", "onchain-add");
  const chainSelect = make("select", "chart-select");
  for (const chain of info.chains) {
    const option = make("option", "", chain.name);
    option.value = chain.id;
    chainSelect.append(option);
  }
  if (state.whaleChain) chainSelect.value = state.whaleChain;

  const tokenInput = make("input", "onchain-input");
  tokenInput.placeholder = "代币合约 / native";
  tokenInput.autocomplete = "off";
  tokenInput.spellcheck = false;
  const addressInput = make("input", "onchain-input");
  addressInput.placeholder = "地址";
  addressInput.autocomplete = "off";
  addressInput.spellcheck = false;
  const labelInput = make("input", "onchain-input");
  labelInput.placeholder = "备注（可选）";
  labelInput.autocomplete = "off";

  wrap.append(
    chainSelect,
    tokenInput,
    addressInput,
    labelInput,
    rowActionButton("手动添加", "primary", async (event) => {
      const button = event.currentTarget;
      const chain = chainSelect.value;
      const token = tokenInput.value.trim();
      const address = addressInput.value.trim();
      if (!chain || !token || !address) {
        showState("whale", "error", "请填写链、代币合约和地址");
        return;
      }
      button.disabled = true;
      try {
        await request("/api/whale/watch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "add", chain, token, address, label: labelInput.value.trim(),
          }),
        });
        await refreshWhale();
      } catch (error) {
        showState("whale", "error", apiErrorText(error));
        button.disabled = false;
      }
    }),
  );
  return wrap;
}

const CHAT_SOURCE_BADGES = {
  web: { label: "Web", hint: () => "网页面板添加" },
  telegram: {
    label: "TG",
    hint: (row) => `来自 Telegram（${(row.chat_ids || []).length} 个聊天），移除会同时取消那边的监控`,
  },
  both: {
    label: "TG+Web",
    hint: (row) => `网页和 Telegram 都有（${(row.chat_ids || []).length} 处），移除会一并取消`,
  },
};

function whaleChatSource(row) {
  const chats = row.chat_ids || [];
  const hasWeb = chats.includes(state.webChatId || "__web__");
  if (hasWeb && chats.length > 1) return "both";
  if (hasWeb) return "web";
  return "telegram";
}

function appendChatSourceBadge(node, row) {
  const source = whaleChatSource(row);
  const badge = CHAT_SOURCE_BADGES[source];
  if (!badge) return;
  const el = make("span", `account-source ${source}`, badge.label);
  el.title = badge.hint(row);
  node.append(el);
}

function whaleGroupKey(row) {
  const symbol = String(row.symbol || "").trim().toUpperCase();
  if (symbol) return symbol;
  const token = String(row.token || "").trim().toUpperCase();
  return token || "未标注";
}

function collapsedGroups() {
  try {
    const raw = JSON.parse(localStorage.getItem("hl.whaleCollapsed") || "[]");
    return new Set(Array.isArray(raw) ? raw : []);
  } catch (_) {
    return new Set();
  }
}

function setGroupCollapsed(name, collapsed) {
  const set = collapsedGroups();
  if (collapsed) set.add(name);
  else set.delete(name);
  localStorage.setItem("hl.whaleCollapsed", JSON.stringify([...set]));
}

function whaleWatchRow(row) {
  const action = make("td");
  const actions = make("div", "row-actions");
  actions.append(rowActionButton("刷新", "", (event) => {
    event.stopPropagation();
    refreshWhaleTargets(
      [{ chain: row.chain, token: row.token, address: row.address }],
      event.currentTarget,
    );
  }));
  actions.append(rowActionButton("移除", "danger", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await request("/api/whale/watch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "remove", chain: row.chain, token: row.token, address: row.address,
          all_chats: true,
        }),
      });
      await refreshWhale();
    } catch (error) {
      showState("whale", "error", apiErrorText(error));
      button.disabled = false;
    }
  }));
  action.append(actions);
  return [
    cell(row.chain),
    addressCell(row.address),
    cell(row.label || "—"),
    cell(row.balance === null || row.balance === undefined ? "—" : amountText(row.balance)),
    cell(percentText(row.min_delta_pct, 1)),
    cell(row.checked_ms ? relativeTime(row.checked_ms) : "未检查"),
    statusCell(row),
    action,
  ];
}

function renderWhaleWatchGroups(info, body) {
  const groups = new Map();
  for (const row of info.watches) {
    const key = whaleGroupKey(row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  const collapsed = collapsedGroups();
  const wrap = make("div", "onchain-groups");
  for (const name of [...groups.keys()].sort((a, b) => a.localeCompare(b))) {
    const rows = groups.get(name);
    const chains = [...new Set(rows.map((row) => row.chain))];
    const failed = rows.filter((row) => row.error).length;
    const isCollapsed = collapsed.has(name);

    const block = make("div", "onchain-group");
    const head = make("div", "onchain-group-head");
    head.append(make("span", `onchain-caret${isCollapsed ? " collapsed" : ""}`, "▾"));
    head.append(make("span", "onchain-group-name", name));
    appendChatSourceBadge(head, { chat_ids: [...new Set(rows.flatMap((row) => row.chat_ids || []))] });
    head.append(make("span", "onchain-group-meta", `${rows.length} 个地址 · ${chains.length} 条链`));
    if (failed) head.append(make("span", "onchain-group-failed", `${failed} 个失败`));
    head.append(make("span", "onchain-group-spacer"));
    head.append(rowActionButton("刷新本组", "", (event) => {
      event.stopPropagation();
      refreshWhaleTargets(
        rows.map((row) => ({
          chain: row.chain, token: row.token, address: row.address,
        })),
        event.currentTarget,
      );
    }));
    block.append(head);

    const inner = make("div", `onchain-group-body${isCollapsed ? " collapsed" : ""}`);
    inner.append(table(
      ["链", "地址", "备注", "余额", "告警阈值", "检查时间", "状态", ""],
      rows.map(whaleWatchRow),
    ));
    block.append(inner);

    clickableToggle(head, isCollapsed, () => {
      const nowCollapsed = !collapsedGroups().has(name);
      setGroupCollapsed(name, nowCollapsed);
      inner.classList.toggle("collapsed", nowCollapsed);
      head.setAttribute("aria-expanded", String(!nowCollapsed));
      const caret = head.querySelector(".onchain-caret");
      if (caret) caret.classList.toggle("collapsed", nowCollapsed);
    });
    wrap.append(block);
  }
  body.append(wrap);
}

const TX_DIRECTION_LABELS = { in: "转入", out: "转出", self: "自转" };

function renderWhaleTransactions(info, body) {
  const rows = info.transactions || [];
  body.append(sectionTitle(`最近链上成交（${rows.length}）`));
  if (!rows.length) {
    body.append(make(
      "div",
      "process-empty",
      info.monitor_transactions
        ? "还没有抓到成交。首次检查只建立基线，之后出现新成交才会记录。"
        : "成交监控当前已关闭，可在「设置」里打开。",
    ));
  } else {
    body.append(table(
      ["时间", "代币", "方向", "数量", "对手方", "链", "交易"],
      rows.map((row) => {
        const link = make("a", "tx-link", shortAddress(row.hash || ""));
        link.href = row.url || "#";
        link.target = "_blank";
        link.rel = "noreferrer";
        const action = make("td");
        action.append(link);
        return [
          cell(timeText(row.time)),
          cell(row.asset || row.token || "—"),
          cell(TX_DIRECTION_LABELS[row.direction] || "交易", row.direction === "in" ? "positive" : row.direction === "out" ? "negative" : ""),
          cell(qty.format(Number(row.value) || 0)),
          addressCell(row.counterparty || "—"),
          cell(row.chain),
          action,
        ];
      }),
    ));
  }
  const unsupported = [...new Set(
    info.watches
      .filter((row) => {
        const chain = (info.chains || []).find((item) => item.id === row.chain);
        return chain && chain.tx === false;
      })
      .map((row) => row.symbol || row.token),
  )];
  if (unsupported.length && info.monitor_transactions) {
    body.append(make(
      "div",
      "settings-hint",
      `以下所在链暂时拿不到免费成交接口，只做余额监控：${unsupported.join("、")}`,
    ));
  }
}

function renderWhaleWatches(info, body) {
  body.append(sectionTitle(`监控地址（${info.watches.length}）`));
  if (info.watches.length) {
    renderWhaleWatchGroups(info, body);
  } else {
    body.append(table(
      ["代币", "链", "地址", "余额", "告警阈值", "检查时间", "状态", ""],
      [],
    ));
  }
  body.append(whaleAddForm(info));
}

function renderWhaleTokens(info, body) {
  body.append(sectionTitle(`订阅代币（${info.tokens.length}）`));
  if (!info.tokens.length) {
    body.append(make("div", "process-empty", "还没有订阅。扫描后点“订阅该币筹码复扫”，即可定期跟踪筹码结构变化。"));
    return;
  }
  const rows = info.tokens.map((row) => {
    const action = make("td");
    const actions = make("div", "row-actions");
    const nameCell = cell(row.symbol || row.token);
    appendChatSourceBadge(nameCell, row);
    actions.append(rowActionButton("复扫", "", (event) => {
      event.stopPropagation();
      rescanWhaleToken(row.chain, row.token, event.currentTarget);
    }));
    actions.append(rowActionButton("取消订阅", "danger", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        await request("/api/whale/token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "remove", chain: row.chain, token: row.token, all_chats: true,
          }),
        });
        await refreshWhale();
      } catch (error) {
        showState("whale", "error", apiErrorText(error));
        button.disabled = false;
      }
    }));
    action.append(actions);
    return [
      nameCell,
      cell(row.chain),
      cell(row.top_pct === null || row.top_pct === undefined ? "—" : percentText(row.top_pct)),
      cell(row.score === null || row.score === undefined ? "—" : `${Math.round(Number(row.score))}/100`),
      cell(`${Number(row.interval_hours).toFixed(1).replace(/\.0$/, "")}h`),
      cell(row.scanned_ms ? relativeTime(row.scanned_ms) : "未扫描"),
      statusCell(row),
      action,
    ];
  });
  body.append(table(
    ["代币", "链", "最大非基础设施", "评分", "复扫间隔", "上次扫描", "状态", ""],
    rows,
  ));
}

// ---------------------------------------------------------------- 外观设置

const THEME_VARS = {
  accent_color: "--accent",
  up_color: "--green",
  down_color: "--red",
  bg_color: "--bg",
  panel_color: "--panel",
};

function hexToRgba(hex, alpha) {
  const match = /^#?([0-9a-fA-F]{6})$/.exec(String(hex || "").trim());
  if (!match) return "";
  const value = parseInt(match[1], 16);
  return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
}

function paintTheme(values) {
  if (!values) return;
  const root = document.documentElement;
  for (const [key, cssVar] of Object.entries(THEME_VARS)) {
    if (values[key]) root.style.setProperty(cssVar, values[key]);
  }
  const soft = hexToRgba(values.accent_color, 0.12);
  if (soft) root.style.setProperty("--accent-soft", soft);
  if (values.site_title) {
    document.title = values.site_title;
    if (els.brandText) els.brandText.textContent = values.site_title;
  }
  if (state.chart) {
    state.chart.applyOptions({
      layout: { background: { type: "solid", color: values.bg_color || "#181818" } },
    });
  }
  if (state.candleSeries && values.up_color && values.down_color) {
    state.candleSeries.applyOptions({
      upColor: values.up_color,
      downColor: values.down_color,
      wickUpColor: values.up_color,
      wickDownColor: values.down_color,
    });
  }
}

function applyTheme(values) {
  paintTheme(values);
  if (values) state.theme = values;
}

function draftTheme() {
  const draft = { ...(state.theme || {}) };
  for (const [key, node] of Object.entries(state.settingsInputs || {})) {
    if (key === "proxy_url" || node.type === "checkbox") continue;
    if (node.value) draft[key] = node.value.trim();
  }
  return draft;
}

function settingsField(label, control) {
  const wrap = make("label", "settings-field");
  wrap.append(make("span", "settings-label", label), control);
  return wrap;
}

function renderSettings(data) {
  state.settingsData = data;
  const body = panel("settings").querySelector(".panel-body");
  body.replaceChildren();
  const values = data.values || {};
  const inputs = {};

  const textInput = (key, placeholder) => {
    const input = make("input", "onchain-input settings-wide");
    input.value = values[key] || "";
    input.placeholder = placeholder || "";
    input.autocomplete = "off";
    input.spellcheck = false;
    inputs[key] = input;
    return input;
  };

  const colorInput = (key) => {
    const row = make("div", "settings-color");
    const picker = make("input", "settings-picker");
    picker.type = "color";
    picker.value = /^#[0-9a-fA-F]{6}$/.test(values[key] || "") ? values[key] : "#000000";
    const text = make("input", "onchain-input settings-hex");
    text.value = values[key] || "";
    text.spellcheck = false;
    picker.addEventListener("input", () => {
      text.value = picker.value;
      paintTheme(draftTheme());
    });
    text.addEventListener("input", () => {
      const value = text.value.trim();
      if (/^#[0-9a-fA-F]{6}$/.test(value)) {
        picker.value = value;
        paintTheme(draftTheme());
      }
    });
    row.append(picker, text);
    inputs[key] = text;
    return row;
  };

  const selectInput = (key, options) => {
    const select = make("select", "chart-select settings-wide");
    for (const [value, label] of options) {
      const option = make("option", "", label);
      option.value = value;
      select.append(option);
    }
    select.value = values[key] || options[0][0];
    inputs[key] = select;
    return select;
  };

  const previewAmount = (style) => {
    const previous = state.theme;
    state.theme = { ...(previous || {}), amount_format: style };
    const text = formatAmount(123456789);
    state.theme = previous;
    return text;
  };

  const appearance = make("div", "settings-card");
  appearance.append(make("div", "settings-title", "外观"));
  const grid = make("div", "settings-grid");

  const amountField = make("label", "settings-field");
  amountField.append(make("span", "settings-label", "金额显示"));
  const amountSelect = selectInput("amount_format", [
    ["compact", "英文紧凑（1.23M / 4.56B）"],
    ["cn", "中文单位（1234.56万 / 1.23亿）"],
    ["full", "完整数字（1,234,567.89）"],
  ]);
  amountField.append(amountSelect);
  const amountSample = make("div", "settings-hint", `预览：${previewAmount(amountSelect.value)}`);
  amountSelect.addEventListener("change", () => {
    amountSample.textContent = `预览：${previewAmount(amountSelect.value)}`;
  });
  amountField.append(amountSample);

  grid.append(
    settingsField("网站标题", textInput("site_title", "浏览器标签与左上角标题")),
    amountField,
    settingsField("上涨色（K线 / 盈利）", colorInput("up_color")),
    settingsField("主题色", colorInput("accent_color")),
    settingsField("下跌色（K线 / 亏损）", colorInput("down_color")),
    settingsField("背景色", colorInput("bg_color")),
    settingsField("面板色", colorInput("panel_color")),
  );
  appearance.append(grid);
  appearance.append(make("div", "settings-hint", "改动会立即预览；界面是深色主题，建议保持低亮度配色。K 线涨跌色同时用于盈亏数字。"));
  body.append(appearance);

  const network = make("div", "settings-card");
  network.append(make("div", "settings-title", "网络代理"));
  const toggle = make("label", "settings-toggle");
  const checkbox = make("input");
  checkbox.type = "checkbox";
  checkbox.checked = values.proxy_enabled === "1";
  toggle.append(checkbox, make("span", "", "启用代理（REST 与链上请求）"));
  network.append(toggle);

  const proxyUrl = make("input", "onchain-input settings-wide");
  proxyUrl.value = values.proxy_url || "";
  proxyUrl.placeholder = "socks5://127.0.0.1:7890";
  proxyUrl.disabled = !checkbox.checked;
  proxyUrl.autocomplete = "off";
  proxyUrl.spellcheck = false;
  checkbox.addEventListener("change", () => {
    proxyUrl.disabled = !checkbox.checked;
  });
  inputs.proxy_url = proxyUrl;
  inputs.proxy_enabled = checkbox;
  network.append(settingsField("代理地址", proxyUrl));
  network.append(make("div", "settings-hint", "支持 socks5://、socks://、http:// 写法；留空表示直连。保存后立即对 REST 与链上请求生效，WebSocket 需要重启进程才会切换。"));
  network.append(make("div", "settings-hint", `当前生效：${data.runtime?.effective_proxy || "直连"}`));
  body.append(network);

  const monitor = make("div", "settings-card");
  monitor.append(make("div", "settings-title", "链上监控"));
  const txToggle = make("label", "settings-toggle");
  const txBox = make("input");
  txBox.type = "checkbox";
  txBox.checked = values.whale_monitor_transactions === "1";
  txToggle.append(txBox, make("span", "", "监控被跟踪地址的链上成交"));
  inputs.whale_monitor_transactions = txBox;
  monitor.append(txToggle);
  monitor.append(make(
    "div",
    "settings-hint",
    "开启后会在检查余额的同时拉取转入/转出明细，能看到对手方、数量和交易链接。"
    + "HyperEVM 目前没有免费的成交接口，只做余额监控。",
  ));
  body.append(monitor);

  state.settingsInputs = inputs;
}

function collectSettings() {
  const values = {};
  for (const [key, node] of Object.entries(state.settingsInputs || {})) {
    values[key] = node.type === "checkbox" ? (node.checked ? "1" : "0") : node.value;
  }
  return values;
}

async function saveSettings(reset = false) {
  const button = reset ? els.settingsReset : els.settingsSave;
  const previous = state.theme;
  button.disabled = true;
  setStateLoading("settings");
  try {
    const data = await request("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reset ? { reset: true } : { values: collectSettings() }),
    });
    clearState("settings");
    renderSettings(data);
    applyTheme(data.values);
    setUpdatedAt(data.generated_at);
    if (state.chart) loadView(true);
  } catch (error) {
    if (previous) paintTheme(previous);
    showState("settings", "error", apiErrorText(error));
  } finally {
    button.disabled = false;
  }
}
// ---------------------------------------------------------------- 成交分析

const TX_CATEGORY_LABELS = {
  exchange: "交易所",
  cex: "交易所",
  dex: "DEX",
  bridge: "跨链桥",
  lending: "借贷",
  staking: "质押",
  custody: "托管",
  protocol: "协议",
  "phish--hack": "风险地址",
};

function txCategoryText(category) {
  const first = String(category || "").split(",").find(Boolean);
  if (!first) return "";
  return TX_CATEGORY_LABELS[first] || first;
}

function counterpartyCell(row) {
  const node = make("td", "wta-peer");
  node.title = row.counterparty;
  const line = make("div", "wta-peer-line");
  line.append(make("code", "", shortAddress(row.counterparty)));
  if (row.is_exchange) {
    const badge = make("span", "account-source both", "交易所");
    badge.title = "资金进出交易所会按这个标记归类";
    line.append(badge);
  } else {
    const text = txCategoryText(row.category);
    if (text) line.append(make("span", "account-source web", text));
  }
  node.append(line);
  if (row.label) node.append(make("div", "wta-peer-label", row.label));
  return node;
}

function renderWtaMetrics(summary) {
  const metrics = make("div", "metrics");
  const net = Number(summary.net_value) || 0;
  metrics.append(
    metric("总笔数", String(summary.count)),
    metric("转入", `${summary.in_count} 笔 · ${formatAmount(summary.in_value)}`),
    metric("转出", `${summary.out_count} 笔 · ${formatAmount(summary.out_value)}`),
    metric("净流", signed(net, formatAmount), pnlClass(net)),
    metric("对手方", String(summary.peer_count)),
    metric("参与地址", String(summary.watched_count)),
  );
  if (Number(summary.exchange_count) > 0) {
    metrics.append(
      metric("存入交易所", formatAmount(summary.exchange_deposit), "negative"),
      metric("从交易所提出", formatAmount(summary.exchange_withdraw), "positive"),
      metric("交易所净流", signed(summary.exchange_net, formatAmount), pnlClass(summary.exchange_net)),
      metric("交易所对手方", String(summary.exchange_count)),
    );
  }
  return metrics;
}

function renderWtaDaily(series, asset) {
  if (!series.length) return;
  const card = make("div", "onchain-card");
  card.append(make("div", "settings-title", "每日净流"));
  const maxVal = Math.max(
    ...series.map((row) => Math.max(row.in, row.out)), 1,
  );
  const wrap = make("div", "wta-bars");
  for (const row of series.slice(-31)) {
    const col = make("div", "wta-col");
    const inBar = make("div", "wta-bar in");
    inBar.style.height = `${Math.max(2, (row.in / maxVal) * 100)}%`;
    const outBar = make("div", "wta-bar out");
    outBar.style.height = `${Math.max(2, (row.out / maxVal) * 100)}%`;
    const bars = make("div", "wta-bars-inner");
    bars.append(inBar, outBar);
    col.append(bars);
    const label = make("div", "wta-col-label", new Date(row.day).toISOString().slice(5, 10));
    label.title = `${label.textContent} · 转入 ${formatAmount(row.in)} · 转出 ${formatAmount(row.out)} · ${row.count} 笔`;
    col.append(label);
    wrap.append(col);
  }
  card.append(wrap);
  const legend = make("div", "onchain-hint");
  legend.append(make("span", "wta-legend-dot in", ""), make("span", "", "转入"));
  legend.append(make("span", "wta-legend-dot out", ""), make("span", "", "转出"));
  legend.append(make("span", "onchain-note", ` · ${asset}`));
  card.append(legend);
  return card;
}

function renderWta(data) {
  const body = panel("whale-tx").querySelector(".panel-body");
  body.replaceChildren();
  const summary = data.summary || {};
  if (!summary.count) {
    body.append(make("div", "state-empty",
      `${data.window} 内没有 ${data.asset} 的成交记录。监控地址出现新成交后这里会自动积累数据。`));
    return;
  }
  body.append(renderWtaMetrics(summary));
  const daily = renderWtaDaily(data.daily || [], data.asset);
  if (daily) body.append(daily);

  if ((data.watched || []).length > 1) {
    body.append(sectionTitle("按监控地址拆分"));
    body.append(table(
      ["地址", "链", "笔数", "转入", "转出"],
      data.watched.map((row) => [
        addressCell(row.address),
        cell(row.chain),
        cell(String(row.count)),
        cell(formatAmount(row.in)),
        cell(formatAmount(row.out)),
      ]),
    ));
  }

  body.append(sectionTitle(`对手方（${data.counterparties.length}）`));
  body.append(table(
    ["对手方", "转入", "转出", "净流", "笔数", "链", "首次", "最近"],
    (data.counterparties || []).map((row) => {
      const net = Number(row.net) || 0;
      const inV = Number(row["in"].value) || 0;
      const outV = Number(row["out"].value) || 0;
      const inCell = cell(inV ? formatAmount(inV) : "—");
      inCell.title = `${row["in"].count} 笔`;
      const outCell = cell(outV ? formatAmount(outV) : "—");
      outCell.title = `${row["out"].count} 笔`;
      return [
        counterpartyCell(row),
        inCell,
        outCell,
        cell(signed(net, formatAmount), pnlClass(net)),
        cell(String(row["in"].count + row["out"].count)),
        cell((row.chains || []).join(", ")),
        cell(timeText(row.first_ms, false)),
        cell(timeText(row.last_ms, false)),
      ];
    }),
  ));

  if ((data.recent || []).length) {
    body.append(sectionTitle(`明细（最近 ${data.recent.length} 笔）`));
    body.append(table(
      ["时间", "我方地址", "方向", "数量", "对手方", "交易"],
      data.recent.map((row) => {
        const link = make("a", "tx-link", shortAddress(row.hash || ""));
        link.href = row.url || "#";
        link.target = "_blank";
        link.rel = "noreferrer";
        const action = make("td");
        action.append(link);
        return [
          cell(timeText(row.time)),
          addressCell(row.address),
          cell(TX_DIRECTION_LABELS[row.direction] || "交易", row.direction === "in" ? "positive" : row.direction === "out" ? "negative" : ""),
          cell(qty.format(Number(row.value) || 0)),
          addressCell(row.counterparty || "—"),
          action,
        ];
      }),
    ));
  }
}

async function loadWta() {
  const asset = els.wtaAsset.value;
  if (!asset) {
    showState("whale-tx", "empty", "还没有抓到任何成交，等监控地址出现新交易后再来。");
    return;
  }
  setStateLoading("whale-tx");
  try {
    const data = await request(
      `/api/whale/tx/analysis?asset=${encodeURIComponent(asset)}&window=${encodeURIComponent(state.wtaWindow)}`,
    );
    clearState("whale-tx");
    renderWta(data);
    setUpdatedAt(data.generated_at);
  } catch (error) {
    showState("whale-tx", "error", apiErrorText(error));
  }
}

async function loadWtaAssets() {
  try {
    const data = await request("/api/whale/tx/assets");
    const select = els.wtaAsset;
    const wanted = state.wtaAsset;
    select.replaceChildren();
    for (const item of data.assets || []) {
      const option = make("option", "", `${item.asset}（${item.count} 笔）`);
      option.value = item.asset;
      select.append(option);
    }
    const values = [...select.children].map((node) => node.value);
    state.wtaAsset = values.includes(wanted) ? wanted : (values[0] || "");
    select.value = state.wtaAsset;
  } catch (error) {
    showState("whale-tx", "error", apiErrorText(error));
  }
}
function renderWhale(data) {
  if (data) state.whaleData = data;
  const info = state.whaleData;
  const body = panel("whale").querySelector(".panel-body");
  body.replaceChildren();
  if (!info) return;
  if (!info.enabled) {
    body.append(make("div", "state-empty", "链上筹码监控未启用：请在 config.toml 的 [whales] 里设置 enabled = true。"));
    return;
  }
  syncWhaleChains(info.chains || []);
  if (state.whaleScan) renderWhaleScan(state.whaleScan, body);
  renderWhaleErrors(info, body);
  renderWhaleWatches(info, body);
  renderWhaleTransactions(info, body);
  renderWhaleTokens(info, body);
}

async function refreshWhale() {
  const data = await request("/api/whale");
  state.whaleData = data;
  clearState("whale");
  renderWhale(data);
  setUpdatedAt(data.generated_at);
}

async function runWhaleScan() {
  const chain = els.whaleChain.value;
  const token = els.whaleToken.value.trim();
  if (!chain || !token) {
    showState("whale", "error", "请选择链并填写代币合约（UTXO 链填 native）");
    return;
  }
  state.whaleChain = chain;
  localStorage.setItem("hl.whaleChain", chain);
  els.whaleScan.disabled = true;
  setStateLoading("whale");
  try {
    const data = await request(
      `/api/whale/scan?chain=${encodeURIComponent(chain)}&token=${encodeURIComponent(token)}`,
    );
    state.whaleScan = data;
    if (!state.whaleData) {
      await refreshWhale();
    } else {
      clearState("whale");
      renderWhale(null);
    }
    setUpdatedAt(data.generated_at);
  } catch (error) {
    showState("whale", "error", apiErrorText(error));
  } finally {
    els.whaleScan.disabled = false;
  }
}

async function runWhaleCheck() {
  els.whaleCheck.disabled = true;
  setStateLoading("whale");
  try {
    const data = await request("/api/whale/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    state.whaleData = data;
    clearState("whale");
    renderWhale(data);
    setUpdatedAt(data.generated_at);
  } catch (error) {
    showState("whale", "error", apiErrorText(error));
  } finally {
    els.whaleCheck.disabled = false;
  }
}
function renderReport(data, body) {
  const report = make("div", "report-html");
  report.innerHTML = data.html || "";
  body.append(report);
}

function renderView(view, data) {
  if (view === "chart") {
    renderChart(data);
    return;
  }
  if (view === "whale") {
    renderWhale(data);
    return;
  }
  if (view === "whale-tx") {
    renderWta(data);
    return;
  }
  if (view === "settings") {
    renderSettings(data);
    return;
  }
  const body = panel(view).querySelector(".panel-body");
  body.replaceChildren();
  if (view === "overview") renderOverview(data, body);
  else if (view === "fills") renderFills(data, body);
  else if (view === "events") renderEvents(data, body);
  else if (view === "autohunt") renderAutohunt(data, body);
  else if (view === "chart") renderChart(data);
  else renderReport(data, body);
}

function endpoint(view) {
  const address = encodeURIComponent(state.selected);
  if (view === "overview") return `/api/overview?address=${address}`;
  if (view === "fills") return `/api/fills?address=${address}&window_min=${state.fillsWindow}`;
  if (view === "orders") return `/api/orders?address=${address}&level=${state.ordersLevel}`;
  if (view === "chart") {
    const coin = encodeURIComponent(state.chartCoin || "BTC");
    const fillWindow = Number(state.fillWindow) || 1440;
    const wantsWhale = state.overlays.whaleOrders || state.overlays.whaleFills;
    const whaleParam = wantsWhale ? "&whale=1" : "";
    const mergeParam = `&merge=${state.merge}`;
    return `/api/chart?address=${address}&coin=${coin}&interval=${state.chartInterval}&fill_window_min=${fillWindow}${whaleParam}${mergeParam}`;
  }
  if (view === "tpsl") return `/api/tpsl?address=${address}`;
  if (view === "history") return `/api/history?address=${address}`;
  if (view === "autohunt") return "/api/autohunt";
  if (view === "whale") return "/api/whale";
  if (view === "whale-tx") return "/api/whale/tx/analysis?asset=" + encodeURIComponent(state.wtaAsset) + "&window=" + encodeURIComponent(state.wtaWindow);
  if (view === "settings") return "/api/settings";
  return `/api/events?address=${address}&limit=100`;
}

function setView(view) {
  state.view = view;
  for (const button of els.viewNav.querySelectorAll(".nav-button")) {
    button.classList.toggle("active", button.dataset.view === view);
  }
  for (const node of document.querySelectorAll(".panel")) {
    node.classList.toggle("active", node.dataset.panel === view);
  }
  if (view === "chart" && state.chart) {
    setTimeout(() => state.chart.applyOptions({
      width: els.priceChart.clientWidth,
      height: els.priceChart.clientHeight,
    }), 0);
  }
}

async function loadView(force = false) {
  if (state.busy) return;
  const view = state.view;
  if (["whale", "whale-tx", "settings"].includes(view)) {
    if (view === "whale-tx" && !els.wtaAsset.children.length) {
      await loadWtaAssets();
    }
  } else if (!state.selected) {
    showState(view, "empty", "暂无账户");
    return;
  }
  state.busy = true;
  els.refresh.disabled = true;
  setStateLoading(view);
  try {
    const data = await request(endpoint(view));
    if (state.view === view) {
      clearState(view);
      if (view === "chart") renderChartSymbols(data);
      renderView(view, data);
      setUpdatedAt(data.generated_at);
    }
  } catch (error) {
    if (state.view === view) showState(view, "error", apiErrorText(error));
  } finally {
    state.busy = false;
    els.refresh.disabled = false;
  }
}

async function loadState() {
  const payload = await request("/api/state");
  state.accounts = payload.accounts || [];
  if (state.selected && !state.accounts.some((account) => account.address === state.selected)) {
    state.selected = state.accounts[0]?.address || "";
  } else if (!state.selected && state.accounts[0]) {
    state.selected = state.accounts[0].address;
  }
  if (state.selected) localStorage.setItem("hl.selected", state.selected);
  if (payload.settings) applyTheme(payload.settings);
  els.network.textContent = payload.network || "";
  els.version.textContent = payload.version ? `v${payload.version}` : "";
  renderAccounts();
  renderContext();
}

els.viewNav.addEventListener("click", (event) => {
  const button = event.target.closest(".nav-button");
  if (!button || button.dataset.view === state.view) return;
  setView(button.dataset.view);
  loadView(true);
});

els.fillsWindow.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  state.fillsWindow = button.dataset.window;
  for (const node of els.fillsWindow.querySelectorAll("button")) node.classList.toggle("active", node === button);
  if (state.view === "fills") loadView(true);
});

els.ordersLevel.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  state.ordersLevel = button.dataset.level;
  for (const node of els.ordersLevel.querySelectorAll("button")) node.classList.toggle("active", node === button);
  if (state.view === "orders") loadView(true);
});

els.chartFillWindow.addEventListener("change", () => {
  state.fillWindow = els.chartFillWindow.value;
  localStorage.setItem("hl.fillWindow", state.fillWindow);
  syncFillWindowLabel();
  if (state.view === "chart") loadView(true);
});

els.chartInterval.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  state.chartInterval = button.dataset.interval;
  for (const node of els.chartInterval.querySelectorAll("button")) node.classList.toggle("active", node === button);
  if (state.view === "chart") loadView(true);
});

els.chartSymbol.addEventListener("change", () => {
  state.chartCoin = els.chartSymbol.value;
  hidePositionPopup();
  hidePositionTooltip();
  if (state.view === "chart") loadView(true);
});

els.chartOverlays.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const key = button.dataset.overlay;
  state.overlays[key] = !state.overlays[key];
  button.classList.toggle("active", state.overlays[key]);
  if (state.view !== "chart") return;
  if (key === "whaleOrders" || key === "whaleFills") {
    loadView(true);
    return;
  }
  if (state.chartData) {
    drawChartOverlays(state.chartData);
    updatePositionOverlay();
    updateOrderZoneOverlays();
  }
});

function showPositionTooltip(event) {
  const position = state.chartData?.position;
  if (!position) return;
  const containerRect = els.chartContainer.getBoundingClientRect();
  const tooltip = els.positionTooltip;
  tooltip.textContent = `${position.side} · ${pnlLabel(position.pnl)}`;
  tooltip.hidden = false;
  const left = Math.min(
    Math.max(8, event.clientX - containerRect.left - tooltip.offsetWidth / 2),
    Math.max(8, els.chartContainer.clientWidth - tooltip.offsetWidth - 8),
  );
  const top = Math.min(
    Math.max(8, Number(els.positionHitbox.style.top || 0) + 24),
    Math.max(8, els.chartContainer.clientHeight - tooltip.offsetHeight - 8),
  );
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
  tooltip.style.right = "";
}

els.priceChart.addEventListener("mousemove", handleZoneHover);
els.priceChart.addEventListener("mouseleave", () => {
  setActiveZone(null);
  hideZoneTooltip();
});
els.priceChart.addEventListener("click", handleZoneClick);

els.positionHitbox.addEventListener("mouseenter", showPositionTooltip);
els.positionHitbox.addEventListener("mousemove", showPositionTooltip);
els.positionHitbox.addEventListener("mouseleave", hidePositionTooltip);

els.positionHitbox.addEventListener("click", (event) => {
  event.stopPropagation();
  if (!state.chartData?.position) return;
  if (els.positionPopup.hidden) renderPositionPopup(state.chartData, state.chartData.position, event);
  else hidePositionPopup();
});

els.positionPopup.addEventListener("click", (event) => event.stopPropagation());
els.zonePopup.addEventListener("click", (event) => event.stopPropagation());
document.addEventListener("click", (event) => {
  if (!els.positionPopup.hidden && !els.positionPopup.contains(event.target)) hidePositionPopup();
  if (!els.zonePopup.hidden && !els.zonePopup.contains(event.target)) hideZonePopup();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (!els.positionPopup.hidden) hidePositionPopup();
    if (!els.zonePopup.hidden) hideZonePopup();
  }
});

els.priceAutoButton.addEventListener("click", () => {
  if (!state.chart) return;
  state.chart.priceScale("right").applyOptions({ autoScale: true });
});

function syncMergeLabel() {
  els.mergeSlider.value = String(state.merge);
  els.mergeValue.textContent = `${Number(state.merge).toFixed(2).replace(/0$/, "").replace(/\.$/, ".0")}x`;
}

let mergeTimer = null;
els.mergeSlider.addEventListener("input", () => {
  state.merge = Math.min(4, Math.max(0.25, parseFloat(els.mergeSlider.value) || 1));
  localStorage.setItem("hl.merge", String(state.merge));
  syncMergeLabel();
  if (state.view !== "chart") return;
  if (mergeTimer) clearTimeout(mergeTimer);
  mergeTimer = setTimeout(() => loadView(true), 450);
});
syncMergeLabel();
els.chartRefresh.addEventListener("click", () => {
  if (state.view === "chart") loadView(true);
});

els.chartSideToggle.addEventListener("click", () => {
  chartPanel().classList.toggle("side-collapsed");
  setTimeout(() => {
    if (state.chart) state.chart.applyOptions({
      width: els.priceChart.clientWidth,
      height: els.priceChart.clientHeight,
    });
  }, 0);
});

els.chartFullscreen.addEventListener("click", async () => {
  const node = chartPanel();
  try {
    if (document.fullscreenElement === node) {
      await document.exitFullscreen();
    } else if (node.requestFullscreen) {
      await node.requestFullscreen({ navigationUI: "hide" });
    } else if (node.webkitRequestFullscreen) {
      node.webkitRequestFullscreen();
    } else {
      syncChartFullscreen(!node.classList.contains("fullscreen"));
    }
  } catch (_) {
    syncChartFullscreen(!node.classList.contains("fullscreen"));
  }
});

document.addEventListener("fullscreenchange", () => {
  syncChartFullscreen(document.fullscreenElement === chartPanel());
});

els.refresh.addEventListener("click", () => loadView(true));
els.wtaRefresh.addEventListener("click", loadWta);
els.wtaAsset.addEventListener("change", () => {
  state.wtaAsset = els.wtaAsset.value;
  localStorage.setItem("hl.wtaAsset", state.wtaAsset);
  loadWta();
});
els.wtaWindow.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  state.wtaWindow = button.dataset.window;
  for (const node of els.wtaWindow.querySelectorAll("button")) {
    node.classList.toggle("active", node === button);
  }
  loadWta();
});
els.settingsSave.addEventListener("click", () => saveSettings(false));
els.settingsReset.addEventListener("click", () => saveSettings(true));
els.whaleScan.addEventListener("click", runWhaleScan);
els.whaleCheck.addEventListener("click", runWhaleCheck);
els.whaleChain.addEventListener("change", () => {
  state.whaleChain = els.whaleChain.value;
  localStorage.setItem("hl.whaleChain", state.whaleChain);
});
els.whaleToken.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  runWhaleScan();
});
els.sidebarToggle.addEventListener("click", () => setSidebarOpen(!els.sidebar.classList.contains("open")));
els.sidebarBackdrop.addEventListener("click", () => setSidebarOpen(false));

els.accountFormToggle.addEventListener("click", () => {
  els.accountForm.hidden = !els.accountForm.hidden;
  if (!els.accountForm.hidden) els.accountAddress.focus();
});

els.accountForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const address = els.accountAddress.value.trim();
  const alias = els.accountAlias.value.trim();
  if (!address) return;
  els.accountForm.disabled = true;
  try {
    await request("/api/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ address, alias }),
    });
    state.selected = address.toLowerCase();
    localStorage.setItem("hl.selected", state.selected);
    state.chartCoin = "";
    els.accountForm.reset();
    els.accountForm.hidden = true;
    await loadState();
    loadView(true);
  } catch (error) {
    showState(state.view, "error", error.message);
  } finally {
    els.accountForm.disabled = false;
  }
});

initFillWindowSelect();
setView("overview");
loadState()
  .then(() => loadView(true))
  .catch((error) => showState(state.view, "error", error.message));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && els.sidebar.classList.contains("open")) setSidebarOpen(false);
});