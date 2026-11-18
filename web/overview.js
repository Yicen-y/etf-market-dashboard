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
    const anchor = append(parent, "a", label);
    anchor.href = "./index.html?" + params;
    return anchor;
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
    for (const {event, group} of events) {
      const anchor = link(append(list, "li"), event.strategy, event.date);
      append(anchor, "span", date(event.date)).className = "overview-event-date";
      append(anchor, "strong", group.name);
      append(anchor, "span", event.label).className = "overview-event-type";
      const scale = event.field === "return40Spread" ? 100 : 1;
      const unit = scale === 100 ? " pp" : "";
      append(anchor, "span", `${value(event.previous, scale, unit)} → ${value(event.value, scale, unit)} · 当日阈值 ${value(event.threshold, scale, unit)}`).className = "overview-event-detail";
    }
    if (!events.length) {
      const empty = append(list, "li");
      empty.className = "overview-empty";
      append(empty, "strong", "该区间无新触发");
      append(empty, "span", "可切换到近5个交易日查看历史变化。");
    }
  }

  function visibleGroups() {
    const filter = get("overview-filter").value;
    return overview.groups.filter(group =>
      filter === "latest" ? group.events.some(event => event.date === overview.observation_date) :
      filter === "recent" ? group.events.length > 0 :
      filter === "quality" ? group.quality !== "完整" : true
    );
  }

  function renderMobileRows(groups) {
    const list = get("overview-mobile-list");
    list.replaceChildren();
    if (!groups.length) {
      append(list, "p", "该筛选下无组合").className = "overview-footnote";
      return;
    }
    for (const group of groups) {
      const card = append(list, "article");
      card.className = "overview-mobile-item";
      const head = append(card, "div");
      head.className = "overview-mobile-head";
      link(head, group.id, group.events[0]?.date || group.data_date, group.name);
      const quality = append(head, "span", group.quality === "完整" ? "完整" : "需核验");
      quality.className = "overview-quality";
      quality.dataset.state = group.quality === "完整" ? "complete" : "warning";
      append(card, "p", `数据日期 ${date(group.data_date)} · ${group.quality}`);
      const bias = group.spread == null ? "40日收益差暂不可用" : group.spread === 0 ? "近40日收益持平" :
        (group.spread > 0 ? group.a_name || indexNames[group.a] : group.b_name || indexNames[group.b]) + "近40日相对占优";
      append(card, "strong", bias);
      const details = append(card, "details");
      append(details, "summary", "查看指标与最近事件");
      const metrics = append(details, "dl");
      for (const [label, metric] of [
        ["40日收益差", value(group.spread, 100, " pp")],
        ["比值距MA242", value(group.distance, 100, "%")],
        ["RSI14", value(group.rsi)],
        ["最近事件", group.events[0] ? `${date(group.events[0].date)} · ${group.events[0].label}` : "近5日无新触发"]
      ]) {
        append(metrics, "dt", label);
        append(metrics, "dd", metric);
      }
    }
  }

  function renderRows() {
    const rows = get("overview-rows");
    const groups = visibleGroups();
    rows.replaceChildren();
    for (const group of groups) {
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
      const qualityCell = append(row, "td");
      const quality = append(qualityCell, "span", group.quality);
      quality.className = "overview-quality";
      quality.dataset.state = group.quality === "完整" ? "complete" : "warning";
      append(qualityCell, "span", date(group.data_date)).className = "overview-quality-date";
    }
    if (!rows.children.length) append(append(rows, "tr"), "td", "该筛选下无组合").colSpan = 8;
    renderMobileRows(groups);
  }

  async function load() {
    retry.classList.add("hidden");
    content.classList.add("hidden");
    meta.parentElement.dataset.state = "loading";
    meta.textContent = "正在读取已发布快照…";
    try {
      const response = await fetch("/api/rotation/overview", {cache: "no-cache"});
      if (!response.ok) throw new Error("HTTP " + response.status);
      overview = await response.json();
      const triggered = overview.groups.filter(group => group.events.some(event => event.date === overview.observation_date)).length;
      const issues = overview.groups.filter(group => group.quality !== "完整").length;
      get("overview-observation").textContent = date(overview.observation_date);
      get("overview-triggered").textContent = triggered + " 组";
      get("overview-triggered-copy").textContent = triggered ? `已发布收盘数据中有 ${triggered} 组新触发` : "当日无新触发；可查看近5日历史变化";
      get("overview-complete").textContent = `${overview.groups.length - issues} / ${overview.groups.length}`;
      get("overview-quality-copy").textContent = issues ? `${issues} 组指标缺失或日期落后，查看各组状态` : "全部组合数据完整";
      const qualityCard = document.querySelector(".overview-headline-card--quality");
      qualityCard.dataset.state = issues ? "warning" : "complete";
      const spread = overview.etf.spread;
      get("overview-spread").textContent = spread == null ? "—" : (spread > 0 ? "+" : "") + value(spread, 100, " pp");
      get("overview-spread-copy").textContent = `基准 ${date(overview.etf.base_date)} · ETF 截至 ${date(overview.etf.data_date)}`;
      document.querySelector(".overview-headline-card--spread").dataset.polarity = spread > 0 ? "positive" : spread < 0 ? "negative" : "neutral";
      get("overview-group-count").textContent = `（${overview.groups.length}组）`;
      meta.textContent = `已读取发布快照 · 指数观察日 ${date(overview.observation_date)} · ETF 数据日 ${date(overview.etf.data_date)}`;
      meta.parentElement.dataset.state = "ready";
      get("overview-snapshot").textContent = `快照 ${overview.snapshot_id} · 指标版本 ${overview.formula_version || "未记录"} · 事件规则 ${overview.rule_version || "未记录"}。指数策略数据按各组有效交易日计算；ETF 展示未复权收盘价格收益。`;
      get("etf-dates").textContent = "实际基准日 " + date(overview.etf.base_date) + " · 数据日期 " + date(overview.etf.data_date);
      const etf = get("overview-etf");
      etf.replaceChildren();
      const items = [...Object.values(overview.etf.returns), {name: "红利 / 成长初始各50%买入持有", value: overview.etf.portfolio}];
      for (const item of items) {
        const cell = append(etf, "div");
        append(cell, "dt", item.name);
        const amount = append(cell, "dd", value(item.value, 100, "%"));
        amount.className = item.value > 0 ? "positive" : item.value < 0 ? "negative" : "neutral";
      }
      renderEvents();
      renderRows();
      content.classList.remove("hidden");
    } catch (error) {
      meta.textContent = "信息总览加载失败，请重试（" + error.message + "）";
      meta.parentElement.dataset.state = "error";
      retry.classList.remove("hidden");
    }
  }

  retry.addEventListener("click", load);
  get("event-period").addEventListener("change", renderEvents);
  get("overview-filter").addEventListener("change", renderRows);
  load();
})();
