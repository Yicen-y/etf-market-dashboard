(function () {
  if (window.echarts && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    window.echarts.registerPreprocessor((option) => { option.animation = false; });
  }
  const strategies = [
    ["dividend-growth", "300红利 / 300成长（ETF）"],
    ["prism", "成长100R / 价值100R"],
    ["dividend-hs300", "300红利 / 沪深300"],
    ["growth-value-300", "300成长 / 300价值"],
    ["csi2000-hs300", "中证2000 / 沪深300"],
    ["nonferrous-chemical", "中证有色 / 中证化工"],
    ["banks-exbank-financial", "中证银行 / 非银金融"],
    ["dividend-growth-300", "300红利 / 300成长（指数）"],
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
    return strategies.map(([id, label]) => {
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
    const rotationOpen = activeSection === "rotation" || (saved.rotationItems ?? false);
    const dividendOpen = activeSection === "dividend" || (saved.dividendItems ?? false);
    root.classList.add("strategy-sidebar");
    root.setAttribute("aria-label", "ETF看板导航");
    root.innerHTML = `
      <button class="mobile-nav-toggle" type="button" aria-expanded="false" aria-controls="dashboard-nav-content"><span>投资分析看板</span><span aria-hidden="true">菜单</span></button>
      <div id="dashboard-nav-content" class="dashboard-nav-content">
      <div class="sidebar-brand">${chartIcon}<span>投资分析看板</span></div>
      <a class="sidebar-standalone${activeSection === "overview" ? " active" : ""}" href="./overview.html"${current(activeSection === "overview")}>轮动总览</a>
      <div class="sidebar-divider"></div>
      <section class="sidebar-section">
        <button class="sidebar-section-toggle" type="button" data-sidebar-toggle="rotation-items" aria-expanded="${rotationOpen}">
          <span class="sidebar-chevron" aria-hidden="true">${rotationOpen ? "⌄" : "›"}</span><span>轮动看板</span>
        </button>
        <div id="rotation-items" class="sidebar-section-items"${rotationOpen ? "" : " hidden"}>${strategyMarkup(activeSection, activeStrategy)}</div>
      </section>
      <div class="sidebar-divider"></div>
      <section class="sidebar-section">
        <button class="sidebar-section-toggle" type="button" data-sidebar-toggle="dividend-items" aria-expanded="${dividendOpen}">
          <span class="sidebar-chevron" aria-hidden="true">${dividendOpen ? "⌄" : "›"}</span><span>红利看板</span>
        </button>
        <div id="dividend-items" class="sidebar-section-items"${dividendOpen ? "" : " hidden"}>
          <a class="strategy-item dividend-entry${activeSection === "dividend" && activeDividend === "ETF" ? " active" : ""}" data-type="ETF" href="./dividend.html?type=ETF"${current(activeSection === "dividend" && activeDividend === "ETF")}>ETF股息率</a>
          <a class="strategy-item dividend-entry${activeSection === "dividend" && activeDividend === "STOCK" ? " active" : ""}" data-type="STOCK" href="./dividend.html?type=STOCK"${current(activeSection === "dividend" && activeDividend === "STOCK")}>股票股息率</a>
        </div>
      </section>
      <div class="sidebar-divider"></div>
      <a class="sidebar-standalone${activeSection === "anchor" ? " active" : ""}" href="./anchor.html"${current(activeSection === "anchor")}>五年之锚</a>
      <a class="sidebar-standalone${activeSection === "research" ? " active" : ""}" href="./dividend-research.html"${current(activeSection === "research")}>红利研究</a>
      <a class="sidebar-standalone${activeSection === "bond-value" ? " active" : ""}" href="./bond-value.html"${current(activeSection === "bond-value")}>股债性价比</a>
      <a class="sidebar-standalone${activeSection === "settings" ? " active" : ""}" href="./settings.html"${current(activeSection === "settings")}>设置</a>
      <div class="sidebar-divider"></div>
      <a class="sidebar-standalone fund-flow-link${activeSection === "fund-flow" ? " active" : ""}" href="./fund-flow.html"${current(activeSection === "fund-flow")}>${flowIcon}<span>沪深300 ETF资金流向</span></a>
      <p class="sidebar-note">选择看板后，基准日期、状态和图表会随模块切换。</p>
      </div>`;
  }

  const mainContent = document.querySelector(".dashboard-content");
  if (mainContent) {
    mainContent.id ||= "dashboard-main";
    mainContent.setAttribute("tabindex", "-1");
    if (!document.querySelector(".skip-link")) document.querySelector("main")?.insertAdjacentHTML("beforebegin", '<a class="skip-link" href="#dashboard-main">跳转到主要内容</a>');
  }
  document.querySelectorAll("[data-dashboard-navigation]").forEach(renderNavigation);
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
