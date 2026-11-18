# 数据中心

最近更新任务的每一行提供“查看详情”，进入 `/web/job-detail.html?job=<任务编号>`，通过只读 `/api/jobs/{job_id}/details` 展示逐数据集的发布状态、实际来源、最近日期、增补数量和脱敏原因。新任务将结果以 `(job_id,dataset_id)` 为主键写入 `jobs.db`，重试不会累积重复行。旧任务没有逐数据集诊断时，页面仅依据已保存的任务阶段指出可确认的范围：`PUBLISHED_WITH_PARTIAL_FAILURE` 表示 ETF 与指数行情已发布、日经临时基准未完成，但无法区分旧任务究竟是凭证缺失还是上游错误；旧失败任务不能精确定位证券代码。详情页明确显示这一证据限制。

入口 `/web/data-center.html` 是一级导航；只读 API 为 `GET /api/data-center`，`schema_version=1`。返回 `summary`、`datasets`、`recent_issues`、`recent_jobs`、当前快照和空间大小。受影响页面映射在 `scripts/data_center.py:REGISTRY`，由底层数据集汇总而非按策略复制面板。

业务页由共用导航注入轻量“截至日期 / 当前状态 / 查看详情”行；当已发布版本落后于有覆盖范围的交易日历时显示“沿用旧版”。策略切换会更新此行，不复制数据中心的完整诊断表。

状态分三列：`fetch_status`、`validation_status`、`publication_status`。`UNKNOWN` 是尚无充分证据，`STRUCTURE_PASS` 是内部结构校验，`PUBLISHED` 是当前指针文件验证通过，`FAILED` 表示文件/清单不可读；`LOCAL_DB`/`LOCAL_FILE` 不等同于版本化发布。若新浪候选被隔离，可同时看到采集候选阻断、仍沿用旧版发布的情况。可选 `ETF_DATA_DIR/market_calendar.json` 需要按序列出的 `YYYYMMDD` 交易日和 `covered_through`；只有覆盖当前截止日才计算预期交易日与 `STALE`，否则一律 `UNKNOWN`，避免把休市误判成失败。此文件目前没有自动采集流程。任务表记录 QUEUED/RUNNING/SUCCEEDED/FAILED/PARTIAL，以及采集、校验、发布三阶段结果；仍未逐证券细分。

固定浏览器演示：测试夹具中 ETF 发布 `fixture-v2`、指数验证失败；页面在桌面和 390px 手机端分别显示两种状态，失败筛选只留下指数卡片。测试用模拟 API，不是市场事实。截图在 `evidence/data-center-desktop.png` 和 `evidence/data-center-mobile.png`。

已知缺口：生产环境交易日历自动更新、跨市场日历、逐数据集抓取行数、上次成功/失败时间、异常 Raw→Canonical 下钻、最近两个可恢复快照尚未完整展示。非 ETF/指数的数据集仅有本地存储摘要，不能据此判断发布和外部核验成功。
