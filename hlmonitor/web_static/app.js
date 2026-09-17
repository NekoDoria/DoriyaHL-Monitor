const state = {
  accounts: [],
  selected: localStorage.getItem("hl.selected") || "",
  view: "overview",
  fillsWindow: "1440",
  ordersLevel: "auto",
  chartCoin: "",
  chartInterval: "15m",
  merge: Math.min(4, Math.max(0.25, parseFloat(localStorage.getItem("hl.merge")) || 1)),
  chartData: null,
  overlays: { orders: true, fills: true, tpsl: true, volume: true, whale: false },
  busy: false,
  chart: null,
  candleSeries: null,
  volumeSeries: null,
  priceLines: [],
  zoneRects: [],
  overlayFrame: null,
};

const els = {
  sidebar: document.getElementById("sidebar"),
  sidebarToggle: document.getElementById("sidebar-toggle"),
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
  mergeSlider: document.getElementById("merge-slider"),
  mergeValue: document.getElementById("merge-value"),
  positionHitbox: document.getElementById("position-hitbox"),
  positionTooltip: document.getElementById("position-tooltip"),
  positionPopup: document.getElementById("position-popup"),
  priceAutoButton: document.getElementById("price-auto-button"),
};

function chartPanel() {
  return panel("chart");
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
const compactUsd = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 2,
});
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

function formatUsd(value, compact = false) {
  return (compact ? compactUsd : usd).format(Number(value) || 0);
}

function formatCnAmount(value) {
  const raw = Number(value);
  const number = Number.isFinite(raw) ? raw : 0;
  const abs = Math.abs(number);
  const sign = '$';
  if (abs >= 100000000) return sign + (number / 100000000).toFixed(2) + '亿';
  if (abs >= 10000000) return sign + (number / 10000000).toFixed(2) + '千万';
  if (abs >= 1000000) return sign + (number / 1000000).toFixed(2) + '百万';
  if (abs >= 10000) return sign + (number / 10000).toFixed(2) + '万';
  return usd.format(number);
}

function priceFormat(value) {
  value = Number(value) || 0;
  const precision = value >= 1000 ? 2 : value >= 100 ? 3 : value >= 1 ? 4 : value >= 0.01 ? 5 : 7;
  return { type: "price", precision, minMove: Number((0.1 ** precision).toFixed(precision)) };
}

function signed(value, formatter = formatUsd) {
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
    text.append(make("div", "account-name", accountLabel(account)));
    text.append(make("div", "account-address", shortAddress(account.address)));
    item.append(
      make("span", "account-avatar", (account.alias || account.address.slice(2, 4)).slice(0, 2).toUpperCase()),
      text,
    );
    if (account.source !== "config") {
      const remove = make("button", "remove-account", "×");
      remove.title = "移除";
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
      els.sidebar.classList.remove("open");
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
    metric("账户净值", formatUsd(summary.account_value)),
    metric("可提取", formatUsd(summary.withdrawable)),
    metric("浮动盈亏", signed(summary.unrealized_pnl), pnlClass(summary.unrealized_pnl)),
    metric("持仓名义", formatUsd(summary.total_ntl_pos)),
  );
  body.append(metrics, sectionTitle("合约持仓"));
  const rows = data.positions.map((row) => [
    cell(row.coin),
    cell(sideText(row)),
    cell(qty.format(Math.abs(row.szi))),
    cell(formatUsd(row.notional)),
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
    metric("成交额", formatUsd(data.notional, true)),
    metric("成交笔数", String(data.count)),
    metric("已实现盈亏", signed(data.realized_pnl), pnlClass(data.realized_pnl)),
    metric("窗口", data.window_label),
  );
  body.append(metrics, sectionTitle("币种统计"));
  body.append(table(["币种", "笔数", "成交额", "买入", "卖出", "盈亏"], data.coins.slice(0, 20).map((row) => [
    cell(row.coin), cell(String(row.count)), cell(formatUsd(row.notional)),
    cell(formatUsd(row.buy)), cell(formatUsd(row.sell)), cell(signed(row.pnl), pnlClass(row.pnl)),
  ])));
  body.append(sectionTitle("最近成交"));
  body.append(table(["时间", "币种", "方向", "数量", "价格", "金额", "盈亏"], data.recent.slice(0, 30).map((row) => [
    cell(timeText(row.time)), cell(row.coin), cell(sideText(row)), cell(qty.format(row.size)),
    cell(qty.format(row.price)), cell(formatUsd(row.notional)), cell(signed(row.closed_pnl), pnlClass(row.closed_pnl)),
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
    addPriceLine(row.avg_px, color, `${label} ${formatUsd(row.avg_px, true)}`, 2);
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
}

function clearOrderZoneOverlays() {
  els.zoneLayer.replaceChildren();
  state.zoneRects = [];
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

const CHART_FILL_WINDOWS = {
  "1m": 60,
  "5m": 240,
  "15m": 1440,
  "1h": 4320,
  "4h": 10080,
  "1d": 10080,
};
const ZONE_DIR_MAP = {
  "Open Long": "开多",
  "Close Long": "平多",
  "Open Short": "开空",
  "Close Short": "平空",
};

function zoneDirectionLabel(row) {
  if (row.kind === "whale") return row.side_raw === "B" ? "大户多" : "大户空";
  if (row.kind === "fill") {
    const mapped = ZONE_DIR_MAP[String(row.dir || "")];
    if (mapped) return mapped;
    return row.side_raw === "B" ? "开多" : "开空";
  }
  if (row.kind === "tpsl") return row.label || "止盈止损";
  return row.side_raw === "B" ? "挂多" : "挂空";
}

function zoneKindLabel(row) {
  if (row.kind === "whale") return "Autohunt 区间";
  if (row.kind === "fill") return "成交区间";
  if (row.kind === "tpsl") return row.label || "止盈止损";
  return "挂单区间";
}
function zoneTooltipText(row) {
  const accounts = row.accounts ? ` · ${row.accounts}账户` : "";
  return `${zoneKindLabel(row)} · ${zoneDirectionLabel(row)} · ${row.count}笔${accounts} · ${formatCnAmount(row.total_value)}`;
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
    positionDetailRow("总金额", formatCnAmount(row.total_value)),
  );
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

function addZoneRect(row, className) {
  const node = make("div", className);
  node.dataset.zoneIndex = String(state.zoneRects.length);
  node.addEventListener("mouseenter", (event) => showZoneTooltip(event, row));
  node.addEventListener("mousemove", (event) => showZoneTooltip(event, row));
  node.addEventListener("mouseleave", hideZoneTooltip);
  node.addEventListener("click", (event) => {
    event.stopPropagation();
    renderZonePopup(row, event);
  });
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
    positionDetailRow("名义价值", formatUsd(position.notional)),
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
  visibleOrders.forEach((row) => addZoneRect(row, `zone-rect order-zone ${row.side_raw === "B" ? "long" : "short"}`));
  visibleFills.forEach((row) => addZoneRect(row, `zone-rect fill-zone ${row.side_raw === "B" ? "long" : "short"}`));
  const visibleWhale = state.overlays.whale ? (data.whale_zones || []).slice(0, 20) : [];
  visibleWhale.forEach((row) => addZoneRect(row, `zone-rect whale-zone ${row.side_raw === "B" ? "long" : "short"}`));

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
  if (visibleWhale.length) {
    const label = data.whale_process ? `Autohunt(${data.whale_process})` : "Autohunt";
    els.chartLegend.append(legendChip(label, `${visibleWhale.length} 组 · ${data.whale_account_count || 0} 账户`, "#6eaaff"));
  }
  if (visibleTpsl.length) {
    els.chartLegend.append(legendChip("止盈止损", `${visibleTpsl.length} 条`, "#7c9cff"));
  }
  if (!visibleOrders.length && !visibleFills.length && !visibleTpsl.length && !visibleWhale.length) {
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
        cell(formatUsd(acc.account_value, true)),
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
      cell(formatUsd(row.account_value, true)),
      cell(formatUsd(row.volume, true)),
      cell(signed(row.pnl), pnlClass(row.pnl)),
      cell(`${(Number(row.roi) || 0).toFixed(1)}%`, pnlClass(row.roi)),
      cell(`${((Number(row.win_rate) || 0) * 100).toFixed(1)}%`),
      cell((Number(row.score) || 0).toFixed(2)),
    ]);
    body.append(table(["命名", "地址", "账户价值", "成交量", "盈亏", "ROI", "胜率", "评分"], rows));
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
    const fillWindow = CHART_FILL_WINDOWS[state.chartInterval] || 1440;
    const whaleParam = state.overlays.whale ? "&whale=1" : "";
    const mergeParam = `&merge=${state.merge}`;
    return `/api/chart?address=${address}&coin=${coin}&interval=${state.chartInterval}&fill_window_min=${fillWindow}${whaleParam}${mergeParam}`;
  }
  if (view === "tpsl") return `/api/tpsl?address=${address}`;
  if (view === "history") return `/api/history?address=${address}`;
  if (view === "autohunt") return "/api/autohunt";
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
  if (!state.selected) {
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
    if (state.view === view) showState(view, "error", error.message);
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
  if (key === "whale") {
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
els.sidebarToggle.addEventListener("click", () => els.sidebar.classList.toggle("open"));

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

setView("overview");
loadState()
  .then(() => loadView(true))
  .catch((error) => showState(state.view, "error", error.message));