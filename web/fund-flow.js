const $ = id => document.getElementById(id);
const fmt = x => x == null ? "—" : Number(x).toFixed(3);
const chartTheme = window.DashboardChartTheme;
const securityColor = code => chartTheme.securityColor(code);
let charts = {};
let tableRows = [], tableNames = {};
let historyComplete = false;
let selectedEtf = null;

function renderSelected(rows, names, codes) {
  if (!codes.includes(selectedEtf)) selectedEtf = codes[0] || null;
  const cards = $("etf-cards");
  cards.replaceChildren();
  for (const code of codes) {
    const history = rows.filter(row => row.etf_code === code);
    const latest = history.at(-1);
    const card = document.createElement("button");
    card.type = "button";
    card.className = "etf-card";
    card.style.setProperty("--etf-color", securityColor(code));
    card.setAttribute("aria-pressed", String(code === selectedEtf));
    const title = document.createElement("strong");
    title.textContent = `${names[code] || code} · ${code}`;
    const shares = document.createElement("span");
    shares.className = "etf-card-value";
    shares.textContent = latest.shares_adj_wan == null ? "份额暂无数据" : `${(latest.shares_adj_wan / 10000).toFixed(2)} 亿份`;
    const change = document.createElement("span");
    change.className = "etf-card-change";
    const delta = latest.delta_shares_wan;
    change.textContent = delta == null ? "份额变化：—" : `份额变化 ${delta >= 0 ? "+" : ""}${(delta / 10000).toFixed(2)} 亿份`;
    const flow = document.createElement("span");
    flow.className = "etf-card-flow";
    flow.textContent = latest.net_flow_yi == null ? "估算净申赎：—" : `估算净申赎 ${latest.net_flow_yi >= 0 ? "+" : ""}${latest.net_flow_yi.toFixed(2)} 亿元`;
    const meta = document.createElement("small");
    meta.textContent = `${latest.trade_date} · ${latest.status || "状态未知"}${latest.nav_adj == null ? " · NAV缺失" : ""}`;
    card.append(title, shares, change, flow, meta);
    card.addEventListener("click", () => { selectedEtf = code; renderSelected(rows, names, codes); });
    cards.append(card);
  }
  const selectedRows = rows.filter(row => row.etf_code === selectedEtf);
  const name = names[selectedEtf] || selectedEtf || "ETF";
  $("selected-daily-title").textContent = `每日份额变化 — ${name}`;
  $("selected-recent-title").textContent = `近3个月调整后份额 — ${name}`;
  const dailyDates = selectedRows.map(row => row.trade_date);
  const dailyValues = selectedRows.map(row => row.delta_shares_wan);
  charts.selectedDaily.setOption({
    ...chartTheme.createBaseChartOption({dates: dailyDates, bottom: 48}),
    grid: {left: 70, right: 20, top: 20, bottom: 48},
    tooltip: {trigger: "axis", valueFormatter: value => value == null ? "—" : `${Number(value).toFixed(2)} 万份`},
    dataZoom: [{type: "inside", filterMode: "none", start: 0, end: 100}],
    xAxis: {type: "category", data: dailyDates, axisLabel: {hideOverlap: true}},
    yAxis: {type: "value", name: "万份"},
    series: [{type: "bar", name: "份额变化", data: dailyValues, barMaxWidth: 12,
      itemStyle: {color: params => params.value >= 0 ? "#c9362b" : "#16834a"}}],
  }, true);
  const latestDay = selectedRows.at(-1)?.trade_date;
  const latestDate = latestDay ? new Date(`${latestDay}T00:00:00Z`) : null;
  const monthStart = latestDate ? new Date(Date.UTC(latestDate.getUTCFullYear(), latestDate.getUTCMonth() - 3, 1)) : null;
  const lastDayOfMonth = monthStart ? new Date(Date.UTC(monthStart.getUTCFullYear(), monthStart.getUTCMonth() + 1, 0)).getUTCDate() : 0;
  const cutoff = monthStart ? new Date(Date.UTC(monthStart.getUTCFullYear(), monthStart.getUTCMonth(), Math.min(latestDate.getUTCDate(), lastDayOfMonth))).toISOString().slice(0, 10) : null;
  const recent = selectedRows.filter(row => row.shares_adj_wan != null && (!cutoff || row.trade_date >= cutoff));
  charts.selectedRecent.setOption({
    ...chartTheme.createBaseChartOption({dates: recent.map(row => row.trade_date), bottom: 48}),
    grid: {left: 70, right: 20, top: 20, bottom: 48},
    tooltip: {trigger: "axis", valueFormatter: value => value == null ? "—" : `${Number(value).toFixed(2)} 万份`},
    xAxis: {type: "category", data: recent.map(row => row.trade_date), axisLabel: {hideOverlap: true}},
    yAxis: {type: "value", name: "万份", scale: true},
    series: [{type: "line", name: "调整后份额", data: recent.map(row => row.shares_adj_wan),
      showSymbol: false, areaStyle: {color: securityColor(selectedEtf), opacity: 0.12},
      lineStyle: {color: securityColor(selectedEtf), width: 2}, itemStyle: {color: securityColor(selectedEtf)}}],
  }, true);
}

function renderDataTable() {
  const tbody = $("fund-flow-table").tBodies[0];
  tbody.replaceChildren();
  const fragment = document.createDocumentFragment();
  const number = value => value == null ? "—" : Number(value).toFixed(3);
  for (const row of tableRows) {
    const tr = document.createElement("tr");
    for (const value of [row.trade_date, `${tableNames[row.etf_code] || row.etf_code}（${row.etf_code}）`, number(row.shares_adj_wan), number(row.nav_adj), number(row.net_flow_yi), number(row.cum_flow_yi), row.status || "—"]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      tr.append(cell);
    }
    fragment.append(tr);
  }
  tbody.append(fragment);
}

function setStatus(text, kind = "") {
  const node = $("status");
  node.textContent = text;
  node.className = `status ${kind}`;
  node.dataset.state = kind || "loading";
  node.setAttribute("aria-busy", String(!kind || kind === "loading"));
  node.setAttribute("role", kind === "error" ? "alert" : "status");
}

function renderChart(key, rows, valueKey, unit, names, chartType = "line") {
  const grouped = {};
  for (const row of rows) {
    (grouped[row.etf_code] ??= []).push([row.trade_date, row[valueKey]]);
  }
  const dates = [...new Set(rows.map(x => x.trade_date))];
  const isBar = chartType === "bar";
  const valueFormatter = valueKey === "shares_adj_wan" ? chartTheme.formatSharesWan : chartTheme.formatMoneyYi;
  charts[key].setOption({
    ...chartTheme.createBaseChartOption({ dates, bottom: 48 }),
    legend: { top: 0, left: 64, right: 24, type: "scroll" },
    grid: { left: 64, right: 24, top: 48, bottom: 48 },
    tooltip: chartTheme.axisTooltip(() => valueFormatter),
    dataZoom: [{ type: "inside", filterMode: "none", start: 0, end: 100 }],
    xAxis: { type: "category", data: dates, axisLabel: { rotate: 0, hideOverlap: true, interval: Math.max(0, Math.ceil(dates.length / 8) - 1), formatter: value => String(value).slice(0, 7) } },
    yAxis: { type: "value", axisLine: { onZero: true } },
    series: Object.entries(grouped).map(([code, data]) => ({
      name: `${names[code] || code}（${code}）`,
      type: chartType,
      showSymbol: !isBar,
      ...(isBar ? { barMaxWidth: 12, barGap: "12%" } : {}),
      connectNulls: false,
      data: dates.map(date => data.find(x => x[0] === date)?.[1] ?? null),
      lineStyle: { color: securityColor(code), width: 2 },
      itemStyle: { color: isBar ? params => Number(params.value) >= 0 ? "#c9362b" : "#16834a" : securityColor(code) },
    })),
  });
}

async function load() {
  setStatus("正在读取资金流数据…");
  const params = new URLSearchParams({ preset: $("preset").value, start: $("start").value, end: "latest" });
  try {
    const response = await fetch(`/api/fund-flow/overview?${params}`);
    const payload = await response.json();
    if (!response.ok) throw Error(payload.detail || "读取失败");
    const names = payload.names || {};
    const members = payload.codes.map(code => `${names[code] || code}（${code}）`);
    $("universe").innerHTML = members.map(item => `<span>${item}</span>`).join("");
    if (!payload.dataExists) {
      historyComplete = false;
      $("refresh").textContent = "补齐历史数据";
      tableRows = []; tableNames = {}; renderDataTable();
      setStatus("暂无已入库数据。点击“补齐历史数据”获取 2023-12-29 至今的历史数据。", "warning");
      $("summary").innerHTML = "";
      $("etf-cards").replaceChildren();
      Object.values(charts).forEach(chart => chart.clear());
      return true;
    }
    const rows = payload.rows;
    tableRows = rows; tableNames = names;
    if (!$('fund-flow-table-region').hidden) renderDataTable();
    const actualStart = rows.map(row => row.trade_date).filter(Boolean).sort()[0];
    historyComplete = Boolean(payload.historyComplete) || Boolean(actualStart && payload.start && actualStart <= payload.start);
    $("refresh").textContent = historyComplete ? "增量更新" : "补齐历史数据";
    const quality = rows.some(row => row.status !== "PASS");
    const statusText = !historyComplete
      ? `历史回填未完成（当前最早 ${payload.earliestTradeDate || actualStart || "无"}，目标 ${payload.start}）`
      : quality ? "存在质量提示" : "正常";
    $("summary").innerHTML = [
      ["最新交易日", payload.latestTradeDate],
      ["覆盖ETF数", payload.codes.length],
      ["指标记录数", rows.length],
      ["状态", statusText],
    ].map(([label, value]) => `<div class="summary-card"><div class="label">${label}</div><div class="value">${value}</div></div>`).join("");
    renderChart("shares", rows, "shares_adj_wan", "", names);
    renderSelected(rows, names, payload.codes);
    renderChart("cumulative", rows, "cum_flow_yi", " 亿元", names);
    renderChart("daily", rows, "net_flow_yi", " 亿元", names, "bar");
    setStatus(
      `数据截至 ${payload.latestTradeDate}，当前组合为 ${members.join("、")}；显示区间 ${actualStart || payload.start} 至 ${payload.latestTradeDate}。${!historyComplete ? " 请点击“补齐历史数据”完成历史回填。" : ""}`,
      historyComplete && !quality ? "success" : "warning",
    );
    return true;
  } catch (error) {
    tableRows = []; tableNames = {}; renderDataTable();
    $("summary").replaceChildren();
    $("etf-cards").replaceChildren();
    Object.values(charts).forEach(chart => chart.clear());
    setStatus(`读取失败：${error.message}`, "error");
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "ui-button";
    retry.textContent = "重试读取";
    retry.addEventListener("click", load, { once: true });
    $("status").append(" ", retry);
    return false;
  }
}

async function refresh({ backfill = !historyComplete } = {}) {
  const button = $("refresh");
  button.disabled = true;
  button.textContent = backfill ? "补齐历史数据中…" : "增量更新中…";
  setStatus("正在调用交易所份额接口和独立NAV接口…");
  try {
    const response = await fetch(`/api/fund-flow/sync?backfill=${backfill}`, { method: "POST" });
    const body = await response.json();
    if (response.status === 409) {
      setStatus("已有资金流更新正在执行，等待完成后重新读取数据…", "warning");
      for (let attempt = 0; attempt < 100; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 3000));
        const statusResponse = await fetch("/api/fund-flow/sync-status", {cache: "no-store"});
        if (!statusResponse.ok) throw Error("无法查询资金流更新状态，请重启服务后重试");
        if (!(await statusResponse.json()).updating) {
          if (await load()) setStatus("已有资金流更新结束，已重新读取最新数据。", "success");
          return;
        }
      }
      throw Error("资金流更新等待超过 5 分钟，请稍后重试");
    }
    if (!response.ok) throw Error(body.detail || "读取失败");
    if (!await load()) return;
    if (body.warnings?.length) setStatus(`刷新完成，但有提示：${body.warnings.join("；")}`, "warning");
    else setStatus(`刷新完成，已执行${body.mode === "backfill" ? "历史回填" : "增量更新"}；最新来源日期 ${body.latestTradeDate || "暂无新增"}。`, "success");
  } catch (error) {
    setStatus(`刷新失败：${error.message}`, "error");
  } finally {
    button.disabled = false;
    button.textContent = historyComplete ? "增量更新" : "补齐历史数据";
  }
}

function observeChartContainers() {
  if (!window.ResizeObserver) return;
  const observer = new ResizeObserver(entries => {
    entries.forEach(entry => Object.values(charts).find(chart => chart?.getDom() === entry.target)?.resize());
  });
  Object.values(charts).forEach(chart => observer.observe(chart.getDom()));
  window.fundFlowChartResizeObserver = observer;
}

function init() {
  charts.shares = chartTheme.init($("shares-chart"));
  charts.cumulative = chartTheme.init($("cumulative-flow-chart"));
  charts.daily = chartTheme.init($("daily-flow-chart"));
  charts.selectedDaily = chartTheme.init($("selected-daily-chart"));
  charts.selectedRecent = chartTheme.init($("selected-recent-chart"));
  observeChartContainers();
  $("preset").addEventListener("change", load);
  $("start").addEventListener("change", load);
  $("refresh").addEventListener("click", () => refresh());
  $("fund-flow-table-toggle").addEventListener("click", event => {
    const region = $("fund-flow-table-region");
    region.hidden = !region.hidden;
    event.currentTarget.setAttribute("aria-expanded", String(!region.hidden));
    event.currentTarget.textContent = region.hidden ? "展开交易日数据" : "收起交易日数据";
    if (!region.hidden) renderDataTable();
  });
  window.addEventListener("resize", () => Object.values(charts).forEach(chart => chart.resize()));
  load();
}

window.addEventListener("DOMContentLoaded", init);
