# V2 验收报告（2026-11-13）

环境：Windows，Python 3.9.13、Node 24.15.0、Chrome（本机安装）；WSL Linux，Python 3.11。Git HEAD `dd95f2105c0edf4d11bb7cdd4b5ad33e4a0a18d3`；工作树含用户原有未提交改动，本报告不代表提交版本。基线 388 passed；修改后 Windows `python -m pytest -q` **413 passed，退出码 0**，只有本机 pandas 对 numexpr/bottleneck 的两个可选依赖版本警告。`node --check web/app.js; node --check web/navigation.js; node --check web/data-center.js` 退出码 0。`git diff --check` 退出码 0（有 CRLF 转换提醒）。

WSL Linux 初次全量运行 **394 passed、3 failed、退出码 1**：三个 Wind MCP mock HTTP 测试的本机 `127.0.0.1` 请求被 WSL 代理转发，返回 502。单独设置 `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost` 后，这 5 项相关测试通过；最终以相同环境变量重跑全量 **413 passed、退出码 0**。这是本机测试环境代理问题，不是实际 Wind 服务已连接成功。

独立 API 冒烟：本机 Uvicorn `127.0.0.1:8765` 下 `/api/live`、`/api/ready`、`/api/snapshot`、`/api/data-center`、`/web/data-center.html` 均返回 200；数据中心列出 5 个数据集、当前快照 `20261111T214903-865e1e9e`。这只证明本机现有文件可读，不证明截至 11 月 12/13 日的行情已更新。

浏览器命令：设置 `PYTHONPATH=C:\Users\Yicen\AppData\Local\Temp\etf-playwright` 后运行 `python tests/ui_data_center_v2.py`，退出码 0。固定 API 夹具覆盖 ETF 已发布、指数失败、空集、API 出错后重试，1440px/390px 均无未处理 Page Error、无全局横向溢出，筛选正常。截图：`evidence/data-center-desktop.png`、`evidence/data-center-mobile.png`。本机 Playwright 是临时依赖；`requirements-ui.txt` 与 CI 安装步骤已加入，但 CI 尚未在线执行。

本地现有数据浏览器冒烟：`python tests/ui_live_smoke_v2.py`，退出码 0；8 个页面 × 1440/390px 共 16 场景，HTTP 200、有标题、无页面脚本异常和全局横向溢出。逐项 JSON 与截图存于 `evidence/live-smoke.json`、`evidence/live-*-*.png`。该测试使用本地真实数据快照，不是固定夹具，也不证明每个业务数值与交互正确。

| ID | 判定 | 实际证据与缺口 |
|---|---|
| T01 | PASS | Windows 与 WSL Linux 分隔符兼容测试均通过；CI 矩阵已加入但未在线运行 |
| T02 | PASS | `test_snapshot_portability` 拒绝 `..`、绝对/盘符/软链越界 |
| T03 | PASS | 损坏文件/哈希/ID 使 Reader 与 readiness 报错，数据中心显示 FAILED |
| T04 | PASS | `test_fallback_quarantine` 验证备源候选不能覆盖旧发布 |
| T05 | PASS | `test_source_policy` 验证重叠价格/收益、来源证据及冲突阻断 |
| T06 | PASS | `test_snapshot_portability` 验证历史未知来源不伪造 Raw 关联 |
| T07 | PASS | JSON/Manifest 写入故障、SQLite 回滚、指针切换失败与恢复、并发读一致性及 Windows 临时文件占用重试均有离线注入 |
| T08 | PASS | 双进程同窗口认领只产生一个 job；成功窗口重复触发复用旧 job；第二进程更新文件锁被拒绝，Windows/WSL 均通过 |
| T09 | PASS | 固定日历下休市不误报陈旧、旧日可标陈旧；港股人民币全收益指数保留本地交易日、上海时区截点明确；相关离线 39 项通过。生产日历未自动采集，缺失时为 UNKNOWN |
| T10 | PASS | 官方 PDF 现金分红、缺少完整分红覆盖时收益率保留 NULL、份额折算保持经济价值、大额份额跳变仅候选；相关离线 40 项通过 |
| T11 | PASS | `test_metrics` 手算 50:50 与 20 个百分点收益差；主图单图契约见原有 UI 测试 |
| T12 | PASS | `test_dividend_research_backtest` 初始建仓和手续费手算、T+1 约束 |
| T13 | PASS | 注入“采集成功但校验失败”和“校验成功但发布失败”；任务三列分别显示 FETCH_OK / VALIDATION_FAILED / NOT_ATTEMPTED 与 FETCH_OK / VERIFIED / FAILED，旧快照仍可读 |
| T14 | PASS | 固定日历下旧版仍 `PUBLISHED` 且标 `STALE`；浏览器业务页轻量状态显示“沿用旧版”，策略切换后更新关联数据集，跳转数据中心对应卡片 |
| T15 | PASS | 桌面/手机固定夹具覆盖筛选、空集、API 错误重试；数据库不可读时仍返回各数据集诊断；API 不返回凭证字段 |
| T16 | BLOCKED | Windows 生成 113 文件代码包；WSL 用此包执行 Linux 部署 dry-run，独立数据哈希未变、代码软链未切换；真实 Linux `--apply` 尚未在测试服务器执行 |
| T17 | PASS | 临时 SQLite WAL 备份→恢复完整性测试和只读清理预览通过 |
| T18 | FAIL | 16 个主要页面/视口本地冒烟通过；统一固定 API 夹具下的业务数值、日期切换、图例和交互仍未完整覆盖 |

以上 PASS 仅指离线结构/逻辑测试，不是独立外部行情事实核验。Wind、ETFirst、东方财富、真实 Linux 服务器、真实代理链路本阶段未连接验证。当前按完整 T01–T18 门槛计 **16/18 PASS**，另 1 BLOCKED、1 FAIL；总体 V2 尚未通过最终验收。
