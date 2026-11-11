# 本地数据源凭证设置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地 ETF 看板中增加统一设置页，让使用者安全保存、删除和测试 Wind MCP、华泰柏瑞 ETF、南方 ETFirst 三类凭证，并让现有采集链路读取这些凭证。

**Architecture:** 新增独立的凭证服务模块，使用 Windows Credential Manager 保存三类 Key；FastAPI 只暴露配置状态和操作结果，不返回明文。前端新增设置页和导航入口，调用后端接口；数据源适配器通过统一凭证读取接口接入现有 Wind、HTBR 和 ETFirst 调用，不改动指标计算和数据库业务结构。

**Tech Stack:** Python 3、FastAPI、Pydantic、keyring、HTML/CSS/JavaScript、现有导航与 UI 组件、pytest。

## Global Constraints

- 凭证只保存到 Windows Credential Manager，不写入 SQLite、JSON、`localStorage`、日志或 Git。
- API 响应、页面、异常和测试输出不得包含明文 Key。
- provider 仅允许 `wind`、`htbr`、`etfirst`。
- 不新增登录、用户系统、云部署或远程凭证存储。
- 沿用现有 FastAPI、HTML/JavaScript、CSS 和导航体系。
- 上游测试使用最小只读请求、超时和服务端防重复提交。
- Windows Credential Manager 不可用时拒绝降级为明文文件。
- 不修改 ETF 轮动、资金流向、五年之锚和红利研究的计算逻辑。

---

## 文件地图

| 文件 | 责任 |
|---|---|
| `scripts/credential_settings.py` | provider 白名单、凭证库读写、状态脱敏、测试适配器 |
| `scripts/wind_credentials.py` | 保留现有 Wind CLI，并改为复用统一 Wind 凭证读取/写入能力 |
| `scripts/dividend/provider_yields.py` | 读取 HTBR 凭证时使用统一凭证模块 |
| `scripts/fetch_data.py` | ETFirst 调用读取统一凭证，兼容显式参数 |
| `server.py` | 注册设置 API、保证异常不泄露凭证 |
| `web/settings.html` | 设置页结构 |
| `web/settings.js` | 状态加载、保存、删除、测试和可见性切换 |
| `web/settings.css` | 设置页卡片、状态和响应式样式 |
| `web/navigation.js` | 增加设置入口 |
| `tests/test_credential_settings.py` | 凭证服务与安全边界测试 |
| `tests/test_settings_api.py` | FastAPI 设置接口测试 |
| `tests/test_settings_ui.py` | 设置页和导航静态行为测试 |

## Task 1: 凭证服务与安全边界

**Files:**
- Create: `scripts/credential_settings.py`
- Modify: `scripts/wind_credentials.py`
- Test: `tests/test_credential_settings.py`

**Interfaces:**
- Produces `CredentialProvider`, `CredentialStatus`, `get_credential`, `set_credential`, `delete_credential`, `list_credential_status`, `test_credential`.
- `list_credential_status() -> list[dict]` only returns provider, configured, masked.

- [ ] Step 1: Write failing tests for provider whitelist, keyring mapping, masking, delete idempotence, Wind normalization, and plaintext exclusion.
- [ ] Step 2: Run `pytest tests/test_credential_settings.py -q`; expected initial import/implementation failures.
- [ ] Step 3: Implement a keyring-backed service using service name `etf-market-dashboard` and accounts `WIND_MCP_AUTH`, `HTBR_ETF_API_KEY`, `ETFIRST_API_KEY`. Reject empty values and non-Windows keyring backends.
- [ ] Step 4: Refactor `scripts/wind_credentials.py` to preserve CLI behavior while delegating Wind storage/read to the new service; keep environment variables as an explicit compatibility override.
- [ ] Step 5: Run `pytest tests/test_credential_settings.py -q`; expected all tests pass and no test output contains a sample secret.
- [ ] Step 6: Commit with `git add scripts/credential_settings.py scripts/wind_credentials.py tests/test_credential_settings.py && git commit -m "feat: add local credential settings service"`.

## Task 2: Data-source adapters and connection tests

**Files:**
- Modify: `scripts/fetch_data.py`
- Modify: `scripts/dividend/provider_yields.py`
- Modify: `scripts/credential_settings.py`
- Test: `tests/test_credential_settings.py`
- Test: `tests/test_update_data.py`

**Interfaces:**
- Consumes `get_credential("etfirst")` and `get_credential("htbr")`.
- Produces provider test functions that perform only bounded read-only checks and return a redacted status dictionary.

- [ ] Step 1: Add tests that monkeypatch provider commands/clients and assert ETFirst and HTBR receive the configured value without writing it to logs or return payloads.
- [ ] Step 2: Add tests for provider test failures, timeout handling, and preservation of an existing credential.
- [ ] Step 3: Update ETFirst invocation to resolve the credential from the unified service when no explicit `api_key` argument is provided; keep explicit arguments for CLI/test compatibility.
- [ ] Step 4: Update HTBR invocation/configuration to resolve `HTBR_ETF_API_KEY` from the unified service at call time without changing existing parsing or persistence logic.
- [ ] Step 5: Implement `test_credential(provider)` with minimal read-only calls: Wind initialization/list-tools, ETFirst auth/status check, HTBR configuration/status check. All exceptions become redacted messages.
- [ ] Step 6: Run `pytest tests/test_credential_settings.py tests/test_update_data.py -q`.
- [ ] Step 7: Commit with `git add scripts/fetch_data.py scripts/dividend/provider_yields.py scripts/credential_settings.py tests/test_credential_settings.py tests/test_update_data.py && git commit -m "feat: connect data providers to local credentials"`.

## Task 3: FastAPI settings endpoints

**Files:**
- Modify: `server.py`
- Create: `tests/test_settings_api.py`

**Interfaces:**
- `GET /api/settings/credentials`
- `PUT /api/settings/credentials/{provider}` with JSON `{ "key": "..." }`
- `DELETE /api/settings/credentials/{provider}`
- `POST /api/settings/credentials/{provider}/test`

- [ ] Step 1: Write API tests for status-only responses, save/delete/test behavior, unknown provider 404, empty key 400, upstream test failure, and no secret in serialized responses.
- [ ] Step 2: Run `pytest tests/test_settings_api.py -q`; expected failures before routes exist.
- [ ] Step 3: Add a small Pydantic request model and register four routes in `server.py` or a focused router imported by it.
- [ ] Step 4: Return status 200 for successful operations, 400 for invalid input, 404 for unknown provider, 502 for provider test failure; never return stored values.
- [ ] Step 5: Run `pytest tests/test_settings_api.py -q` and then `pytest tests/test_server.py tests/test_wind_credentials.py -q`.
- [ ] Step 6: Commit with `git add server.py tests/test_settings_api.py && git commit -m "feat: expose credential settings API"`.

## Task 4: Settings page and navigation

**Files:**
- Create: `web/settings.html`
- Create: `web/settings.js`
- Create: `web/settings.css`
- Modify: `web/navigation.js`
- Test: `tests/test_settings_ui.py`

**Interfaces:**
- Page calls the four `/api/settings/credentials` endpoints.
- Navigation renders a `设置` link with `aria-current="page"` only when settings is active.

- [ ] Step 1: Write static UI tests for three provider cards, password inputs, labels, save/delete/test controls, status area, no hard-coded key values, and navigation link.
- [ ] Step 2: Implement `settings.html` using the existing navigation root and shared theme/UI CSS.
- [ ] Step 3: Implement `settings.js` to load statuses, prevent duplicate submissions, toggle password visibility, show redacted success/error messages, and never place keys in localStorage or URL parameters.
- [ ] Step 4: Implement responsive `settings.css` for desktop, 1024px, 768px and narrow mobile layouts; keep keyboard focus visible and use `aria-live` for operation status.
- [ ] Step 5: Add the settings link in `navigation.js` without altering active state logic for existing pages.
- [ ] Step 6: Run `pytest tests/test_settings_ui.py tests/test_dashboard_navigation.py -q` and `node --check web/settings.js`.
- [ ] Step 7: Commit with `git add web/settings.html web/settings.js web/settings.css web/navigation.js tests/test_settings_ui.py && git commit -m "feat: add credential settings page"`.

## Task 5: Integration, security regression, and local verification

**Files:**
- Modify: `README.md`
- Modify: `.gitignore` only if needed to guard local credential/debug artifacts
- Test: existing regression suite

- [ ] Step 1: Add local setup instructions: install `keyring`, open `/web/settings.html`, save each provider, test connection, and remove credentials.
- [ ] Step 2: Run `rg -n "WIND_MCP_AUTH|HTBR_ETF_API_KEY|ETFIRST_API_KEY|api_key" web scripts tests` and inspect that no page or test fixture contains a real credential.
- [ ] Step 3: Run targeted tests:
  `pytest tests/test_credential_settings.py tests/test_settings_api.py tests/test_settings_ui.py tests/test_wind_credentials.py tests/test_update_data.py -q`
- [ ] Step 4: Run the full suite with `pytest -q` and record failures without claiming unrelated pre-existing failures are fixed.
- [ ] Step 5: Start locally with `python -m uvicorn server:app --host 127.0.0.1 --port 8000`, open `http://127.0.0.1:8000/web/settings.html`, and verify status-only loading, save, delete, and test error handling using test doubles or unavailable-provider conditions.
- [ ] Step 6: Commit documentation and final fixes with `git add README.md .gitignore && git commit -m "docs: document local credential settings"`.

## Verification Checklist

- [ ] All three providers can be saved and deleted from the settings page.
- [ ] Restarting the local server preserves configured status through Windows Credential Manager.
- [ ] No API response, browser storage, static file, log, test output, or Git diff contains a real Key.
- [ ] Existing data refresh and dashboard regression tests remain intact.
- [ ] Provider test failures are explicit and do not erase an existing credential.
