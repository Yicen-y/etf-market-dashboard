(function () {
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
  ];
  const storageKey = "etf-dashboard-navigation";

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
    return strategies.map(([id, label]) => activeSection === "rotation"
      ? `<button class="strategy-item${id === activeStrategy ? " active" : ""}" type="button" data-strategy="${id}">${label}</button>`
      : `<a class="strategy-item${id === activeStrategy ? " active" : ""}" data-strategy-link="${id}" href="./index.html?strategy=${id}">${label}</a>`
    ).join("");
  }

  function renderNavigation(root) {
    const activeSection = root.dataset.activeSection || "rotation";
    const params = new URLSearchParams(location.search);
    const activeStrategy = root.dataset.activeStrategy || params.get("strategy") || "dividend-growth";
    const activeDividend = root.dataset.activeDividend || (params.get("type") === "STOCK" ? "STOCK" : "ETF");
    const saved = loadState();
    const rotationOpen = saved.rotationItems ?? activeSection === "rotation";
    const dividendOpen = saved.dividendItems ?? activeSection === "dividend";
    root.classList.add("strategy-sidebar");
    root.setAttribute("aria-label", "ETF看板导航");
    root.innerHTML = `
      <div class="sidebar-brand"><span class="sidebar-brand-icon" aria-hidden="true">⌁</span><span>投资分析看板</span></div>
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
          <a class="strategy-item dividend-entry${activeSection === "dividend" && activeDividend === "ETF" ? " active" : ""}" data-type="ETF" href="./dividend.html?type=ETF">ETF股息率</a>
          <a class="strategy-item dividend-entry${activeSection === "dividend" && activeDividend === "STOCK" ? " active" : ""}" data-type="STOCK" href="./dividend.html?type=STOCK">股票股息率</a>
        </div>
      </section>
      <div class="sidebar-divider"></div>
      <a class="sidebar-standalone fund-flow-link${activeSection === "fund-flow" ? " active" : ""}" href="./fund-flow.html"><span class="sidebar-nav-icon" aria-hidden="true">♜</span><span>沪深300 ETF资金流向</span></a>
      <p class="sidebar-note">选择看板后，基准日期、状态和图表会随模块切换。</p>`;
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
})();
