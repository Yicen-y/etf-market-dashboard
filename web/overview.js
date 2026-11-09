(() => {
  const get = id => document.getElementById(id);
  const meta = get("overview-meta");
  const retry = get("overview-retry");
  const content = get("overview-content");
  let overview;
  // Names for overview responses from servers started before name fields were added.
  const indexNames = {
    "480080": "成长100R",
    "480081": "价值100R",
    "H00821": "沪深300红利",
    "H00300": "沪深300",
    "H00918": "沪深300成长",
    "H00919": "沪深300价值",
    "932000CNY010": "中证2000",
    "H00811": "中证细分有色",
    "H00813": "中证细分化工",
    "H20180": "中证银行",
    "H20035": "沪深300非银金融",
    "H00922": "中证红利",
    "H20903": "中证A股",
    "H20915": "港股通高股息投资人民币全收益"
};
  const date = value => value ? value.replace(/^(\d{4})(\d{2})(\d{2})$/, "$1-$2-$3") : "—";
  const value = (n, scale = 1, suffix = "") => n == null ? "—" : (n * scale).toFixed(2) + suffix;

  function append(parent, tag, text) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    parent.append(node);
    return node;
  }

  function link(parent, strategy, day, label) {
    const params = new URLSearchParams({strategy});
    if (day) params.set("observed_date", day);
    append(parent, "a", label).href = "./index.html?" + params;
  }

  function eventLink(parent, event, label) {
    const scale = event.field === "return40Spread" ? 100 : 1;
    const suffix = scale === 100 ? " pp" : "";
    link(parent, event.strategy, event.date,
      date(event.date) + " · " + label + event.label + " · " +
      value(event.previous, scale, suffix) + " → " + value(event.value, scale, suffix) +
      "（当日阈值 " + value(event.threshold, scale, suffix) + "）");
  }

  function renderEvents() {
    const list = get("overview-events");
    list.replaceChildren();
    const events = overview.groups.flatMap(group => group.events.map(event => ({event, group})))
      .filter(({event}) => get("event-period").value === "5" || event.date === overview.observation_date)
      .sort((a, b) => b.event.date.localeCompare(a.event.date));
    for (const {event, group} of events) eventLink(append(list, "li"), event, group.name + " · ");
    if (!events.length) append(list, "li", "该区间无新触发");
  }

  function renderRows() {
    const rows = get("overview-rows");
    const filter = get("overview-filter").value;
    rows.replaceChildren();
    for (const group of overview.groups) {
      if (filter === "latest" && !group.events.some(event => event.date === overview.observation_date)) continue;
      if (filter === "recent" && !group.events.length) continue;
      if (filter === "quality" && group.quality === "完整") continue;
      const row = append(rows, "tr");
      const latest = group.events[0];
      link(append(row, "td"), group.id, latest?.date || group.data_date, group.name);
      append(row, "td", group.spread == null ? "—" : group.spread > 0 ? (group.a_name || indexNames[group.a] || "名称待补充") + "近40日相对占优" : group.spread < 0 ? (group.b_name || indexNames[group.b] || "名称待补充") + "近40日相对占优" : "持平");
      append(row, "td", value(group.spread, 100, " pp"));
      const distance = append(row, "td", value(group.distance, 100, "%"));
      const mean = group.states.find(state => state.threshold === "ratioMa242");
      if (mean) append(distance, "small", (mean.direction > 0 ? "均线上方" : mean.direction < 0 ? "均线下方" : "等于均线") + " " + mean.days + " 日").className = "overview-state";
      const rsi = append(row, "td", value(group.rsi));
      const relative = group.states.find(state => state.field === "rsi14" && state.threshold === 50);
      if (relative) append(rsi, "small", (relative.direction > 0 ? "高于50" : relative.direction < 0 ? "低于50" : "等于50") + " " + relative.days + " 日").className = "overview-state";
      const eventCell = append(row, "td", latest ? null : "近5日无新触发");
      if (latest) {
        const details = append(eventCell, "details");
        append(details, "summary", latest.label + "（" + group.events.length + "条）");
        for (const event of group.events) eventLink(append(details, "div"), event, "");
      }
      append(row, "td", date(latest?.date));
      append(row, "td", group.quality + " · " + date(group.data_date));
    }
    if (!rows.children.length) append(append(rows, "tr"), "td", "该筛选下无组合").colSpan = 8;
  }

  async function load() {
    retry.classList.add("hidden");
    content.classList.add("hidden");
    meta.textContent = "正在读取已发布快照…";
    try {
      const response = await fetch("/api/rotation/overview", {cache: "no-cache"});
      if (!response.ok) throw new Error("HTTP " + response.status);
      overview = await response.json();
      const triggered = overview.groups.filter(group => group.events.some(event => event.date === overview.observation_date)).length;
      const issues = overview.groups.filter(group => group.quality !== "完整").length;
      meta.textContent = "观察日 " + date(overview.observation_date) + " · 快照 " + overview.snapshot_id +
        " · 最新交易日触发 " + triggered + " 组 · 数据问题 " + issues + " 组";
      get("etf-dates").textContent = "实际基准日 " + date(overview.etf.base_date) + " · 数据日期 " + date(overview.etf.data_date);
      const etf = get("overview-etf");
      etf.replaceChildren();
      const items = [...Object.values(overview.etf.returns), {name: "50:50组合", value: overview.etf.portfolio},
        {name: "红利−成长差值", value: overview.etf.spread, unit: " pp"}];
      for (const item of items) {
        const cell = append(etf, "div");
        append(cell, "dt", item.name);
        append(cell, "dd", value(item.value, 100, item.unit || "%"));
      }
      renderEvents();
      renderRows();
      content.classList.remove("hidden");
    } catch (error) {
      meta.textContent = "轮动总览加载失败，请重试（" + error.message + "）";
      retry.classList.remove("hidden");
    }
  }

  retry.addEventListener("click", load);
  get("event-period").addEventListener("change", renderEvents);
  get("overview-filter").addEventListener("change", renderRows);
  load();
})();
