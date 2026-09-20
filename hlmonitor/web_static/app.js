const state = {
  accounts: [],
  selectedAccounts: (() => { try { const value = JSON.parse(localStorage.getItem("hl.selectedAccounts") || "[]"); if (Array.isArray(value) && value.length) return value; const legacy = localStorage.getItem("hl.selected") || ""; return legacy ? [legacy] : []; } catch (_) { return []; } })(),
  view: "overview",
  fillsWindow: "1440",
  ordersLevel: "auto",
  chartCoin: "",
  chartInterval: "15m",
  fillWindow: localStorage.getItem("hl.fillWindow") || "1440",
  merge: Math.min(4, Math.max(0.25, parseFloat(localStorage.getItem("hl.merge")) || 1)),
  chartData: null,
  whaleChain: localStorage.getItem("hl.whaleChain") || "",
  autohuntProc: localStorage.getItem("hl.autohuntProc") || "",
  autohuntProcesses: [],
  autohuntQuery: localStorage.getItem("hl.autohuntQuery") || "",
  autohuntSearchResults: [],
  autohuntSearchStatus: "",
  autohuntSearchToken: 0,
  autohuntPositions: null,
  autohuntPositionsStatus: "",
  autohuntPositionsToken: 0,
  accountDetail: null,
  accountDetailToken: 0,
  accountDetailTab: "positions",
  accountDetailWindow: localStorage.getItem("hl.accountDetailWindow") || "24h",
  accountDetailChart: null,
  accountDetailResize: null,
  autohuntHuntId: sessionStorage.getItem("hl.autohuntJob") || "",
  autohuntHunt: null,
  autohuntHuntToken: 0,
  autohuntHuntTimer: null,
  autohuntData: null,
  autohuntPnl: null,
  autohuntPnlToken: 0,
  autohuntPnlAddress: localStorage.getItem("hl.autohuntPnl") || "",
  autohuntPnlAlias: localStorage.getItem("hl.autohuntPnlAlias") || "",
  autohuntPnlChart: null,
  autohuntPnlResize: null,
  webChatId: "__web__",
  whaleData: null,
  whaleScan: null,
  settingsData: null,
  wtaAsset: localStorage.getItem("hl.wtaAsset") || "",
  wtaWindow: "30d",
  settingsInputs: null,
  theme: null,
  overlays: { orders: true, fills: true, tpsl: true, volume: true, whaleOrders: false, whaleFills: false, whalePositions: false },
  busy: false,
  loadPending: false,
  chartOverlayToken: 0,
  chartOverlayStatus: {},
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
  sidebarClose: document.getElementById("sidebar-close"),
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
  autohuntSearch: document.getElementById("autohunt-search"),
  accountDetail: document.getElementById("account-detail"),
  accountDetailTitle: document.getElementById("account-detail-title"),
  accountDetailAddress: document.getElementById("account-detail-address"),
  accountDetailBody: document.getElementById("account-detail-body"),
  accountDetailWindow: document.getElementById("account-detail-window"),
  accountDetailClose: document.getElementById("account-detail-close"),
  autohuntHunt: document.getElementById("autohunt-hunt"),
  autohuntLimit: document.getElementById("autohunt-limit"),
  chartOverlayStatus: document.getElementById("chart-overlay-status"),
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

els.autohuntSearch.value = state.autohuntQuery;

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
  const direction = String(row.dir || "").trim();
  const directionMap = {
    "Open Long": "开多",
    "Close Long": "平多",
    "Open Short": "开空",
    "Close Short": "平空",
    "Open": "开仓",
    "Close": "平仓",
  };
  if (directionMap[direction]) return directionMap[direction];
  if (direction) return direction;
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

function selectedAccounts() {
  return state.accounts.filter((account) => state.selectedAccounts.includes(account.address));
}

function selectedAddresses() {
  return selectedAccounts().map((account) => account.address);
}

function persistSelectedAccounts() {
  localStorage.setItem("hl.selectedAccounts", JSON.stringify(state.selectedAccounts));
  const first = state.selectedAccounts[0] || "";
  if (first) localStorage.setItem("hl.selected", first);
  else localStorage.removeItem("hl.selected");
}

function selectedAccount() {
  return selectedAccounts()[0] || null;
}

function accountLabel(account) {
  return account.alias || shortAddress(account.address);
}

function renderContext() {
  const accounts = selectedAccounts();
  if (!accounts.length) {
    els.currentAccount.textContent = "当前功能内选择账户";
    els.currentAddress.textContent = "可选择多个账户叠加数据";
    return;
  }
  els.currentAccount.textContent = accounts.length === 1
    ? accountLabel(accounts[0])
    : accounts.length + " 个账户叠加";
  els.currentAddress.textContent = accounts.length === 1
    ? accounts[0].address
    : accounts.map(accountLabel).join("、");
}

const ACCOUNT_SOURCE_BADGES = {
  telegram: {
    label: "TG",
    hint: (account) => "来自 Telegram（" + (account.chat_count || 1) + " 个聊天），移除会同时取消那边的订阅",
  },
  both: {
    label: "TG+Web",
    hint: (account) => "网页和 Telegram（" + (account.chat_count || 2) + " 个聊天）都订阅了，移除会一并取消",
  },
  web: {
    label: "Web",
    hint: () => "在网页面板添加",
  },
};

function accountPickerButton(text, className = "") {
  return make("button", ("account-picker-action " + className).trim(), text);
}

function renderAccountPicker(view) {
  const slot = panel(view)?.querySelector(".panel-account-slot");
  if (!slot) return;
  slot.replaceChildren();

  const picker = make("div", "account-picker");
  const head = make("div", "account-picker-head");
  const title = make("div", "account-picker-title");
  const count = selectedAddresses().length;
  title.append(
    make("span", "", "数据账户"),
    make("span", "account-picker-count", count ? " · 已选 " + count : " · 尚未选择"),
  );
  const actions = make("div", "account-picker-actions");
  const all = accountPickerButton("全选");
  const clear = accountPickerButton("清空");
  const add = accountPickerButton("+ 添加账户", "primary");
  all.addEventListener("click", () => {
    state.selectedAccounts = state.accounts.map((account) => account.address);
    persistSelectedAccounts();
    renderAccountPicker(view);
    renderContext();
    loadView(true);
  });
  clear.addEventListener("click", () => {
    state.selectedAccounts = [];
    persistSelectedAccounts();
    renderAccountPicker(view);
    renderContext();
    showState(view, "empty", "请选择一个或多个账户");
    panel(view).querySelector(".panel-body").replaceChildren();
  });
  actions.append(all, clear, add);
  head.append(title, actions);

  const list = make("div", "account-picker-list");
  if (!state.accounts.length) {
    list.append(make("div", "account-picker-empty", "暂无账户，请先添加一个地址"));
  }
  for (const account of state.accounts) {
    const active = state.selectedAccounts.includes(account.address);
    const item = make("label", "account-picker-item" + (active ? " active" : ""));
    const checkbox = make("input");
    checkbox.type = "checkbox";
    checkbox.checked = active;
    checkbox.setAttribute("aria-label", "选择 " + accountLabel(account));
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        if (!state.selectedAccounts.includes(account.address)) state.selectedAccounts.push(account.address);
      } else {
        state.selectedAccounts = state.selectedAccounts.filter((address) => address !== account.address);
      }
      persistSelectedAccounts();
      renderAccountPicker(view);
      renderContext();
      loadView(true);
    });
    const text = make("div", "account-text");
    const name = make("div", "account-name", accountLabel(account));
    const sourceBadge = ACCOUNT_SOURCE_BADGES[account.source];
    if (sourceBadge) {
      const badge = make("span", "account-source " + account.source, sourceBadge.label);
      badge.title = sourceBadge.hint(account);
      name.append(badge);
    }
    text.append(name, make("div", "account-address", shortAddress(account.address)));
    item.append(
      checkbox,
      make("span", "account-avatar", (account.alias || account.address.slice(2, 4)).slice(0, 2).toUpperCase()),
      text,
    );
    if (account.source !== "config") {
      const remove = make("button", "account-picker-remove", "×");
      remove.type = "button";
      remove.title = "移除账户";
      remove.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        try {
          await request("/api/accounts/" + account.address, { method: "DELETE" });
          state.selectedAccounts = state.selectedAccounts.filter((address) => address !== account.address);
          persistSelectedAccounts();
          await loadState();
          loadView(true);
        } catch (error) {
          showState(view, "error", apiErrorText(error));
        }
      });
      item.append(remove);
    }
    list.append(item);
  }

  const form = make("form", "account-picker-form");
  form.hidden = true;
  const address = make("input");
  address.placeholder = "0x...";
  address.autocomplete = "off";
  address.spellcheck = false;
  address.required = true;
  const alias = make("input");
  alias.placeholder = "命名（可选）";
  alias.autocomplete = "off";
  const submit = make("button", "", "添加并选择");
  submit.type = "submit";
  form.append(address, alias, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    try {
      const rawAddress = address.value.trim();
      await request("/api/accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address: rawAddress, alias: alias.value.trim() }),
      });
      const normalized = rawAddress.toLowerCase();
      if (!state.selectedAccounts.includes(normalized)) state.selectedAccounts.push(normalized);
      persistSelectedAccounts();
      await loadState();
      renderAccountPicker(view);
      loadView(true);
    } catch (error) {
      showState(view, "error", apiErrorText(error));
    } finally {
      submit.disabled = false;
    }
  });
  add.addEventListener("click", () => {
    form.hidden = !form.hidden;
    if (!form.hidden) address.focus();
  });
  picker.append(head, list, form, make("div", "account-picker-note", "可同时勾选多个账户，页面会合并显示它们的数据"));
  if (view === "chart") {
    const procControl = make("div", "account-picker-autohunt");
    const procHead = make("div", "account-picker-autohunt-head");
    procHead.append(make("span", "account-picker-autohunt-title", "Autohunt 进程"));
    procHead.append(make("span", "account-picker-autohunt-meta", state.autohuntProcesses.length ? `${state.autohuntProcesses.length} 个` : "未加载"));
    const procSelect = make("select", "chart-select autohunt-process-select");
    procSelect.setAttribute("aria-label", "选择 Autohunt 进程");
    procSelect.append(new Option("默认进程", ""));
    for (const process of state.autohuntProcesses) {
      procSelect.append(new Option(`${process.name}${process.account_count ? ` · ${process.account_count}账户` : ""}`, process.name));
    }
    if (!state.autohuntProcesses.some((process) => process.name === state.autohuntProc)) state.autohuntProc = "";
    procSelect.value = state.autohuntProc;
    procSelect.addEventListener("change", () => {
      state.autohuntProc = procSelect.value;
      localStorage.setItem("hl.autohuntProc", state.autohuntProc);
      ensureChartOverlays(true);
    });
    procControl.append(procHead, procSelect);
    list.before(procControl);
  }
  slot.append(picker);
}

function renderAccountPickers() {
  document.querySelectorAll(".panel-account-slot").forEach((slot) => {
    const parent = slot.closest(".panel");
    if (parent?.dataset.panel === state.view) renderAccountPicker(state.view);
    else slot.replaceChildren();
  });
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
    ...(data.multi ? [cell(row.account || "合计")] : []),
    cell(row.coin),
    cell(sideText(row)),
    cell(qty.format(Math.abs(row.szi))),
    cell(formatAmount(row.notional)),
    cell(row.entry || "-"),
    cell(row.leverage ? row.leverage + "x" : "-"),
    cell(signed(row.pnl), pnlClass(row.pnl)),
  ]);
  body.append(table((data.multi ? ["账户"] : []).concat(["币种", "方向", "数量", "价值", "开仓均价", "杠杆", "浮动盈亏"]), rows));
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
  body.append(table((data.multi ? ["账户"] : []).concat(["时间", "币种", "方向", "数量", "价格", "金额", "盈亏"]), data.recent.slice(0, 30).map((row) => [
    ...(data.multi ? [cell(row.account || "—")] : []),
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
    if (data.multi) meta.append(make("span", "", event.account || "账户"));
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
  const owner = row.account ? ` · ${row.account}` : "";
  return `${zoneKindLabel(row)} · ${zoneDirectionLabel(row)} · ${row.count}笔${accounts}${owner} · ${formatAmount(row.total_value)}`;
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
  const coin = position.coin || state.chartData.coin;
  const isAutohunt = Boolean(position.account_count);
  const leverage = Number(position.leverage) || 0;
  const size = Number(position.size || Math.abs(position.szi || 0));
  const entryValue = Number(position.entry) * size;
  const margin = Number(position.margin) > 0
    ? Number(position.margin)
    : leverage > 0
      ? Number(position.notional) / leverage
      : entryValue;
  const roi = margin > 0 ? Number(position.pnl) / margin * 100 : 0;
  const leverageText = leverage > 0
    ? `${leverage % 1 === 0 ? leverage.toFixed(0) : leverage.toFixed(2)}x`
    : "-";
  const popup = els.positionPopup;
  const title = make("div", "position-popup-head");
  const titleText = make("div", "position-popup-title");
  titleText.append(
    make("span", `position-side ${position.side === "做多" ? "long" : "short"}`, position.side),
    make("span", "", `${coin}${isAutohunt ? " Autohunt 聚合仓位" : " 仓位"}`),
  );
  const close = make("button", "position-close", "×");
  close.type = "button";
  close.setAttribute("aria-label", "关闭仓位详情");
  close.addEventListener("click", hidePositionPopup);
  title.append(titleText, close);

  const details = make("div", "position-detail");
  details.append(
    positionDetailRow("加权均价", priceText(position.entry)),
    positionDetailRow("持仓数量", qty.format(size)),
    positionDetailRow("名义价值", formatAmount(position.notional)),
    positionDetailRow("杠杆", leverageText),
    positionDetailRow("浮动盈亏", pnlLabel(position.pnl), pnlClass(position.pnl)),
    positionDetailRow("收益率", `${roi >= 0 ? "+" : "-"}${Math.abs(roi).toFixed(2)}%`, pnlClass(roi)),
  );
  if (isAutohunt) {
    details.append(positionDetailRow("账户数", `${position.account_count} 个`));
  }
  details.append(positionDetailRow("更新时间", timeText(data.generated_at)));

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

function chartPositions(data) {
  if (Array.isArray(data?.positions)) return data.positions;
  return data?.position ? [data.position] : [];
}
function positionAtChartEvent(event) {
  const data = state.chartData;
  if (!data || !state.candleSeries) return null;
  const rows = [
    ...chartPositions(data),
    ...(state.overlays.whalePositions ? (data.whale_positions || []) : []),
  ];
  if (!rows.length) return null;
  const chartRect = els.priceChart.getBoundingClientRect();
  const pointerY = event.clientY - chartRect.top;
  let best = null;
  for (const position of rows) {
    if (!(Number(position.entry) > 0)) continue;
    let coordinate;
    try {
      coordinate = state.candleSeries.priceToCoordinate(Number(position.entry));
    } catch (_) {
      coordinate = NaN;
    }
    if (!Number.isFinite(coordinate)) continue;
    const distance = Math.abs(pointerY - coordinate);
    if (distance <= 16 && (!best || distance < best.distance)) {
      best = { position, distance };
    }
  }
  return best?.position || null;
}

function handlePositionClick(event) {
  const position = positionAtChartEvent(event);
  if (!position) return;
  event.stopPropagation();
  hidePositionPopup();
  renderPositionPopup(state.chartData, position, event);
}

function updatePositionOverlay() {
  const data = state.chartData;
  const position = chartPositions(data).find((row) => Number(row.entry) > 0);
  if (!position || !state.candleSeries) {
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

function drawChartOverlays(data, options = {}) {
  const preservePopups = options.preservePopups === true;
  clearPriceLines();
  clearOrderZoneOverlays();
  if (!preservePopups) {
    hidePositionTooltip();
    hidePositionPopup();
    hideZoneTooltip();
    hideZonePopup();
  }
  els.chartLegend.replaceChildren();
  const visibleOrders = state.overlays.orders ? data.order_zones.slice(0, 12) : [];
  const visibleFills = state.overlays.fills ? data.fill_zones.slice(0, 12) : [];
  const visibleTpsl = state.overlays.tpsl ? data.tpsl_lines.slice(0, 12) : [];
  const visibleWhaleOrders = state.overlays.whaleOrders ? (data.whale_order_zones || data.whale_zones || []).slice(0, 20) : [];
  const visibleWhaleFills = state.overlays.whaleFills ? (data.whale_fill_zones || []).slice(0, 30) : [];
  const visibleWhalePositions = state.overlays.whalePositions ? (data.whale_positions || []).slice(0, 30) : [];
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
  const positions = chartPositions(data);
  for (const position of positions) {
    const account = position.account ? ` · ${position.account}` : "";
    const color = position.side === "做空" ? "#ff9db7" : "#c8b0ff";
    addPriceLine(position.entry, color, `${position.side}${account}`, 2);
  }
  if (positions.length) {
    for (const position of positions) {
      const account = position.account ? ` · ${position.account}` : "";
      const color = position.side === "做空" ? "#ff9db7" : "#c8b0ff";
      els.chartLegend.append(legendChip(`持仓${account}`, priceText(position.entry), color));
    }
  }
  for (const position of visibleWhalePositions) {
    const color = position.side === "做空" ? "#ff5c7a" : "#00e0a8";
    const accounts = position.account_count ? ` · ${position.account_count}账户` : "";
    addPriceLine(position.entry, color, `${position.side}${accounts}`, 2);
  }
  if (visibleWhalePositions.length) {
    const label = data.whale_process ? `Autohunt(${data.whale_process}) 持仓` : "Autohunt 持仓";
    for (const position of visibleWhalePositions) {
      const color = position.side === "做空" ? "#ff5c7a" : "#00e0a8";
      els.chartLegend.append(legendChip(label, `${position.side} ${priceText(position.entry)}`, color));
    }
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
  if (!positions.length && !visibleOrders.length && !visibleFills.length && !visibleTpsl.length && !visibleWhaleOrders.length && !visibleWhaleFills.length && !visibleWhalePositions.length) {
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
  ensureChartOverlays(true);
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

function destroyAutohuntPnlChart() {
  if (state.autohuntPnlResize) {
    state.autohuntPnlResize.disconnect();
    state.autohuntPnlResize = null;
  }
  if (state.autohuntPnlChart) {
    state.autohuntPnlChart.remove();
    state.autohuntPnlChart = null;
  }
}

function autohuntText(value) {
  return String(value ?? "").trim().toLowerCase();
}

function filterAutohuntData(data, rawQuery) {
  const term = autohuntText(rawQuery);
  if (!term) return data;
  const matches = (...values) => values.flat().some((value) => autohuntText(value).includes(term));

  const processes = (data.processes || []).map((process) => {
    if (matches(process.name, process.coins || [])) return process;
    const accounts = (process.accounts || []).filter((account) => matches(
      account.address, account.alias, account.account_value,
    ));
    const positions = (process.positions || []).filter((position) => matches(
      position.coin, position.side, position.account, position.accounts || [],
    ));
    if (!accounts.length && !positions.length) return null;
    return { ...process, accounts, positions };
  }).filter(Boolean);

  const collected = (data.collected || []).filter((account) => matches(
    account.address, account.alias, account.account_value, account.volume,
    account.pnl, account.roi, account.win_rate, account.score,
  ));

  return { ...data, processes, collected };
}

function autohuntPnlTrigger(address, alias = "") {
  const button = make("button", "autohunt-pnl-trigger", "详情");
  button.type = "button";
  button.dataset.address = address;
  button.dataset.alias = alias || "";
  button.title = "查看账户详情";
  return button;
}

function bindAutohuntPnlTriggers(root) {
  root.querySelectorAll(".autohunt-pnl-trigger").forEach((button) => {
    button.addEventListener("click", () => showAccountDetail(button.dataset.address, button.dataset.alias));
  });
}

function renderAutohuntPnlCard() {
  const current = state.autohuntPnl;
  if (!current) return null;
  const card = make("div", "pnl-card");
  const head = make("div", "pnl-head");
  const title = make("div", "pnl-title");
  title.append(make("div", "pnl-name", current.alias || shortAddress(current.address)));
  title.append(make("code", "pnl-address", shortAddress(current.address)));
  const close = make("button", "icon-button pnl-close");
  close.type = "button";
  close.setAttribute("aria-label", "关闭收益曲线");
  close.append(make("span", "", "×"));
  close.addEventListener("click", () => {
    state.autohuntPnlAddress = "";
    state.autohuntPnlAlias = "";
    state.autohuntPnl = null;
    localStorage.removeItem("hl.autohuntPnl");
    localStorage.removeItem("hl.autohuntPnlAlias");
    destroyAutohuntPnlChart();
    renderAutohunt(state.autohuntData, panel("autohunt").querySelector(".panel-body"));
  });
  head.append(title, close);
  card.append(head);

  if (current.loading) {
    const loading = make("div", "pnl-loading");
    for (let index = 0; index < 3; index += 1) loading.append(make("i"));
    loading.append(make("span", "", "正在读取累计盈亏..."));
    card.append(loading);
    return card;
  }
  if (current.error) {
    card.append(make("div", "state-error", current.error));
    return card;
  }

  const data = current.data || {};
  const info = data.account || {};
  const stats = data.metrics || {};
  const metrics = make("div", "metrics pnl-metrics");
  const currentPnl = Number(stats.current);
  metrics.append(
    metric("累计盈亏", Number.isFinite(currentPnl) ? signed(currentPnl) : "-", pnlClass(currentPnl)),
    metric("账户净值", formatAmount(info.account_value)),
    metric("全时段 ROI", `${(Number(info.roi) || 0).toFixed(2)}%`, pnlClass(info.roi)),
    metric("加权胜率", `${((Number(info.weighted_win_rate) || 0) * 100).toFixed(1)}%`),
    metric("最大回撤", stats.max_drawdown_pct == null ? "-" : `${Number(stats.max_drawdown_pct).toFixed(2)}%`),
    metric("评分", info.score ? (Number(info.score) * 100).toFixed(0) + "/100" : "-"),
  );
  card.append(metrics);

  const chartWrap = make("div", "pnl-chart");
  chartWrap.dataset.address = current.address;
  card.append(chartWrap);
  const hint = make("div", "pnl-hint");
  if (Number(stats.point_count) > 0) {
    hint.append(
      make("span", "", `${timeText(stats.start_time)} — ${timeText(stats.end_time)} · ${stats.point_count} 点`),
      make("span", "", `区间变化 ${signed(stats.change)}`),
    );
  } else {
    hint.append(make("span", "", "该账户暂时没有历史收益数据"));
  }
  card.append(hint);

  if ((data.points || []).length) {
    const token = current.token;
    requestAnimationFrame(() => {
      if (state.autohuntPnl?.token === token) mountAutohuntPnlChart(chartWrap, data);
    });
  }
  return card;
}

function mountAutohuntPnlChart(container, data) {
  if (!window.LightweightCharts) return;
  destroyAutohuntPnlChart();

  const points = (data.points || []).map((point) => {
    let time = Number(point.time) || 0;
    if (time > 1e12) time /= 1000;
    return { time: Math.floor(time), value: Number(point.pnl) || 0 };
  }).filter((point) => point.time > 0 && Number.isFinite(point.value));
  points.sort((a, b) => a.time - b.time);

  const chart = LightweightCharts.createChart(container, {
    width: Math.max(320, container.clientWidth || 680),
    height: 260,
    layout: {
      background: { type: "solid", color: "transparent" },
      textColor: "#9b9b9b",
      fontSize: 11,
    },
    grid: {
      vertLines: { visible: false },
      horzLines: { color: "rgba(255,255,255,.055)" },
    },
    rightPriceScale: { borderColor: "#303030" },
    timeScale: {
      borderColor: "#303030",
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 0,
    },
    localization: { priceFormatter: (value) => formatAmount(value) },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });
  const series = chart.addSeries(LightweightCharts.BaselineSeries, {
    baseValue: { type: "price", price: 0 },
    lineWidth: 2,
    topLineColor: "#66dd8e",
    topFillColor1: "rgba(102,221,142,.32)",
    topFillColor2: "rgba(102,221,142,.03)",
    bottomLineColor: "#ff7a7a",
    bottomFillColor1: "rgba(255,122,122,.03)",
    bottomFillColor2: "rgba(255,122,122,.32)",
    priceLineVisible: false,
    lastValueVisible: true,
  });
  series.setData(points);
  chart.timeScale().fitContent();

  const resize = new ResizeObserver(() => {
    chart.applyOptions({ width: Math.max(240, container.clientWidth), height: 260 });
  });
  resize.observe(container);
  state.autohuntPnlChart = chart;
  state.autohuntPnlResize = resize;
}

function destroyAccountDetailChart() {
  if (state.accountDetailResize) {
    state.accountDetailResize.disconnect();
    state.accountDetailResize = null;
  }
  if (state.accountDetailChart) {
    state.accountDetailChart.remove();
    state.accountDetailChart = null;
  }
}

function accountDonut(title, rows, valueFormatter = formatAmount, signColor = false) {
  const card = make("div", "donut-card");
  card.append(make("div", "donut-title", title));
  const values = (rows || []).filter((row) => Number(row.value) !== 0).slice(0, 8);
  const total = values.reduce((sum, row) => sum + Math.abs(Number(row.value) || 0), 0);
  const center = make("div", "donut-visual");
  const size = 150;
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.classList.add("donut-svg");

  const colors = ["#38d1a7", "#6eaaff", "#ffbe69", "#c89bff", "#ff8a8a", "#4fd8e0", "#f7d774", "#a0e7a0"];
  let offset = 0;
  values.forEach((row, index) => {
    const value = Math.abs(Number(row.value) || 0);
    const fraction = total > 0 ? value / total : 0;
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", "75");
    circle.setAttribute("cy", "75");
    circle.setAttribute("r", String(radius));
    circle.setAttribute("fill", "none");
    circle.setAttribute("stroke", colors[index % colors.length]);
    circle.setAttribute("stroke-width", "22");
    const finalDash = `${Math.max(0, fraction * circumference - 2)} ${circumference}`;
    circle.dataset.finalDash = finalDash;
    circle.dataset.circumference = String(circumference);
    circle.setAttribute("stroke-dasharray", finalDash);
    circle.setAttribute("stroke-dashoffset", String(-offset * circumference));
    circle.setAttribute("transform", "rotate(-90 75 75)");
    circle.setAttribute("stroke-linecap", "butt");
    svg.append(circle);
    offset += fraction;
  });
  const centerText = document.createElementNS("http://www.w3.org/2000/svg", "text");
  centerText.setAttribute("x", "75");
  centerText.setAttribute("y", "72");
  centerText.setAttribute("text-anchor", "middle");
  centerText.classList.add("donut-total");
  centerText.textContent = total ? valueFormatter(signColor ? values.reduce((sum, row) => sum + Number(row.value || 0), 0) : total) : "-";
  const centerLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
  centerLabel.setAttribute("x", "75");
  centerLabel.setAttribute("y", "90");
  centerLabel.setAttribute("text-anchor", "middle");
  centerLabel.classList.add("donut-label");
  centerLabel.textContent = values.length ? "合计" : "暂无";
  svg.append(centerText, centerLabel);
  center.append(svg);

  const legend = make("div", "donut-legend");
  if (!values.length) {
    legend.append(make("div", "donut-empty", "该区间没有数据"));
  }
  values.forEach((row, index) => {
    const item = make("div", "donut-item");
    const dot = make("i", "donut-dot");
    dot.style.background = colors[index % colors.length];
    item.append(dot, make("span", "donut-name", row.name || "-"), make("span", "donut-value", valueFormatter(Number(row.value) || 0)));
    if (signColor) item.querySelector(".donut-value").classList.add(pnlClass(Number(row.value) || 0));
    legend.append(item);
  });
  card.append(center, legend);
  return card;
}

function mountAccountDetailChart(container, data) {
  if (!window.LightweightCharts) return;
  destroyAccountDetailChart();
  const points = (data.pnl_series || []).map((point) => ({
    time: Math.floor((Number(point.time) || 0) / 1000),
    value: Number(point.pnl) || 0,
  })).filter((point) => point.time > 0).sort((a, b) => a.time - b.time);

  if (!points.length) {
    container.append(make("div", "detail-chart-empty", "当前区间没有收益曲线数据"));
    return;
  }
  const chart = LightweightCharts.createChart(container, {
    width: Math.max(320, container.clientWidth || 900),
    height: 230,
    layout: { background: { type: "solid", color: "transparent" }, textColor: "#9b9b9b", fontSize: 11 },
    grid: { vertLines: { visible: false }, horzLines: { color: "rgba(255,255,255,.055)" } },
    rightPriceScale: { borderColor: "#303030" },
    timeScale: { borderColor: "#303030", timeVisible: true, secondsVisible: false, rightOffset: 0 },
    localization: { priceFormatter: (value) => formatAmount(value) },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });
  const series = chart.addSeries(LightweightCharts.BaselineSeries, {
    baseValue: { type: "price", price: 0 },
    lineWidth: 2,
    topLineColor: "#66dd8e",
    topFillColor1: "rgba(102,221,142,.30)",
    topFillColor2: "rgba(102,221,142,.02)",
    bottomLineColor: "#ff7a7a",
    bottomFillColor1: "rgba(255,122,122,.02)",
    bottomFillColor2: "rgba(255,122,122,.30)",
    priceLineVisible: false,
    lastValueVisible: true,
  });
  series.setData(points);
  chart.timeScale().fitContent();
  const resize = new ResizeObserver(() => {
    chart.applyOptions({ width: Math.max(240, container.clientWidth), height: 230 });
  });
  resize.observe(container);
  state.accountDetailChart = chart;
  state.accountDetailResize = resize;
}

const prefersReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function motionReady() {
  return Boolean(window.anime) && !prefersReducedMotion;
}

function animateMetricNumbers(container) {
  if (!motionReady()) return;
  container.querySelectorAll("[data-raw-value]").forEach((node, index) => {
    const target = Number(node.dataset.rawValue);
    const formatter = String(node.dataset.formatter || "formatAmount");
    if (!Number.isFinite(target)) return;
    anime({
      targets: { value: 0 },
      value: target,
      duration: 620,
      delay: 70 + index * 35,
      easing: "easeOutExpo",
      round: Math.abs(target) >= 1 ? 0 : 6,
      update(anim) {
        const value = anim.animatables[0].target.value;
        node.textContent = formatter === "signed" ? signed(value) : formatAmount(value);
      },
    });
  });
}

function animateDonutArcs(pies) {
  if (!motionReady()) return;
  pies.querySelectorAll(".donut-svg circle").forEach((circle, index) => {
    const finalValue = circle.dataset.finalDash;
    if (!finalValue) return;
    anime({
      targets: circle,
      strokeDasharray: [`0 ${circle.dataset.circumference}`, finalValue],
      duration: 760,
      delay: 140 + index * 35,
      easing: "easeOutCubic",
    });
  });
}

function accountMetric(label, value, className = "", rawValue = null, formatter = "formatAmount") {
  const item = metric(label, value, className);
  if (rawValue !== null && Number.isFinite(Number(rawValue))) {
    item.dataset.rawValue = String(Number(rawValue));
    item.dataset.formatter = formatter;
  }
  return item;
}

function accountDetailSection(title, headers, rows, emptyText) {
  const wrap = make("div", "detail-section");
  wrap.append(sectionTitle(title));
  if (!rows.length) {
    wrap.append(make("div", "state-empty", emptyText));
    return wrap;
  }
  wrap.append(table(headers, rows));
  return wrap;
}

function renderAccountDetail(data, animateContent = false) {
  const info = data.account || {};
  const stats = data.summary || {};
  const title = info.alias || shortAddress(data.address);
  els.accountDetailTitle.textContent = title;
  els.accountDetailAddress.textContent = data.address;
  els.accountDetailAddress.title = data.address;
  for (const button of els.accountDetailWindow.querySelectorAll("button")) {
    button.classList.toggle("active", button.dataset.window === data.window);
  }

  const root = els.accountDetailBody;
  root.replaceChildren();
  const metrics = make("div", "metrics account-metrics");
  metrics.append(
    accountMetric("账户净值", formatAmount(stats.account_value), "", Number(stats.account_value) || 0),
    accountMetric("总盈亏", signed(stats.total_pnl), pnlClass(stats.total_pnl), Number(stats.total_pnl) || 0, "signed"),
    accountMetric("24h 盈亏", signed(stats.pnl_24h), pnlClass(stats.pnl_24h), Number(stats.pnl_24h) || 0, "signed"),
    accountMetric("48h 盈亏", signed(stats.pnl_48h), pnlClass(stats.pnl_48h), Number(stats.pnl_48h) || 0, "signed"),
    accountMetric("7d 盈亏", signed(stats.pnl_7d), pnlClass(stats.pnl_7d), Number(stats.pnl_7d) || 0, "signed"),
    accountMetric("30d 盈亏", signed(stats.pnl_30d), pnlClass(stats.pnl_30d), Number(stats.pnl_30d) || 0, "signed"),
    accountMetric("区间成交", formatAmount(stats.period_volume), "", Number(stats.period_volume) || 0),
    accountMetric("区间已实现", signed(stats.period_pnl), pnlClass(stats.period_pnl), Number(stats.period_pnl) || 0, "signed"),
    accountMetric("胜率", `${((Number(stats.win_rate) || 0) * 100).toFixed(1)}%`),
    accountMetric("最大回撤", stats.max_drawdown_pct == null ? "-" : `${Number(stats.max_drawdown_pct).toFixed(2)}%`),
  );
  root.append(metrics);

  const chart = make("div", "detail-chart");
  root.append(chart);
  const pies = make("div", "detail-pies");
  pies.append(
    accountDonut("仓位分布", data.pies?.positions || [], formatAmount),
    accountDonut("成交分布", data.pies?.volume || [], formatAmount),
    accountDonut("盈亏分布", data.pies?.pnl || [], signed, true),
  );
  root.append(pies);

  const tabs = make("div", "segmented detail-tabs");
  const tabLabels = [
    ["positions", `仓位 ${data.positions.length}`],
    ["trades", `交易 ${data.fills.length}`],
    ["orders", `当前委托 ${data.orders.length}`],
    ["transfers", `充值&提现 ${data.transfers.length}`],
    ["spot", `现货持仓 ${data.spot.length}`],
  ];
  for (const [key, label] of tabLabels) {
    const button = make("button", "", label);
    button.type = "button";
    button.dataset.tab = key;
    button.classList.toggle("active", state.accountDetailTab === key);
    button.addEventListener("click", () => {
      state.accountDetailTab = key;
      renderAccountDetail(data);
    });
    tabs.append(button);
  }
  root.append(tabs);

  const panelBody = make("div", "detail-tab-panel");
  if (state.accountDetailTab === "positions") {
    panelBody.append(accountDetailSection(
      "合约仓位", ["币种", "方向", "数量", "开仓均价", "仓位价值", "未实现盈亏", "ROE", "杠杆", "保证金", "强平价"],
      data.positions.map((row) => [
        cell(row.coin), cell(row.side), cell(qty.format(row.size)), cell(priceText(row.entry)),
        cell(formatAmount(row.notional)), cell(signed(row.pnl), pnlClass(row.pnl)),
        cell(`${(Number(row.roe_pct) || 0).toFixed(2)}%`, pnlClass(row.roe_pct)),
        cell(`${Number(row.leverage || 0).toFixed(0)}x`), cell(formatAmount(row.margin)), cell(priceText(row.liquidation)),
      ]),
      "当前没有合约仓位。",
    ));
  } else if (state.accountDetailTab === "trades") {
    panelBody.append(accountDetailSection(
      "成交记录", ["时间", "币种", "方向", "价格", "数量", "成交额", "已实现盈亏", "手续费"],
      data.fills.map((row) => [
        cell(timeText(row.time)), cell(row.coin), cell(sideText(row)), cell(priceText(row.px)),
        cell(qty.format(Math.abs(Number(row.sz) || 0))), cell(formatAmount(Math.abs(Number(row.px) * Number(row.sz) || 0))),
        cell(signed(row.closedPnl), pnlClass(row.closedPnl)), cell(formatAmount(row.fee)),
      ]),
      "该区间没有成交记录。",
    ));
  } else if (state.accountDetailTab === "orders") {
    panelBody.append(accountDetailSection(
      "当前委托", ["时间", "币种", "方向", "价格", "数量", "委托金额", "只减仓", "订单 ID"],
      data.orders.map((row) => [
        cell(timeText(row.time)), cell(row.coin), cell(row.side), cell(priceText(row.price)),
        cell(qty.format(row.size)), cell(formatAmount(row.notional)), cell(row.reduce_only ? "是" : "否"), cell(String(row.oid || "-")),
      ]),
      "当前没有普通委托。",
    ));
  } else if (state.accountDetailTab === "transfers") {
    panelBody.append(accountDetailSection(
      "充值 & 提现", ["时间", "类型", "代币", "金额", "手续费", "对手地址"],
      data.transfers.map((row) => [
        cell(timeText(row.time)), cell(row.direction), cell(row.token), cell(formatAmount(row.amount)),
        cell(formatAmount(row.fee)), addressCell(row.counterparty),
      ]),
      "没有充值或提现记录。",
    ));
  } else {
    panelBody.append(accountDetailSection(
      "现货持仓", ["代币", "总数量", "可用", "冻结", "建仓价值"],
      data.spot.map((row) => [
        cell(row.coin), cell(qty.format(row.total)), cell(qty.format(row.available)),
        cell(qty.format(row.hold)), cell(formatAmount(row.entry_value)),
      ]),
      "当前没有现货余额。",
    ));
  }
  root.append(panelBody);
  if (animateContent) {
    if (motionReady()) {
      anime.set([metrics, chart, pies, tabs], { opacity: 0, translateY: 12 });
      anime({
        targets: [metrics, chart, pies, tabs],
        opacity: [0, 1],
        translateY: [12, 0],
        delay: anime.stagger(55),
        duration: 460,
        easing: "easeOutCubic",
      });
    }
    animateMetricNumbers(metrics);
    animateDonutArcs(pies);
  }
  requestAnimationFrame(() => mountAccountDetailChart(chart, data));
}

async function requestAccountDetail(address, alias = "") {
  const token = ++state.accountDetailToken;
  const windowValue = state.accountDetailWindow;
  state.accountDetail = { loading: true, address, alias, window: windowValue, error: "" };
  els.accountDetailTitle.textContent = alias || shortAddress(address);
  els.accountDetailAddress.textContent = address;
  els.accountDetailBody.replaceChildren();
  const loading = make("div", "detail-loading");
  for (let index = 0; index < 3; index += 1) loading.append(make("i"));
  loading.append(make("span", "", "正在读取账户详情..."));
  els.accountDetailBody.append(loading);
  destroyAccountDetailChart();
  try {
    const data = await request(`/api/account/detail?address=${encodeURIComponent(address)}&window=${encodeURIComponent(windowValue)}`);
    if (token !== state.accountDetailToken) return;
    state.accountDetail = { loading: false, address, alias, window: windowValue, error: "", data };
    renderAccountDetail(data, true);
  } catch (error) {
    if (token !== state.accountDetailToken) return;
    state.accountDetail = { loading: false, address, alias, window: windowValue, error: apiErrorText(error) };
    els.accountDetailBody.replaceChildren(make("div", "state-error", apiErrorText(error)));
  }
}

function showAccountDetail(address, alias = "") {
  state.accountDetailWindow = localStorage.getItem("hl.accountDetailWindow") || "24h";
  els.accountDetail.hidden = false;
  if (motionReady()) {
    anime.set(els.accountDetail, { opacity: 0 });
    anime.set(els.accountDetail.querySelector(".detail-dialog"), { opacity: 0, translateY: 18, scale: 0.985 });
    anime({ targets: els.accountDetail, opacity: [0, 1], duration: 170, easing: "linear" });
    anime({
      targets: els.accountDetail.querySelector(".detail-dialog"),
      opacity: [0, 1],
      translateY: [18, 0],
      scale: [0.985, 1],
      duration: 320,
      easing: "easeOutCubic",
    });
  }
  state.accountDetailTab = "positions";
  requestAccountDetail(address, alias);
}

function closeAccountDetail() {
  if (els.accountDetail.hidden) return;
  state.accountDetailToken += 1;
  const finish = () => {
    els.accountDetail.hidden = true;
    destroyAccountDetailChart();
  };
  if (!motionReady()) {
    finish();
    return;
  }
  anime({
    targets: els.accountDetail,
    opacity: [1, 0],
    duration: 150,
    easing: "linear",
    complete: finish,
  });
  anime({
    targets: els.accountDetail.querySelector(".detail-dialog"),
    opacity: [1, 0],
    translateY: [0, 12],
    scale: [1, 0.99],
    duration: 170,
    easing: "easeInCubic",
  });
}

async function loadAutohuntPnl(address, alias = "") {
  const normalized = String(address || "").trim().toLowerCase();
  if (!normalized) return;
  const token = ++state.autohuntPnlToken;
  state.autohuntPnlAddress = normalized;
  state.autohuntPnlAlias = alias || state.autohuntPnlAlias || "";
  localStorage.setItem("hl.autohuntPnl", normalized);
  localStorage.setItem("hl.autohuntPnlAlias", state.autohuntPnlAlias);
  state.autohuntPnl = { token, loading: true, address: normalized, alias: state.autohuntPnlAlias, error: "", data: null };

  const body = panel("autohunt").querySelector(".panel-body");
  if (state.autohuntData) renderAutohunt(state.autohuntData, body);
  try {
    const data = await request(`/api/autohunt/pnl?address=${encodeURIComponent(normalized)}`);
    if (token !== state.autohuntPnlToken || state.view !== "autohunt") return;
    state.autohuntPnl = { token, loading: false, address: normalized, alias: state.autohuntPnlAlias, error: "", data };
    renderAutohunt(state.autohuntData || { processes: [], collected: [] }, body);
  } catch (error) {
    if (token !== state.autohuntPnlToken || state.view !== "autohunt") return;
    state.autohuntPnl = { token, loading: false, address: normalized, alias: state.autohuntPnlAlias, error: apiErrorText(error), data: null };
    renderAutohunt(state.autohuntData || { processes: [], collected: [] }, body);
  }
}

function huntScopeText(job) {
  const coins = job.coins || [];
  return coins.length ? coins.join(" / ") : "综合扫描";
}

function renderAutohuntHuntCard() {
  const job = state.autohuntHunt;
  if (!job || job.status === "not_found") return null;
  const card = make("div", "hunt-card");
  const head = make("div", "hunt-head");
  head.append(
    make("div", "hunt-title", "Hunt 扫描"),
    make("span", "hunt-scope", huntScopeText(job)),
    make("span", `hunt-status ${job.status}`, job.status === "success" ? "完成" : job.status === "error" ? "失败" : "扫描中"),
  );
  card.append(head);

  if (job.status === "running") {
    const total = Math.max(Number(job.progress_total) || 0, 1);
    const done = Math.min(Math.max(Number(job.progress_done) || 0, 0), total);
    const pct = Math.round((done / total) * 100);
    const bar = make("div", "progress");
    const fill = make("div", "progress-fill");
    fill.style.width = `${pct}%`;
    bar.append(fill);
    card.append(bar, make("div", "progress-text", `正在精算胜率 ${done}/${total}（${pct}%）`));
    return card;
  }
  if (job.status === "error") {
    card.append(make("div", "state-error", job.error || "Hunt 扫描失败"));
    return card;
  }

  const results = job.results || [];
  card.append(make("div", "hunt-meta", `发现 ${results.length} 个账户 · 粗筛 ${job.scanned_count || 0} 个 · 已同步到收集库`));
  if (!results.length) {
    card.append(make("div", "state-empty", "本轮没有符合条件的账户。"));
    return card;
  }
  const rows = results.map((account) => {
    const action = cell("", "table-action");
    action.append(autohuntPnlTrigger(account.address, account.alias));
    return [
      cell(account.alias || "-"),
      addressCell(account.address),
      cell(formatAmount(account.account_value)),
      cell(formatAmount(account.volume)),
      cell(signed(account.pnl), pnlClass(account.pnl)),
      cell(`${(Number(account.roi) || 0).toFixed(2)}%`, pnlClass(account.roi)),
      cell(`${((Number(account.win_rate) || 0) * 100).toFixed(1)}%`),
      cell(`${((Number(account.weighted_win_rate) || 0) * 100).toFixed(1)}%`),
      cell(String(account.sample_size || 0)),
      cell((Number(account.score) || 0).toFixed(2)),
      action,
    ];
  });
  card.append(table(["别名", "地址", "净值", "成交", "盈亏", "ROI", "胜率", "加权", "样本", "评分", "走势"], rows));
  return card;
}

function renderAutohuntLeaderboard() {
  if (!state.autohuntQuery || state.autohuntSearchStatus === "loading") {
    if (state.autohuntSearchStatus === "loading") {
      const loading = make("div", "hunt-search-state", "排行榜匹配中...");
      return loading;
    }
    return null;
  }
  const rows = state.autohuntSearchResults || [];
  if (!rows.length) return null;
  const card = make("div", "hunt-card leaderboard-card");
  const head = make("div", "hunt-head");
  head.append(make("div", "hunt-title", "排行榜匹配"), make("span", "hunt-scope", `${rows.length} 个`));
  card.append(head);
  const tableRows = rows.map((account) => {
    const action = cell("", "table-action");
    action.append(autohuntPnlTrigger(account.address, account.alias));
    return [
      cell(account.alias || "-"),
      addressCell(account.address),
      cell(formatAmount(account.account_value)),
      cell(formatAmount(account.volume)),
      cell(signed(account.pnl), pnlClass(account.pnl)),
      cell(`${(Number(account.roi) || 0).toFixed(2)}%`, pnlClass(account.roi)),
      action,
    ];
  });
  card.append(table(["别名", "地址", "净值", "成交", "盈亏", "ROI", "走势"], tableRows));
  return card;
}

function parseAutohuntCoins(query) {
  const values = String(query || "").trim().split(/[,，\s]+/).filter(Boolean);
  if (!values.length) return [];
  const coinLike = values.every((value) => /^[A-Za-z][A-Za-z0-9:-]{0,24}$/.test(value));
  return coinLike ? values.map((value) => value.toUpperCase()) : [];
}

function renderAutohunt(data, body) {
  state.autohuntData = data;
  destroyAutohuntPnlChart();
  const query = state.autohuntQuery;
  const pendingPositions = state.autohuntPositions === null;
  const positionedData = {
    ...data,
    processes: (data.processes || []).map((process) => {
      const positions = pendingPositions ? [] : state.autohuntPositions[process.key] || [];
      return { ...process, positions, position_count: pendingPositions ? null : positions.length };
    }),
  };
  const view = filterAutohuntData(positionedData, query);
  body.replaceChildren();

  const pnlCard = renderAutohuntPnlCard();
  if (pnlCard) body.append(pnlCard);

  if (!data.processes.length) {
    body.append(make("div", "state-empty", "还没有自动收集进程。可在 Telegram 用 /autohunt new 名称 创建。"));
  }

  const huntCard = renderAutohuntHuntCard();
  if (huntCard) body.append(huntCard);

  if (query) {
    const bar = make("div", "autohunt-toolbar");
    bar.append(make("span", "", `本地匹配 ${view.processes.length} 个进程 / ${view.collected.length} 个大户${state.autohuntSearchResults.length ? ` · 排行榜 ${state.autohuntSearchResults.length} 个` : ""}`));
    body.append(bar);
  }

  const leaderboardCard = renderAutohuntLeaderboard();
  if (leaderboardCard) body.append(leaderboardCard);

  for (const row of view.processes) {
    const card = make("div", "process-card");
    const head = make("div", "process-head");
    const title = make("div", "process-title");
    title.append(make("span", "process-name", row.name));
    title.append(make("span", `process-status ${row.running ? "running" : row.enabled ? "on" : "off"}`, processStatusText(row)));
    head.append(title);
    head.append(make("div", "process-scope", row.coins.length ? row.coins.join("、") : "聚合"));
    card.append(head);

    const meta = make("div", "process-meta");
    meta.append(
      make("span", "", `每次 ${row.limit}`),
      make("span", "", `间隔 ${Number(row.interval_h).toFixed(1).replace(/\.0$/, "")}h`),
      make("span", "", "已收集 " + row.account_count),
      make("span", "", pendingPositions ? "持仓 加载中" : row.position_count === null ? "持仓 -" : `持仓 ${row.position_count || 0}`),
      make("span", "", `上次 ${relativeTime(row.last_run)}`),
    );
    if (row.enabled && !row.running && row.next_run) {
      meta.append(make("span", "", `下次 ${relativeTime(row.next_run)}`));
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
      card.append(bar, make("div", "progress-text", `已扫描 ${done}/${total}（${pct}%）`));
    }

    const positions = row.positions || [];
    const positionTitle = pendingPositions ? "聚合持仓（加载中）" : positions.length ? "聚合持仓（同向、相近价格）" : "聚合持仓（当前无持仓）";
    card.append(make("div", "process-section-title", positionTitle));
    if (positions.length) {
      const positionRows = positions.map((position) => [
        cell(position.coin),
        cell(position.side || "-"),
        cell(qty.format(Math.abs(Number(position.szi) || 0))),
        cell(priceText(position.entry)),
        cell(formatAmount(position.notional)),
        cell(signed(position.pnl), pnlClass(position.pnl)),
        cell(position.account_count ? String(position.account_count) : "-"),
      ]);
      card.append(table(["币种", "方向", "数量", "加权均价", "仓位价值", "浮动盈亏", "账户数"], positionRows));
    } else {
      card.append(make("div", "process-empty", pendingPositions ? "正在读取这些账户的当前持仓..." : state.autohuntPositionsStatus === "error" ? "持仓读取失败，但账户列表已正常显示。" : "这些记录账户当前未平仓头寸。"));
    }

    if (row.accounts.length) {
      const rows = row.accounts.map((account) => {
        const action = cell("", "table-action");
        action.append(autohuntPnlTrigger(account.address, account.alias));
        return [
          cell(account.alias || "-"),
          addressCell(account.address),
          cell(formatAmount(account.account_value)),
          cell(relativeTime(account.scanned_at)),
          action,
        ];
      });
      card.append(table(["别名", "地址", "账户价值", "记录时间", "走势"], rows));
    } else {
      card.append(make("div", "process-empty", "该进程没有已收集账户"));
    }
    body.append(card);
  }

  if (view.collected.length) {
    body.append(sectionTitle(`已收集大户（${view.collected.length}）`));
    const rows = view.collected.map((account) => {
      const action = cell("", "table-action");
      action.append(autohuntPnlTrigger(account.address, account.alias));
      return [
        cell(account.alias || "-"),
        addressCell(account.address),
        cell(formatAmount(account.account_value)),
        cell(formatAmount(account.volume)),
        cell(signed(account.pnl), pnlClass(account.pnl)),
        cell(`${(Number(account.roi) || 0).toFixed(1)}%`, pnlClass(account.roi)),
        cell(`${((Number(account.win_rate) || 0) * 100).toFixed(1)}%`),
        cell((Number(account.score) || 0).toFixed(2)),
        action,
      ];
    });
    body.append(table(["别名", "地址", "账户价值", "成交量", "盈利", "ROI", "胜率", "评分", "走势"], rows));
  } else if (query) {
    const empty = make("div", "state-empty");
    empty.append(make("span", "", "没有匹配的收集大户。当前搜索词可能仍在过滤本地列表。 "));
    const clear = make("button", "row-button", "清空搜索");
    clear.type = "button";
    clear.addEventListener("click", () => {
      state.autohuntQuery = "";
      els.autohuntSearch.value = "";
      localStorage.removeItem("hl.autohuntQuery");
      state.autohuntSearchResults = [];
      state.autohuntSearchStatus = "";
      renderAutohunt(state.autohuntData || { processes: [], collected: [] }, panel("autohunt").querySelector(".panel-body"));
    });
    empty.append(clear);
    body.append(empty);
  }

  bindAutohuntPnlTriggers(body);

  if (state.autohuntPnlAddress && !state.autohuntPnl) {
    const known = (data.collected || []).find((account) => account.address === state.autohuntPnlAddress)
      || (data.processes || []).flatMap((process) => process.accounts || []).find((account) => account.address === state.autohuntPnlAddress);
    setTimeout(() => loadAutohuntPnl(state.autohuntPnlAddress, known?.alias || state.autohuntPnlAlias), 0);
  }
  if (state.autohuntHuntId && !state.autohuntHunt) {
    setTimeout(() => pollAutohuntHunt(state.autohuntHuntId), 0);
  }
  if ((data.processes || []).length && state.autohuntPositions === null) {
    setTimeout(() => loadAutohuntPositions(), 0);
  }
}

async function loadAutohuntPositions() {
  const token = ++state.autohuntPositionsToken;
  try {
    const data = await request("/api/autohunt/positions");
    if (token !== state.autohuntPositionsToken || state.view !== "autohunt") return;
    state.autohuntPositions = data.positions || {};
    state.autohuntPositionsStatus = "ready";
    if (state.autohuntData) renderAutohunt(state.autohuntData, panel("autohunt").querySelector(".panel-body"));
  } catch (error) {
    if (token !== state.autohuntPositionsToken || state.view !== "autohunt") return;
    state.autohuntPositions = {};
    state.autohuntPositionsStatus = "error";
    if (state.autohuntData) renderAutohunt(state.autohuntData, panel("autohunt").querySelector(".panel-body"));
  }
}

async function loadAutohuntSearch() {
  const query = state.autohuntQuery.trim();
  const token = ++state.autohuntSearchToken;
  if (query.length < 2) {
    state.autohuntSearchResults = [];
    state.autohuntSearchStatus = "";
    renderAutohunt(state.autohuntData || { processes: [], collected: [] }, panel("autohunt").querySelector(".panel-body"));
    return;
  }
  state.autohuntSearchStatus = "loading";
  renderAutohunt(state.autohuntData || { processes: [], collected: [] }, panel("autohunt").querySelector(".panel-body"));
  try {
    const data = await request(`/api/autohunt/search?limit=30&q=${encodeURIComponent(query)}`);
    if (token !== state.autohuntSearchToken) return;
    state.autohuntSearchResults = data.results || [];
    state.autohuntSearchStatus = "ready";
    renderAutohunt(state.autohuntData || { processes: [], collected: [] }, panel("autohunt").querySelector(".panel-body"));
  } catch (error) {
    if (token !== state.autohuntSearchToken) return;
    state.autohuntSearchResults = [];
    state.autohuntSearchStatus = "error";
    renderAutohunt(state.autohuntData || { processes: [], collected: [] }, panel("autohunt").querySelector(".panel-body"));
  }
}

async function runAutohuntHunt() {
  const coins = parseAutohuntCoins(state.autohuntQuery);
  const limit = Number(els.autohuntLimit.value || 0) || 0;
  const token = ++state.autohuntHuntToken;
  state.autohuntHunt = {
    status: "running", coins, limit,
    progress_done: 0, progress_total: 0, results: [], scanned_count: 0,
  };
  renderAutohunt(state.autohuntData || { processes: [], collected: [] }, panel("autohunt").querySelector(".panel-body"));
  try {
    const job = await request("/api/autohunt/hunt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit, coins, swing: false }),
    });
    if (token !== state.autohuntHuntToken) return;
    state.autohuntHuntId = job.job_id || "";
    state.autohuntHunt = job;
    sessionStorage.setItem("hl.autohuntJob", state.autohuntHuntId);
    renderAutohunt(state.autohuntData || { processes: [], collected: [] }, panel("autohunt").querySelector(".panel-body"));
    pollAutohuntHunt(state.autohuntHuntId);
  } catch (error) {
    if (token !== state.autohuntHuntToken) return;
    state.autohuntHunt = { status: "error", coins, error: apiErrorText(error), results: [] };
    renderAutohunt(state.autohuntData || { processes: [], collected: [] }, panel("autohunt").querySelector(".panel-body"));
  }
}

async function pollAutohuntHunt(jobId) {
  const token = ++state.autohuntHuntToken;
  while (state.autohuntHuntId === jobId) {
    try {
      const job = await request(`/api/autohunt/hunt?job_id=${encodeURIComponent(jobId)}`);
      if (token !== state.autohuntHuntToken || state.autohuntHuntId !== jobId) return;
      state.autohuntHunt = job;
      renderAutohunt(state.autohuntData || { processes: [], collected: [] }, panel("autohunt").querySelector(".panel-body"));
      if (["success", "error", "not_found"].includes(job.status)) {
        if (job.status === "not_found") {
          state.autohuntHuntId = "";
          sessionStorage.removeItem("hl.autohuntJob");
        } else if (job.status === "success") {
          loadView(true);
        }
        return;
      }
    } catch (_) {
      // Keep polling; a brief local-server or proxy hiccup should not lose the job.
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}
// ---------------------------------------------------------------- 链上分析

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

function renderReportSet(data, body) {
  for (const report of data.reports || []) {
    body.append(sectionTitle(report.account || "账户"));
    renderReport(report, body);
  }
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
  else if (data.multi) renderReportSet(data, body);
  else renderReport(data, body);
}

function endpoint(view, rawAddress = "") {
  const address = encodeURIComponent(rawAddress);
  if (view === "overview") return `/api/overview?address=${address}`;
  if (view === "fills") return `/api/fills?address=${address}&window_min=${state.fillsWindow}`;
  if (view === "orders") return `/api/orders?address=${address}&level=${state.ordersLevel}`;
  if (view === "chart") {
    const coin = encodeURIComponent(state.chartCoin || "BTC");
    const fillWindow = Number(state.fillWindow) || 1440;
    return `/api/chart?address=${address}&coin=${coin}&interval=${state.chartInterval}&fill_window_min=${fillWindow}&merge=${state.merge}`;
  }
  if (view === "tpsl") return `/api/tpsl?address=${address}`;
  if (view === "history") return `/api/history?address=${address}`;
  if (view === "autohunt") return "/api/autohunt?positions=0";
  if (view === "whale") return "/api/whale";
  if (view === "whale-tx") return "/api/whale/tx/analysis?asset=" + encodeURIComponent(state.wtaAsset) + "&window=" + encodeURIComponent(state.wtaWindow);
  if (view === "settings") return "/api/settings";
  return `/api/events?address=${address}&limit=100`;
}

const CHART_OVERLAY_KINDS = ["orders", "fills", "positions"];
const CHART_OVERLAY_LABELS = { orders: "挂单区间", fills: "成交区间", positions: "持仓" };
const CHART_OVERLAY_STATE_KEYS = { orders: "whaleOrders", fills: "whaleFills", positions: "whalePositions" };

function activeChartOverlayKinds() {
  return CHART_OVERLAY_KINDS.filter((kind) => state.overlays[CHART_OVERLAY_STATE_KEYS[kind]]);
}

function chartOverlayEndpoint(kind) {
  const coin = encodeURIComponent(state.chartCoin || "BTC");
  const fillWindow = Number(state.fillWindow) || 1440;
  const proc = encodeURIComponent(state.autohuntProc || "");
  return `/api/chart/overlay?kind=${kind}&coin=${coin}&fill_window_min=${fillWindow}&proc=${proc}&merge=${state.merge}`;
}

function renderChartOverlayStatus() {
  const node = els.chartOverlayStatus;
  if (!node) return;
  const kinds = activeChartOverlayKinds();
  if (!kinds.length) {
    node.replaceChildren();
    node.hidden = true;
    return;
  }
  node.hidden = false;
  node.replaceChildren();
  for (const kind of kinds) {
    const status = state.chartOverlayStatus[kind] || "idle";
    const label = CHART_OVERLAY_LABELS[kind];
    const text = status === "loading"
      ? `${label} 加载中`
      : status === "ready"
        ? `${label} 已加载`
        : status === "error"
          ? `${label} 加载失败`
          : label;
    const item = make("div", `overlay-status-item ${status}`);
    item.append(make("i"), make("span", "", text));
    node.append(item);
  }
}

async function ensureChartOverlays(force = false) {
  const kinds = activeChartOverlayKinds();
  const token = ++state.chartOverlayToken;
  const nextStatus = {};
  for (const kind of kinds) {
    nextStatus[kind] = force ? "loading" : (state.chartOverlayStatus[kind] || "loading");
  }
  state.chartOverlayStatus = nextStatus;
  renderChartOverlayStatus();
  if (!state.chartData) return;
  const tasks = kinds.filter((kind) => force || state.chartOverlayStatus[kind] !== "ready");
  if (!tasks.length) return;
  await Promise.all(tasks.map(async (kind) => {
    try {
      const data = await request(chartOverlayEndpoint(kind));
      if (token !== state.chartOverlayToken || !state.chartData) return;
      state.chartData.whale_process = data.process || "";
      state.chartData.whale_account_count = data.account_count || 0;
      if (kind === "orders") state.chartData.whale_order_zones = data.order_zones || [];
      if (kind === "fills") state.chartData.whale_fill_zones = data.fill_zones || [];
      if (kind === "positions") state.chartData.whale_positions = data.positions || [];
      state.chartOverlayStatus[kind] = "ready";
      renderChartOverlayStatus();
      drawChartOverlays(state.chartData, { preservePopups: true });
      updatePositionOverlay();
      updateOrderZoneOverlays();
    } catch (_) {
      if (token !== state.chartOverlayToken) return;
      state.chartOverlayStatus[kind] = "error";
      renderChartOverlayStatus();
    }
  }));
}
function setView(view) {
  state.view = view;
  for (const button of els.viewNav.querySelectorAll(".nav-button")) {
    button.classList.toggle("active", button.dataset.view === view);
  }
  for (const node of document.querySelectorAll(".panel")) {
    node.classList.toggle("active", node.dataset.panel === view);
  }
  renderAccountPickers();
  if (view === "autohunt" && state.autohuntQuery) {
    setTimeout(() => loadAutohuntSearch(), 0);
  }
  if (view === "chart" && state.chart) {
    setTimeout(() => state.chart.applyOptions({
      width: els.priceChart.clientWidth,
      height: els.priceChart.clientHeight,
    }), 0);
  }
}

const ACCOUNT_VIEWS = new Set(["overview", "fills", "orders", "tpsl", "history", "chart", "events"]);

function accountNameFor(address) {
  const account = state.accounts.find((item) => item.address === address);
  return account ? accountLabel(account) : shortAddress(address);
}

function aggregateOverview(items, addresses) {
  const summaryKeys = ["account_value", "withdrawable", "unrealized_pnl", "total_ntl_pos"];
  const summary = {};
  for (const key of summaryKeys) summary[key] = items.reduce((total, item) => total + (Number(item.summary?.[key]) || 0), 0);
  const positionMap = new Map();
  for (const [index, item] of items.entries()) {
    for (const row of item.positions || []) {
      const key = row.coin;
      const current = positionMap.get(key) || {
        coin: row.coin, szi: 0, notional: 0, pnl: 0, entries: new Set(), leverages: new Set(), accounts: new Set(),
      };
      current.szi += Number(row.szi) || 0;
      current.notional += Number(row.notional) || 0;
      current.pnl += Number(row.pnl) || 0;
      if (row.entry) current.entries.add(String(row.entry));
      if (row.leverage) current.leverages.add(String(row.leverage));
      current.accounts.add(accountNameFor(addresses[index]));
      positionMap.set(key, current);
    }
  }
  const positions = [...positionMap.values()]
    .map((row) => ({
      ...row,
      entry: row.entries.size === 1 ? [...row.entries][0] : "",
      leverage: row.leverages.size === 1 ? [...row.leverages][0] : "",
      account: [...row.accounts].join("、"),
    }))
    .sort((a, b) => b.notional - a.notional);
  const spotMap = new Map();
  for (const item of items) {
    for (const row of item.spot || []) {
      const current = spotMap.get(row.coin) || { coin: row.coin, total: 0, hold: 0 };
      current.total += Number(row.total) || 0;
      current.hold += Number(row.hold) || 0;
      spotMap.set(row.coin, current);
    }
  }
  return { type: "overview", summary, positions, spot: [...spotMap.values()].sort((a, b) => b.total - a.total), generated_at: Date.now(), multi: true, addresses };
}

function aggregateFills(items, addresses) {
  const coins = new Map();
  let recent = [];
  const result = { type: "fills", window_min: items[0]?.window_min, window_label: items[0]?.window_label, count: 0, notional: 0, buy: 0, sell: 0, realized_pnl: 0 };
  for (const [index, item] of items.entries()) {
    result.count += Number(item.count) || 0;
    result.notional += Number(item.notional) || 0;
    result.buy += Number(item.buy) || 0;
    result.sell += Number(item.sell) || 0;
    result.realized_pnl += Number(item.realized_pnl) || 0;
    for (const row of item.coins || []) {
      const current = coins.get(row.coin) || { coin: row.coin, count: 0, notional: 0, buy: 0, sell: 0, pnl: 0 };
      current.count += Number(row.count) || 0;
      current.notional += Number(row.notional) || 0;
      current.buy += Number(row.buy) || 0;
      current.sell += Number(row.sell) || 0;
      current.pnl += Number(row.pnl) || 0;
      coins.set(row.coin, current);
    }
    recent = recent.concat((item.recent || []).map((row) => ({ ...row, account: accountNameFor(addresses[index]) })));
  }
  result.coins = [...coins.values()].sort((a, b) => b.notional - a.notional);
  result.recent = recent.sort((a, b) => Number(b.time) - Number(a.time)).slice(0, 100);
  result.generated_at = Date.now();
  result.multi = true;
  result.addresses = addresses;
  return result;
}

function aggregateEvents(items, addresses) {
  const events = [];
  for (const [index, item] of items.entries()) {
    events.push(...(item.events || []).map((event) => ({ ...event, account: accountNameFor(addresses[index]) })));
  }
  return { type: "events", events: events.sort((a, b) => Number(b.time) - Number(a.time)).slice(0, 100), generated_at: Date.now(), multi: true, addresses };
}

function aggregateChart(items, addresses) {
  const first = items[0] || {};
  const addAccount = (rows, index) => (rows || []).map((row) => ({ ...row, account: accountNameFor(addresses[index]) }));
  const positions = items.flatMap((item, index) => {
    const position = item.position;
    if (!position || !(Number(position.entry) > 0)) return [];
    return [{ ...position, account: accountNameFor(addresses[index]) }];
  });
  return {
    ...first,
    order_zones: items.flatMap((item, index) => addAccount(item.order_zones, index)),
    fill_zones: items.flatMap((item, index) => addAccount(item.fill_zones, index)),
    tpsl_lines: items.flatMap((item, index) => addAccount(item.tpsl_lines, index)),
    whale_process: first.whale_process || "",
    whale_account_count: first.whale_account_count || 0,
    whale_order_zones: first.whale_order_zones || first.whale_zones || [],
    whale_fill_zones: first.whale_fill_zones || [],
    whale_positions: first.whale_positions || [],
    position: null,
    positions,
    generated_at: Date.now(),
    multi: true,
    addresses,
  };
}

function aggregateViewData(view, items, addresses) {
  if (items.length === 1) return items[0];
  if (view === "overview") return aggregateOverview(items, addresses);
  if (view === "fills") return aggregateFills(items, addresses);
  if (view === "events") return aggregateEvents(items, addresses);
  if (view === "chart") return aggregateChart(items, addresses);
  return { type: "report", multi: true, reports: items.map((item, index) => ({ ...item, account: accountNameFor(addresses[index]) })), generated_at: Date.now(), addresses };
}

async function loadView(force = false) {
  if (state.busy) {
    state.loadPending = true;
    return;
  }
  const view = state.view;
  const addresses = selectedAddresses();
  if (["whale", "whale-tx", "settings"].includes(view)) {
    if (view === "whale-tx" && !els.wtaAsset.children.length) await loadWtaAssets();
  } else if (ACCOUNT_VIEWS.has(view) && !addresses.length) {
    clearState(view);
    panel(view).querySelector(".panel-body").replaceChildren();
    showState(view, "empty", "请选择一个或多个账户");
    return;
  }
  state.busy = true;
  els.refresh.disabled = true;
  setStateLoading(view);
  try {
    const data = ACCOUNT_VIEWS.has(view)
      ? aggregateViewData(view, await Promise.all(addresses.map((address) => request(endpoint(view, address)))), addresses)
      : await request(endpoint(view));
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
    if (state.loadPending) {
      state.loadPending = false;
      setTimeout(() => loadView(true), 0);
    }
  }
}

async function loadState() {
  const payload = await request("/api/state");
  state.accounts = payload.accounts || [];
  const valid = new Set(state.accounts.map((account) => account.address));
  state.selectedAccounts = state.selectedAccounts.filter((address) => valid.has(address));
  persistSelectedAccounts();
  state.autohuntProcesses = payload.autohunt_processes || [];
  if (payload.settings) applyTheme(payload.settings);
  els.network.textContent = payload.network || "";
  els.version.textContent = payload.version ? "v" + payload.version : "";
  renderAccountPickers();
  renderContext();
}

els.viewNav.addEventListener("click", (event) => {
  const button = event.target.closest(".nav-button");
  if (!button) return;
  setSidebarOpen(false);
  if (button.dataset.view === state.view) return;
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

let chartReloadTimer = null;
function scheduleChartLoad(delay = 120) {
  if (state.view !== "chart") return;
  if (chartReloadTimer) clearTimeout(chartReloadTimer);
  chartReloadTimer = setTimeout(() => {
    chartReloadTimer = null;
    loadView(true);
  }, delay);
}
els.chartFillWindow.addEventListener("change", () => {
  state.fillWindow = els.chartFillWindow.value;
  localStorage.setItem("hl.fillWindow", state.fillWindow);
  syncFillWindowLabel();
  if (state.view === "chart") scheduleChartLoad();
});

els.chartInterval.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  state.chartInterval = button.dataset.interval;
  for (const node of els.chartInterval.querySelectorAll("button")) node.classList.toggle("active", node === button);
  if (state.view === "chart") scheduleChartLoad();
});

els.chartSymbol.addEventListener("change", () => {
  state.chartCoin = els.chartSymbol.value;
  hidePositionPopup();
  hidePositionTooltip();
  if (state.view === "chart") scheduleChartLoad();
});

els.chartOverlays.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const key = button.dataset.overlay;
  state.overlays[key] = !state.overlays[key];
  button.classList.toggle("active", state.overlays[key]);
  if (state.view !== "chart") return;
  if (key === "whaleOrders" || key === "whaleFills" || key === "whalePositions") {
    if (state.overlays[key]) {
      ensureChartOverlays(false);
    } else if (state.chartData) {
      if (key === "whaleOrders") state.chartData.whale_order_zones = [];
      if (key === "whaleFills") state.chartData.whale_fill_zones = [];
      if (key === "whalePositions") state.chartData.whale_positions = [];
      drawChartOverlays(state.chartData, { preservePopups: true });
      updatePositionOverlay();
      updateOrderZoneOverlays();
    }
    renderChartOverlayStatus();
    return;
  }
  if (state.chartData) {
    drawChartOverlays(state.chartData);
    updatePositionOverlay();
    updateOrderZoneOverlays();
  }
});

function showPositionTooltip(event) {
  const position = chartPositions(state.chartData).find((row) => Number(row.entry) > 0);
  if (!position) return;
  const containerRect = els.chartContainer.getBoundingClientRect();
  const tooltip = els.positionTooltip;
  const account = position.account ? ` · ${position.account}` : "";
  tooltip.textContent = `${position.side}${account} · ${pnlLabel(position.pnl)}`;
  tooltip.hidden = false;
  const left = Math.min(
    Math.max(8, event.clientX - containerRect.left - tooltip.offsetWidth / 2),
    Math.max(8, els.chartContainer.clientWidth - tooltip.offsetWidth - 8),
  );
  const top = Math.min(
    Math.max(8, (parseFloat(els.positionHitbox.style.top) || 0) + 24),
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
els.chartContainer.addEventListener("click", handlePositionClick, true);
els.priceChart.addEventListener("click", handleZoneClick);

els.positionHitbox.addEventListener("mouseenter", showPositionTooltip);
els.positionHitbox.addEventListener("mousemove", showPositionTooltip);
els.positionHitbox.addEventListener("mouseleave", hidePositionTooltip);

els.positionHitbox.addEventListener("click", (event) => {
  event.stopPropagation();
  const position = chartPositions(state.chartData).find((row) => Number(row.entry) > 0);
  if (!position) return;
  if (els.positionPopup.hidden) renderPositionPopup(state.chartData, position, event);
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
  mergeTimer = setTimeout(() => ensureChartOverlays(true), 450);
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
let autohuntSearchTimer = null;
els.autohuntSearch.addEventListener("input", () => {
  clearTimeout(autohuntSearchTimer);
  autohuntSearchTimer = setTimeout(() => {
    state.autohuntQuery = els.autohuntSearch.value;
    localStorage.setItem("hl.autohuntQuery", state.autohuntQuery);
    if (state.view === "autohunt") loadAutohuntSearch();
  }, 300);
});
els.autohuntSearch.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    clearTimeout(autohuntSearchTimer);
    state.autohuntQuery = els.autohuntSearch.value;
    localStorage.setItem("hl.autohuntQuery", state.autohuntQuery);
    if (state.view === "autohunt") loadAutohuntSearch();
  }
});
els.autohuntLimit.value = localStorage.getItem("hl.autohuntLimit") || "0";
els.autohuntLimit.addEventListener("change", () => {
  localStorage.setItem("hl.autohuntLimit", els.autohuntLimit.value);
});
els.autohuntHunt.addEventListener("click", runAutohuntHunt);
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
els.accountDetail.addEventListener("click", (event) => {
  if (event.target === els.accountDetail) closeAccountDetail();
});
els.accountDetailClose.addEventListener("click", closeAccountDetail);
els.accountDetailWindow.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-window]");
  if (!button) return;
  state.accountDetailWindow = button.dataset.window;
  localStorage.setItem("hl.accountDetailWindow", state.accountDetailWindow);
  const current = state.accountDetail;
  if (current?.address) requestAccountDetail(current.address, current.alias);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !els.accountDetail.hidden) closeAccountDetail();
});

els.sidebarToggle.addEventListener("click", () => setSidebarOpen(!els.sidebar.classList.contains("open")));
els.sidebarClose.addEventListener("click", () => setSidebarOpen(false));
els.sidebarBackdrop.addEventListener("click", () => setSidebarOpen(false));

initFillWindowSelect();
setView("overview");
loadState()
  .then(() => loadView(true))
  .catch((error) => showState(state.view, "error", error.message));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && els.sidebar.classList.contains("open")) setSidebarOpen(false);
});