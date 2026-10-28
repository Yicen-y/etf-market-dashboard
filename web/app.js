const PRODUCTS = {
  "512530": { name: "沪深300红利ETF建信", short: "红利", role: "dividend", color: "#2c6bed" },
  "562310": { name: "沪深300成长ETF银华", short: "成长", role: "growth", color: "#e67e32" },
  "510330": { name: "沪深300ETF华夏", short: "沪深300", role: "benchmark", color: "#48a868" }
};
const DATA_URL = location.pathname.includes("/web/") ? "../data/etf_prices.json" : "data/etf_prices.json";
let dataset = null;
let chart = null;

function isoToKey(iso) { return iso.replaceAll("-", ""); }
function keyToIso(key) { return `${key.slice(0,4)}-${key.slice(4,6)}-${key.slice(6,8)}`; }
function resolveBenchmarkDate(selectedIso, records) {
  const selected = isoToKey(selectedIso);
  const valid = records.map(r => r.tradeDate).filter(d => d <= selected);
  if (!valid.length) throw new Error("选择日期早于可用数据范围。");
  return valid[valid.length - 1];
}
function buildSeries(records, selectedIso) {
  const actual = resolveBenchmarkDate(selectedIso, records);
  const baseline = records.find(r => r.tradeDate === actual).prices;
  return { actual, rows: records.map(r => {
    const returns = {};
    for (const code of Object.keys(PRODUCTS)) returns[code] = r.prices[code] == null || baseline[code] == null ? null : r.prices[code] / baseline[code] - 1;
    const d = returns["512530"], g = returns["562310"];
    return { ...r, returns, difference: d == null || g == null ? null : d - g, portfolio5050: d == null || g == null ? null : (d + g) / 2 };
  })};
}
function fmtPct(value) { return value == null ? "—" : `${(value * 100).toFixed(2)}%`; }
function cls(value) { return value > 0 ? "positive" : value < 0 ? "negative" : "neutral"; }
function renderKpis(last) {
  const items = [
    ["沪深300红利ETF建信", last.returns["512530"]], ["沪深300成长ETF银华", last.returns["562310"]],
    ["沪深300ETF华夏", last.returns["510330"]], ["红利/成长 50:50组合", last.portfolio5050]
  ];
  document.querySelector("#kpis").innerHTML = items.map(([label, value]) => `<div class="kpi"><div class="label">${label}</div><div class="value ${cls(value)}">${fmtPct(value)}</div></div>`).join("");
}
function renderChart(rows, actual) {
  rows = rows.filter(r => r.tradeDate >= actual);
  const dates = rows.map(r => keyToIso(r.tradeDate));
  const line = (name, code) => ({ name, type:"line", smooth:false, showSymbol:false, data:rows.map(r => r.returns[code]), lineStyle:{width:2, color:rows.at(-1)?.returns[code] >= 0 ? "#c9362b" : "#16834a"}, itemStyle:{color:rows.at(-1)?.returns[code] >= 0 ? "#c9362b" : "#16834a"} });
  chart.setOption({ animation:false, color:["#8a929e", "#2c6bed", "#e67e32", "#48a868", "#9a63c8"], tooltip:{trigger:"axis", valueFormatter:v => fmtPct(v)}, legend:{bottom:0, data:["差距（红利−成长）","沪深300红利ETF建信","沪深300成长ETF银华","沪深300ETF华夏","红利/成长各50%组合"]}, grid:{left:64,right:26,top:38,bottom:76}, xAxis:{type:"category",data:dates, axisLabel:{rotate:45}}, yAxis:{type:"value",axisLabel:{formatter:v => `${(v*100).toFixed(0)}%`},splitLine:{lineStyle:{color:"#dce3ee"}}}, series:[{name:"差距（红利−成长）",type:"bar",data:rows.map(r=>r.difference),barMaxWidth:8,opacity:.52}, line("沪深300红利ETF建信","512530"), line("沪深300成长ETF银华","562310"), line("沪深300ETF华夏","510330"), {name:"红利/成长各50%组合",type:"line",smooth:false,showSymbol:false,data:rows.map(r=>r.portfolio5050),lineStyle:{width:2,type:"dashed"},itemStyle:{color:"#9a63c8"}}] });
}
function renderTable(rows, actual) {
  rows = rows.filter(r => r.tradeDate >= actual);
  const head = ["交易日","红利收盘价","红利累计","成长收盘价","成长累计","沪深300收盘价","沪深300累计","红利−成长","50/50组合"];
  document.querySelector("#data-table thead").innerHTML = `<tr>${head.map(h=>`<th>${h}</th>`).join("")}</tr>`;
  document.querySelector("#data-table tbody").innerHTML = rows.map(r => `<tr><td>${keyToIso(r.tradeDate)}</td><td>${r.prices["512530"]?.toFixed(4) ?? "—"}</td><td class="${cls(r.returns["512530"])}">${fmtPct(r.returns["512530"])}</td><td>${r.prices["562310"]?.toFixed(4) ?? "—"}</td><td class="${cls(r.returns["562310"])}">${fmtPct(r.returns["562310"])}</td><td>${r.prices["510330"]?.toFixed(4) ?? "—"}</td><td class="${cls(r.returns["510330"])}">${fmtPct(r.returns["510330"])}</td><td class="${cls(r.difference)}">${fmtPct(r.difference)}</td><td class="${cls(r.portfolio5050)}">${fmtPct(r.portfolio5050)}</td></tr>`).join("");
}
function downloadCsv(rows) { const headers = ["tradeDate","dividendReturn","growthReturn","hs300Return","difference","portfolio5050"]; const lines = [headers.join(","), ...rows.map(r => [r.tradeDate, r.returns["512530"], r.returns["562310"], r.returns["510330"], r.difference, r.portfolio5050].join(","))]; const blob = new Blob(["\ufeff" + lines.join("\n")], {type:"text/csv;charset=utf-8"}); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "etf-dashboard.csv"; a.click(); URL.revokeObjectURL(a.href); }
function render() { try { const selected = document.querySelector("#benchmark-date").value; const result = buildSeries(dataset.records, selected); const last = result.rows[result.rows.length - 1]; document.querySelector("#benchmark-status").textContent = `实际基准交易日：${keyToIso(result.actual)}`; document.querySelector("#freshness").textContent = `数据截至 ${keyToIso(dataset.latestTradeDate)} · 更新时间 ${dataset.updatedAt || "未记录"}`; document.querySelector("#message").classList.add("hidden"); renderKpis(last); renderChart(result.rows, result.actual); renderTable(result.rows, result.actual); document.querySelector("#download-csv").onclick = () => downloadCsv(result.rows.filter(r => r.tradeDate >= result.actual)); } catch (error) { document.querySelector("#message").textContent = error.message; document.querySelector("#message").classList.remove("hidden"); } }
async function init() { chart = echarts.init(document.querySelector("#main-chart")); try { const response = await fetch(DATA_URL); dataset = await response.json(); const first = dataset.records[0]?.tradeDate; const input = document.querySelector("#benchmark-date"); if (first && input.value < keyToIso(first)) input.value = keyToIso(first); render(); input.addEventListener("change", render); document.querySelectorAll(".strategy-item").forEach(item => item.addEventListener("click", () => { document.querySelectorAll(".strategy-item").forEach(button => button.classList.remove("active")); item.classList.add("active"); })); document.querySelector("#add-strategy").addEventListener("click", () => { document.querySelector("#message").textContent = "自定义策略功能将在下一阶段开放。当前可先使用基准日期和已有 50:50 组合。"; document.querySelector("#message").classList.remove("hidden"); }); window.addEventListener("resize", () => chart.resize()); } catch (error) { document.querySelector("#message").textContent = `数据加载失败：${error.message}`; document.querySelector("#message").classList.remove("hidden"); } }
if (typeof window !== "undefined") window.addEventListener("DOMContentLoaded", init);
if (typeof module !== "undefined") module.exports = { resolveBenchmarkDate, buildSeries };

