# 2026-11-18 手动更新后指数仍停在 17 日

## 现场证据与根因

- 原快照 `20261118T202021-92d1008a`：3 只 ETF 最新日期均为 2026-11-18，14 条指数最新日期均为 2026-11-17。原任务 `dbbd6ae95f9944099224e4783f3e2974` 记为 `SUCCEEDED/PUBLISHED`，虽其 `index_prices.latest_date` 明确是 17 日，页面只显示“更新任务已发布版本”。
- 原手动按钮走 `/api/jobs/update` → `server._run_update_job` → `update_dataset`，未先执行现成的 `scripts.daily_verified.run_daily` 参考核验。18 日指数候选的原始响应已归档，但 14 条都记录过 `REFERENCE_GATE_NO_REFERENCE`，因此未进入正式指数行情。ETF 正常发布使 Manifest 版本变新，并不意味着指数日期也变新。
- `scripts.jobs.claim_job` 原先在同一 `update_window` 复用已成功任务。当天再次点击按钮只返回旧任务 ID，不发起重新采集。该行为会阻碍上游稍后补齐后的同日重试。
- 在隔离副本执行现有每日核验后，14 条官方参考均取得；13 条指数可通过现有门禁至 18 日。**成长100R（480080）仍不能放行**：官方路线已有 18 日记录，但 AkShare/CNI 同日路线仅返回到 17 日，`collect_cni_route_approvals` 对 18 日报告 `NO_TARGET_MATCH`，门禁为 `REFERENCE_GATE_IDENTITY_UNCONFIRMED`。价值100R（480081）已有 18 日路线批准。三棱镜必须保留两者共同有效的 17 日，不得用单边 18 日点位补齐或绕过放行规则。

## 定点修复

1. 手动任务先运行现有 `run_daily(..., publish=False)`，再以相同截止日调用原发布器；没有修改任何指数门禁、金融公式或快照发布机制。
2. 手动点击仅复用进行中的任务，不再复用当天的已完成任务；上游同日补齐后可以再次点击重试。
3. 指数落后 ETF 或已确认的参考交易日时，任务改报 `PARTIAL`。480080 的路线未齐备时，任务详情记为 `CNI_ROUTE_PENDING`，指数数据集显示实际日期。页面分别显示 ETF 与指数截至日及警告状态。
4. 已更新 `app.js`、任务详情脚本的资源版本，避免浏览器继续使用旧提示。

相关修改：`server.py`、`scripts/jobs.py`、`web/app.js`、`web/index.html`、`web/job-detail.js`、`web/job-detail.html`；新增隔离验证脚本 `tests/isolated_manual_refresh.py`、浏览器回归 `tests/ui_manual_refresh_feedback.py`，扩充 `tests/test_jobs_v2.py` 和 `tests/test_job_detail.py`。

## 实际执行结果

- 修改后用临时数据库与快照运行两次受门禁更新，均确认 480080 的 18 日缺少同日路线批准；未将该点位强行写入正式行情。
- 本机服务已重启加载新代码，并执行一次真实手动更新。任务 `c7da30609e6e4b409aeb4133c8956d38` 正确结束为 `PARTIAL/PUBLISHED_WITH_PARTIAL_FAILURE`；新快照 `20261118T204528-597adcfc` 中 ETF、480081、H00300、H20903 等已通过门禁的数据到 18 日，480080 仍为 17 日；三棱镜 API 的共同最新日期仍为 17 日。逐数据集结果在 `.scratch/manual-refresh-20261118/live-job-result.json`。
- Headless Chrome 实测任务详情和三棱镜均可加载，无 JS 异常。模拟 ETF=18 日、指数=17 日的浏览器测试显示警告并注明成长100R 路线证据不足。
- 全量 pytest：509 passed、24 skipped（在线数据源测试按原有 opt-in 条件跳过）。`node --check` 和 `git diff --check` 通过。

## 后续条件与回滚

只有 AkShare/CNI 的 480080 同日路线提供 18 日记录，且原有身份、数值和日历门禁全部通过后，重新点击“刷新全部数据”才能把三棱镜推进到 18 日。即使当日已运行过，修复后的按钮也会重新创建任务。重新打开或刷新浏览器页面以加载新版 JS。

执行真实更新前的 SQLite backup、Manifest 和 jobs.db 保存在 `.scratch/manual-refresh-20261118/before-live-update/`；旧版版本化快照仍保留。若需回滚，应先停止本机服务，核对目标版本后使用项目已有快照回滚流程恢复 Manifest，并按需要恢复相应数据库备份；不要在服务运行中直接覆盖 SQLite 文件。
