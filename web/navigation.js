(function () {
  const STATUS_LABELS = {current:"最新有效",stale:"沿用旧版",review:"待核验",error:"失败",loading:"读取中",success:"更新完成"};
  function renderStatus(target, {state="review", summary="", detail="", href="/web/data-center.html", linkLabel="查看数据中心"} = {}) {
    const normalized = STATUS_LABELS[state] ? state : "review";
    target.replaceChildren();
    target.classList.add("status-compact");
    target.dataset.state = normalized;
    target.setAttribute("role", normalized === "error" ? "alert" : "status");
    target.setAttribute("aria-busy", String(normalized === "loading"));
    const badge = document.createElement("strong"); badge.className = "status-badge"; badge.textContent = STATUS_LABELS[normalized];
    const copy = document.createElement("span"); copy.className = "status-copy"; copy.textContent = summary;
    target.append(badge, copy);
    if (detail && detail !== summary) {
      const more = document.createElement("details"); more.className = "status-detail"; more.open = normalized === "error";
      const toggle = document.createElement("summary"); toggle.textContent = "原因与口径";
      const explanation = document.createElement("p"); explanation.textContent = detail;
      more.append(toggle, explanation); target.append(more);
    }
    if (href) { const link = document.createElement("a"); link.href = href; link.textContent = linkLabel; target.append(link); }
    return target;
  }
  window.DashboardStatus = {render:renderStatus};
  if (window.echarts && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    window.echarts.registerPreprocessor((option) => { option.animation = false; });
  }
  const strategies = [
    ["dividend-growth", "300红利 / 300成长（累计收益率）"],
    ["prism", "成长100R / 价值100R"],
    ["dividend-hs300", "300红利 / 沪深300"],
    ["growth-value-300", "300成长 / 300价值"],
    ["csi2000-hs300", "中证2000 / 沪深300"],
    ["nonferrous-chemical", "中证有色 / 中证化工"],
    ["banks-exbank-financial", "中证银行 / 非银金融"],
    ["dividend-growth-300", "300红利 / 300成长"],
    ["dividend-a-share", "中证红利 / 中证A股"],
    ["dividend-a-hk", "中证红利 / 港股通高股息"],
  ];
  const storageKey = "etf-dashboard-navigation";
  const icon = (path) => `<svg class="sidebar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  const chartIcon = icon('<path d="M3 18h18M5 15l4-5 4 3 6-7"/>');
  const flowIcon = icon('<path d="M4 7h16M4 17h16M8 4l-4 3 4 3M16 14l4 3-4 3"/>');
  const current = selected => selected ? ' aria-current="page"' : '';

  function loadState() {
    try { return JSON.parse(localStorage.getItem(storageKey) || "{}"); }
    catch (_) { return {}; }
  }

  function saveState(id, expanded) {
    const state = loadState();
    state[id] = expanded;
    localStorage.setItem(storageKey, JSON.stringify(state));
  }

  function strategyMarkup(activeSection, activeStrategy) {
    return strategies.filter(([id]) => id !== "dividend-growth").map(([id, label]) => {
      const activeClass = activeSection === "rotation" && id === activeStrategy ? " active" : "";
      return activeSection === "rotation"
        ? `<button class="strategy-item${activeClass}" type="button" data-strategy="${id}"${current(Boolean(activeClass))}>${label}</button>`
        : `<a class="strategy-item" data-strategy-link="${id}" href="./index.html?strategy=${id}">${label}</a>`;
    }).join("");
  }

  function renderNavigation(root) {
    const activeSection = root.dataset.activeSection || "rotation";
    const params = new URLSearchParams(location.search);
    const activeStrategy = root.dataset.activeStrategy || params.get("strategy") || "dividend-growth";
    const activeDividend = root.dataset.activeDividend || (params.get("type") === "STOCK" ? "STOCK" : "ETF");
    const saved = loadState();
    const rotationOpen = activeSection === "rotation" || activeSection === "industry-rotation" || (saved.rotationItems ?? false);
    const dividendOpen = ["dividend", "research", "bond-value"].includes(activeSection) || (saved.dividendItems ?? false);
    root.classList.add("strategy-sidebar");
    root.setAttribute("aria-label", "ETF看板导航");
    root.innerHTML = `
      <button class="mobile-nav-toggle" type="button" aria-expanded="false" aria-controls="dashboard-nav-content"><span>投资分析看板</span><span aria-hidden="true">菜单</span></button>
      <nav id="dashboard-nav-content" class="dashboard-nav-content" aria-label="看板模块">
      <div class="sidebar-brand">${chartIcon}<span><small class="sidebar-kicker">A股 ETF</small><strong>投资分析看板</strong></span></div>
      <p class="sidebar-group-label">总览与数据</p>
      <a class="sidebar-standalone${activeSection === "overview" ? " active" : ""}" href="./overview.html"${current(activeSection === "overview")}>信息总览</a>
      <a class="sidebar-standalone${activeSection === "data-center" ? " active" : ""}" href="./data-center.html"${current(activeSection === "data-center")}>数据中心</a>
      <div class="sidebar-divider"></div>
      <p class="sidebar-group-label">策略看板</p>
      ${activeSection === "rotation" ? `<button class="strategy-item sidebar-feature${activeStrategy === "dividend-growth" ? " active" : ""}" type="button" data-strategy="dividend-growth"${current(activeStrategy === "dividend-growth")}>300红利 / 300成长（累计收益率）</button>` : `<a class="strategy-item sidebar-feature" href="./index.html?strategy=dividend-growth">300红利 / 300成长（累计收益率）</a>`}
      <section class="sidebar-section">
        <button class="sidebar-section-toggle" type="button" data-sidebar-toggle="rotation-items" aria-expanded="${rotationOpen}">
          <span class="sidebar-chevron" aria-hidden="true">${rotationOpen ? "⌄" : "›"}</span><span>三棱镜策略</span>
        </button>
        <div id="rotation-items" class="sidebar-section-items"${rotationOpen ? "" : " hidden"}>${strategyMarkup(activeSection, activeStrategy)}<a class="strategy-item${activeSection === "industry-rotation" ? " active" : ""}" href="./industry-rotation.html"${current(activeSection === "industry-rotation")}>行业轮动</a></div>
      </section>
      <a class="sidebar-standalone${activeSection === "anchor" ? " active" : ""}" href="./anchor.html"${current(activeSection === "anchor")}>五年之锚</a>
      <a class="sidebar-standalone fund-flow-link${activeSection === "fund-flow" ? " active" : ""}" href="./fund-flow.html"${current(activeSection === "fund-flow")}>${flowIcon}<span>沪深300 ETF资金流向</span></a>
      <div class="sidebar-divider"></div>
      <p class="sidebar-group-label">红利与研究</p>
      <section class="sidebar-section">
        <button class="sidebar-section-toggle" type="button" data-sidebar-toggle="dividend-items" aria-expanded="${dividendOpen}">
          <span class="sidebar-chevron" aria-hidden="true">${dividendOpen ? "⌄" : "›"}</span><span>股息率监测</span>
        </button>
        <div id="dividend-items" class="sidebar-section-items"${dividendOpen ? "" : " hidden"}>
          <a class="strategy-item dividend-entry${activeSection === "dividend" && activeDividend === "ETF" ? " active" : ""}" data-type="ETF" href="./dividend.html?type=ETF"${current(activeSection === "dividend" && activeDividend === "ETF")}>ETF股息率</a>
          <a class="strategy-item dividend-entry${activeSection === "dividend" && activeDividend === "STOCK" ? " active" : ""}" data-type="STOCK" href="./dividend.html?type=STOCK"${current(activeSection === "dividend" && activeDividend === "STOCK")}>股票股息率</a>
          <a class="strategy-item${activeSection === "research" ? " active" : ""}" href="./dividend-research.html"${current(activeSection === "research")}>红利研究</a>
          <a class="strategy-item${activeSection === "bond-value" ? " active" : ""}" href="./bond-value.html"${current(activeSection === "bond-value")}>股债性价比</a>
        </div>
      </section>
      <div class="sidebar-divider"></div>
      <a class="sidebar-standalone${activeSection === "settings" ? " active" : ""}" href="./settings.html"${current(activeSection === "settings")}>设置</a>
      </nav>`;
  }

  const mainContent = document.querySelector(".dashboard-content");
  if (mainContent) {
    mainContent.id ||= "dashboard-main";
    mainContent.setAttribute("tabindex", "-1");
    if (!document.querySelector(".skip-link")) document.querySelector("main")?.insertAdjacentHTML("beforebegin", '<a class="skip-link" href="#dashboard-main">跳转到主要内容</a>');
  }
  document.querySelectorAll("[data-dashboard-navigation]").forEach(renderNavigation);
  const topbar = document.createElement("header");
  topbar.className = "app-topbar";
  topbar.innerHTML = `<a class="app-topbar-brand" href="./overview.html">A股 ETF 投资分析平台</a><span class="app-topbar-divider" aria-hidden="true"></span><span class="app-topbar-description">ETF · 轮动 · 红利 · 三棱镜 · 资金流向 · 股息率</span><a class="app-topbar-action" href="./data-center.html">数据中心</a>`;
  document.body.prepend(topbar);
  const section = document.querySelector("[data-dashboard-navigation]")?.dataset.activeSection;
  const dependencies = {
    rotation: ["etf_prices"],
    overview: ["etf_prices", "index_prices"], dividend: ["dividends"],
    "fund-flow": ["fund_flow"], anchor: ["index_prices"],
    research: ["index_prices", "dividends"], "bond-value": ["index_prices", "bond_value"]
  };
  // Pages with a live, source-specific status render it themselves; keep one status strip.
  if (mainContent && dependencies[section] && !mainContent.querySelector('#data-status, #status')) {
    const summary = document.createElement("div");summary.className="data-summary";summary.setAttribute("role","status");summary.textContent="正在核对数据状态…";
    const heading = mainContent.querySelector(".page-hero");
    if (heading) heading.insertAdjacentElement("afterend",summary);else mainContent.prepend(summary);
    const loadSummary=()=>fetch("/api/data-center").then(response=>{if(!response.ok)throw Error("unavailable");return response.json()}).then(data=>{
      summary.replaceChildren();
      const currentStrategy=new URLSearchParams(location.search).get("strategy")||"dividend-growth";
      const ids=section==="rotation"?[currentStrategy==="dividend-growth"?"etf_prices":"index_prices"]:dependencies[section];
      for(const id of ids){
        const item=(data.datasets||[]).find(row=>row.id===id);if(!item)continue;
        const span=document.createElement("span");span.className="data-summary-item";
        const state=item.using_previous_release||item.freshness_status==="STALE"?"stale":item.publication_status==="FAILED"||item.validation_status==="FAILED"?"error":item.freshness_status==="CURRENT"&&item.validation_status==="VERIFIED"?"current":"review";
        span.dataset.state=state;
        const badge=document.createElement("strong");badge.className="status-badge";badge.textContent=STATUS_LABELS[state];
        const name=document.createElement("span");name.textContent=`${item.name} · 截至 ${item.latest_trade_date||"未知"}`;
        const link=document.createElement("a");link.href=`/web/data-center.html#dataset-${encodeURIComponent(id)}`;link.textContent="详情";
        span.append(badge,name,link);summary.append(span);
      }
      if(!summary.children.length)renderStatus(summary,{state:"review",summary:"数据状态尚未登记"});
    }).catch(()=>renderStatus(summary,{state:"error",summary:"数据状态暂不可读"}));
    loadSummary();window.addEventListener("dashboard:strategy-changed",loadSummary);
    if(section==="rotation")document.querySelectorAll("button[data-strategy]").forEach(button=>button.addEventListener("click",()=>setTimeout(loadSummary,0)));
  }
  document.querySelectorAll("[data-sidebar-toggle]").forEach(toggle => {
    toggle.addEventListener("click", () => {
      const target = document.getElementById(toggle.dataset.sidebarToggle);
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!expanded));
      toggle.querySelector(".sidebar-chevron").textContent = expanded ? "›" : "⌄";
      target.hidden = expanded;
      saveState(toggle.dataset.sidebarToggle === "rotation-items" ? "rotationItems" : "dividendItems", !expanded);
    });
  });
  document.querySelectorAll(".mobile-nav-toggle").forEach(toggle => {
    toggle.addEventListener("click", () => {
      const root = toggle.closest("[data-dashboard-navigation]");
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!expanded));
      root.classList.toggle("mobile-nav-open", !expanded);
    });
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    document.querySelectorAll("[data-dashboard-navigation].mobile-nav-open").forEach(root => {
      root.classList.remove("mobile-nav-open");
      const toggle = root.querySelector(".mobile-nav-toggle");
      toggle?.setAttribute("aria-expanded", "false");
      toggle?.focus();
    });
  });
  document.querySelectorAll("[data-dashboard-navigation] .strategy-item").forEach(item => {
    item.addEventListener("click", () => {
      const root = item.closest("[data-dashboard-navigation]");
      if (item.matches("button[data-strategy]")) root.querySelectorAll("button[data-strategy]").forEach(button => {
        if (button === item) button.setAttribute("aria-current", "page");
        else button.removeAttribute("aria-current");
      });
      const toggle = root.querySelector(".mobile-nav-toggle");
      toggle?.setAttribute("aria-expanded", "false");
      root.classList.remove("mobile-nav-open");
    });
  });
})();
