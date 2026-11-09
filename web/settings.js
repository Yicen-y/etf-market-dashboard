(function () {
  const providers = ["wind_mcp", "htbr_etf", "etfirst"];
  const statusMessages = { wind_mcp: "Wind MCP", htbr_etf: "华泰柏瑞 ETF", etfirst: "南方 ETFirst" };
  const operationStatus = document.getElementById("settings-operation-status");

  function setOperation(message, state = "") {
    operationStatus.textContent = message;
    operationStatus.dataset.state = state;
  }

  async function request(url, options = {}) {
    let response;
    try {
      response = await fetch(url, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
    } catch (_) {
      throw new Error("本地服务不可用，请确认后端正在运行");
    }
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* use a safe generic error below */ }
    if (!response.ok) throw new Error("操作未完成，请检查本地服务状态");
    return payload;
  }

  function card(provider) { return document.querySelector(`[data-provider="${provider}"]`); }
  function setBusy(provider, busy) {
    const root = card(provider);
    root.dataset.busy = String(busy);
    root.querySelectorAll("button").forEach(button => { button.disabled = busy; });
    root.querySelector(".credential-input").disabled = busy;
  }

  function renderStatus(item) {
    const root = card(item.provider);
    if (!root) return;
    const output = root.querySelector(`[data-status="${item.provider}"]`);
    output.dataset.state = item.configured ? "configured" : "";
    output.textContent = item.configured ? `已配置（${item.masked || "已保存"}）` : "尚未配置";
  }

  async function loadStatuses() {
    try {
      const payload = await request("/api/settings/credentials");
      (payload.credentials || []).forEach(renderStatus);
    } catch (_) {
      providers.forEach(provider => {
        const output = card(provider).querySelector(`[data-status="${provider}"]`);
        output.dataset.state = "error";
        output.textContent = "状态读取失败";
      });
      setOperation("无法读取凭证状态，请确认本地服务正在运行。", "error");
    }
  }

  async function save(provider) {
    const input = card(provider).querySelector(".credential-input");
    if (!input.value.trim()) { setOperation(`请输入${statusMessages[provider]}凭证后再保存。`, "error"); input.focus(); return; }
    setBusy(provider, true);
    try {
      await request(`/api/settings/credentials/${provider}`, { method: "PUT", body: JSON.stringify({ key: input.value }) });
      input.value = "";
      setOperation(`${statusMessages[provider]}凭证已保存。`, "success");
      await loadStatuses();
    } catch (error) { setOperation(error.message, "error"); }
    finally { setBusy(provider, false); }
  }

  async function remove(provider) {
    setBusy(provider, true);
    try {
      await request(`/api/settings/credentials/${provider}`, { method: "DELETE" });
      setOperation(`${statusMessages[provider]}凭证已删除。`, "success");
      await loadStatuses();
    } catch (error) { setOperation(error.message, "error"); }
    finally { setBusy(provider, false); }
  }

  async function test(provider) {
    setBusy(provider, true);
    try {
      await request(`/api/settings/credentials/${provider}/test`, { method: "POST" });
      setOperation(`${statusMessages[provider]}连接成功。`, "success");
    } catch (error) { setOperation(`${statusMessages[provider]}连接测试未通过，请检查本地配置或服务状态。`, "error"); }
    finally { setBusy(provider, false); }
  }

  document.querySelectorAll("[data-toggle-credential]").forEach(button => button.addEventListener("click", () => {
    const input = card(button.dataset.toggleCredential).querySelector(".credential-input");
    const visible = input.type === "text";
    input.type = visible ? "password" : "text";
    button.textContent = visible ? "显示" : "隐藏";
    button.setAttribute("aria-pressed", String(!visible));
  }));
  document.querySelectorAll("[data-save-credential]").forEach(button => button.addEventListener("click", () => save(button.dataset.saveCredential)));
  document.querySelectorAll("[data-delete-credential]").forEach(button => button.addEventListener("click", () => remove(button.dataset.deleteCredential)));
  document.querySelectorAll("[data-test-credential]").forEach(button => button.addEventListener("click", () => test(button.dataset.testCredential)));
  loadStatuses();
})();
