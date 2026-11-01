(function (global) {
  const THEME_NAME = "etf-dashboard";
  const colors = {
    assetA: "#2c6bed",
    assetB: "#e67e32",
    benchmark: "#0f766e",
    portfolio: "#9461c9",
    difference: "#94a3b8",
    secondary: "#64748b",
    band: "#cbd5e1",
    positive: "#c9362b",
    negative: "#16834a",
  };
  const securityColors = {
    "510300": "#2c6bed",
    "510310": "#e67e32",
    "510330": "#0f766e",
    "159919": "#9461c9",
    "510360": "#c9362b",
    "159925": "#16834a",
  };
  const fallbackPalette = ["#2c6bed", "#e67e32", "#0f766e", "#9461c9", "#c9362b", "#16834a"];

  function finite(value) {
    const number = Number(value);
    return value == null || !Number.isFinite(number) ? null : number;
  }

  function signed(value, digits, suffix) {
    const number = finite(value);
    if (number == null) return "—";
    return `${number > 0 ? "+" : ""}${number.toFixed(digits)}${suffix}`;
  }

  function formatPercent(value, digits = 2) {
    const number = finite(value);
    return number == null ? "—" : signed(number * 100, digits, "%");
  }

  function formatPercentagePoints(value, digits = 2) {
    const number = finite(value);
    return number == null ? "—" : signed(number * 100, digits, "pp");
  }

  function formatRsi(value, digits = 2) {
    const number = finite(value);
    return number == null ? "—" : number.toFixed(digits);
  }

  function formatMoneyYi(value, digits = 3) {
    const number = finite(value);
    return number == null ? "—" : signed(number, digits, " 亿元");
  }

  function formatSharesWan(value, digits = 2) {
    const number = finite(value);
    return number == null ? "—" : `${number.toFixed(digits)} 万份`;
  }

  function securityColor(code) {
    if (securityColors[code]) return securityColors[code];
    const hash = String(code).split("").reduce((sum, char) => sum + char.charCodeAt(0), 0);
    return fallbackPalette[hash % fallbackPalette.length];
  }

  function axisTooltip(formatterForSeries) {
    return {
      trigger: "axis",
      confine: true,
      axisPointer: { type: "line", lineStyle: { color: "#94a3b8", type: "dashed" } },
      formatter(params) {
        const items = Array.isArray(params) ? params : [params];
        if (!items.length) return "";
        const rows = items.map(item => {
          const raw = Array.isArray(item.value) ? item.value.at(-1) : item.value;
          const formatter = formatterForSeries?.(item.seriesName) || formatRsi;
          return `${item.marker || ""}${item.seriesName}：${formatter(raw)}`;
        });
        return [`<strong>${items[0].axisValueLabel || items[0].name || ""}</strong>`, ...rows].join("<br>");
      },
    };
  }

  function createBaseChartOption({ dates, percentAxis = false, showXAxisLabels = true, bottom = 68 } = {}) {
    return {
      animation: false,
      legend: { bottom: 8, type: "scroll" },
      grid: { left: 64, right: 24, top: 28, bottom, containLabel: false },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: dates || [],
        axisLabel: { show: showXAxisLabels, color: "#64748b", hideOverlap: true },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#64748b", formatter: percentAxis ? value => `${(value * 100).toFixed(0)}%` : undefined },
        splitLine: { lineStyle: { color: "#e2e8f0" } },
      },
    };
  }

  const theme = {
    color: fallbackPalette,
    textStyle: { color: "#172033", fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif' },
    legend: { textStyle: { color: "#64748b", fontSize: 12 }, inactiveColor: "#cbd5e1" },
    tooltip: { backgroundColor: "rgba(23,32,51,.94)", borderWidth: 0, textStyle: { color: "#ffffff", fontSize: 12 } },
    categoryAxis: { axisLine: { lineStyle: { color: "#cbd5e1" } }, axisTick: { show: false }, axisLabel: { color: "#64748b" } },
    valueAxis: { axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: "#64748b" }, splitLine: { lineStyle: { color: "#e2e8f0" } } },
  };

  if (global.echarts) global.echarts.registerTheme(THEME_NAME, theme);
  global.DashboardChartTheme = {
    THEME_NAME,
    colors,
    securityColor,
    formatPercent,
    formatPercentagePoints,
    formatRsi,
    formatMoneyYi,
    formatSharesWan,
    axisTooltip,
    createBaseChartOption,
    init(element) { return global.echarts.init(element, THEME_NAME); },
  };
})(window);
