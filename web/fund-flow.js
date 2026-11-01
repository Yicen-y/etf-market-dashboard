const $ = id => document.getElementById(id);
const fmt = x => x == null ? "—" : Number(x).toFixed(3);
const chartTheme = window.DashboardChartTheme;
const securityColor = code => chartTheme.securityColor(code);
let charts = {};

function setStatus(text, kind = "") {
  const node = $("status");
  node.textContent = text;
  node.className = `status ${kind}`;
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
    ...chartTheme.createBaseChartOption({ dates, bottom: 72 }),
    tooltip: chartTheme.axisTooltip(() => valueFormatter),
    dataZoom: [{ type: "inside", filterMode: "none", start: 0, end: 100 }],
    xAxis: { type: "category", data: dates, axisLabel: { rotate: 40, hideOverlap: true } },
    yAxis: { type: "value", axisLine: { onZero: true } },
    series: Object.entries(grouped).map(([code, data]) => ({
      name: `${names[code] || code}（${code}）`,
      type: chartType,
      showSymbol: !isBar,
      ...(isBar ? { barMaxWidth: 12, barGap: "12%" } : {}),
      connectNulls: false,
      data: dates.map(date => data.find(x => x[0] === date)?.[1] ?? null),
      lineStyle: { color: securityColor(code), width: 2 },
      itemStyle: { color: securityColor(code) },
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
      setStatus("暂无已入库数据。点击“刷新全部数据”将自动补齐 2023-12-29 至今的历史数据。", "error");
      $("summary").innerHTML = "";
      Object.values(charts).forEach(chart => chart.clear());
      return;
    }
    const rows = payload.rows;
    const actualStart = rows.map(row => row.trade_date).filter(Boolean).sort()[0];
    const historyComplete = Boolean(payload.historyComplete) || Boolean(actualStart && payload.start && actualStart <= payload.start);
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
    renderChart("cumulative", rows, "cum_flow_yi", " 亿元", names);
    renderChart("daily", rows, "net_flow_yi", " 亿元", names, "bar");
    setStatus(
      `数据截至 ${payload.latestTradeDate}，当前组合为 ${members.join("、")}；显示区间 ${actualStart || payload.start} 至 ${payload.latestTradeDate}。${!historyComplete ? " 请点击“刷新全部数据”完成历史回填。" : ""}`,
      historyComplete && !quality ? "success" : "error",
    );
  } catch (error) {
    setStatus(`读取失败：${error.message}`, "error");
  }
}

async function refresh({ backfill = true, silent = false } = {}) {
  const button = $("refresh");
  if (!silent) {
    button.disabled = true;
    button.textContent = backfill ? "刷新历史数据中…" : "增量更新中…";
    setStatus("正在调用交易所份额接口和独立NAV接口…");
  }
  try {
    const response = await fetch(`/api/fund-flow/sync?backfill=${backfill}`, { method: "POST" });
    const body = await response.json();
    if (!response.ok) throw Error(body.detail || "读取失败");
    if (!silent) {
      if (body.warnings?.length) setStatus(`刷新完成，但有提示：${body.warnings.join("；")}`, "error");
      else setStatus(`刷新完成，已执行${body.mode === "backfill" ? "历史回填" : "增量更新"}。`, "success");
    }
    await load();
  } catch (error) {
    if (!silent) setStatus(`刷新失败：${error.message}`, "error");
  } finally {
    if (!silent) {
      button.disabled = false;
      button.textContent = "刷新全部数据";
    }
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
  observeChartContainers();
  $("preset").addEventListener("change", load);
  $("start").addEventListener("change", load);
  $("refresh").addEventListener("click", () => refresh({ backfill: true }));
  window.addEventListener("resize", () => Object.values(charts).forEach(chart => chart.resize()));
  load().then(() => refresh({ backfill: false, silent: true }));
}

window.addEventListener("DOMContentLoaded", init);
