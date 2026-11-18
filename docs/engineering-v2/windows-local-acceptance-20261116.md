# Windows 本地数据治理验收 · 2026-11-16

## 结论

在 SQLite 一致性备份建立的隔离目录完成了真实 Provider 取数、候选行情核验、质量门禁、SQLite/JSON 发布、Manifest 校验、FastAPI 读取和浏览器展示。正式数据库及当前 Manifest、ETF/指数直读 JSON 的前后 SHA256 全部相同。首次闭环以隔离副本中暂时移除的四条**真实既有价格**作重放，不是模拟价格；这证明本地发布链路，但不等于 2026-11-12/13 的全部中证指数已经更新。

隔离发布版本：`20261116T074322-c42956c6`；后续手动 API 更新发布版本：`20261116T080415-9b97fadd`。发布版本、库内行情和 API 样本一致。修复重复刷新逻辑后，再次刷新返回 `UNCHANGED`，版本号与行情表、核验链接保持不变。

当前 26 条系列：正常 1、陈旧 7、取数失败 12、历史异常 4、证据未知 2。26 条的记录数与最新日期都同 SQLite 或文件吻合；`snapshot_database_consistency=MATCH`。因此本轮不能给出“全部数据已更新”的结论。

## 环境与数据保护

- 项目：`D:\我的坚果云\09-Codex\02-软件应用学习\etf-market-dashboard`；隔离目录：`D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\windows-v2-20261116`。
- 使用 `python -m scripts.backup_db --target <隔离目录>\etf_market.db` 创建 SQLite Backup API 一致性副本，副本 `PRAGMA integrity_check=ok`，44 张表；原始参考文件复制并在副本中重定向 306 条路径，SHA256 均校验通过。
- 隔离基线只移除 2026-11-13 的 3 条真实 ETF 收盘及 2026-11-11 的 1 条真实 H00300 点位，再由线上 Provider 重新取得；正式行情没有任何删除或覆盖。
- 正式文件摘要前后比对：data\index_prices.json=一致, data\current_manifest.json=一致, data\etf_prices.json=一致, data\etf_market.db=一致。见 [摘要前](../../../.scratch/windows-v2-20261116/source_hashes_before.json)、[最终复核](../../../.scratch/windows-v2-20261116/source_integrity_final.json)。

## 真实更新与发布闭环

| 环节 | 实测结果 | 证据 |
|---|---|---|
| 采集 | ETF 三条 11-13 收盘由 AkShare/Sina 备用接口返回，HTBR 独立同日收盘校核后放行；H00300 的 11-11 点位由 AkShare/CSI 返回。原始响应含采集时间、请求、上游及 SHA256。 | [发布逐条证据](../../../.scratch/windows-v2-20261116/publish-validation.json) |
| 校验 | 14 条最近参考请求 `checked=14`，`unavailable=0` 表示请求有可核验历史响应，不表示 11-12/13 全部已取得。新增 H00300 候选通过 5 条独立 CSI 官方散列证据的门禁。 | [首次核验日志](../../../.scratch/windows-v2-20261116/manual-verify-only.log) |
| 发布 | SQLite 恢复为 ETF 6,097、指数 46,552 条；Manifest、两个 Snapshot 文件的 SHA256 均有效，`_database_matches_release=True`。发布前后用不同任务核实。 | [发布结果](../../../.scratch/windows-v2-20261116/publish-validation.json) |
| API/页面 | `/api/live`、`/api/ready`、`/api/snapshot`、两个 Snapshot 文件、数据中心及轮动总览均返回 200，读取同一发布版本；桌面与移动端数据显示该版本。 | [API 结果](../../../.scratch/windows-v2-20261116/api-validation.json)、[浏览器结果](../../../.scratch/windows-v2-20261116/ui/acceptance/result.json) |
| 再次执行 | 初次发现无新价格仍生成新版本；代码修复后 CLI 返回 `publicationStatus=UNCHANGED`，版本留在 `20261116T080415-9b97fadd`。行情表摘要、Manifest 摘要、发布版本及 canonical 数均不变。同期 Wind 返回一条新的日经盘中行，原始观察增加 1 条；此后增加收盘门禁。 | [手动 API 记录](../../../.scratch/windows-v2-20261116/manual-api-repeat.json)、[前后计数](../../../.scratch/windows-v2-20261116/idempotence-final.json) |

采集成功、参考数值一致与允许发布分别记录。上游最新日期缺失时保留旧行情；CNI 已到 11-13，12 条中证指数仍止于 11-11。

## 26 条系列状态核对

以 CNI 480080/480081 同步返回的 2026-11-13 为内地市场最近参考交易日；H20915 保留独立市场日历。完整采集时间、影响看板、异常数量和覆盖率见 [26 条逐项机器报告](../../../.scratch/windows-v2-20261116/series-validation.json)。

| 系列 | 行数 | 最新有效日 | Provider / 上游 | 采集 | 数值/质量 | 来源证据 | 运行状态 |
|---|---:|---|---|---|---|---|---|
| index:480080 | 3366 | 20261113 | AkShare / CNI | RECORDED | ANOMALY | PARTIAL_REFERENCE | ANOMALY |
| index:480081 | 3366 | 20261113 | AkShare / CNI | RECORDED | ANOMALY | PARTIAL_REFERENCE | ANOMALY |
| index:H00821 | 3364 | 20261111 | AkShare / CSI | FAILED | PASS | ISSUER_HTTP_COVERAGE | FETCH_FAILED |
| index:H00300 | 3364 | 20261111 | AkShare / CSI | FAILED | ANOMALY | PARTIAL_REFERENCE | FETCH_FAILED |
| index:H00918 | 3364 | 20261111 | AkShare / CSI | FAILED | PASS | ISSUER_HTTP_COVERAGE | FETCH_FAILED |
| index:H00919 | 3364 | 20261111 | AkShare / CSI | FAILED | ANOMALY | PARTIAL_REFERENCE | FETCH_FAILED |
| index:932000CNY010 | 3126 | 20261111 | AkShare / CSI | FAILED | ANOMALY | PARTIAL_REFERENCE | FETCH_FAILED |
| index:H00811 | 3364 | 20261111 | AkShare / CSI | FAILED | ANOMALY | PARTIAL_REFERENCE | FETCH_FAILED |
| index:H00813 | 3364 | 20261111 | AkShare / CSI | FAILED | ANOMALY | PARTIAL_REFERENCE | FETCH_FAILED |
| index:H20180 | 3364 | 20261111 | AkShare / CSI | FAILED | ANOMALY | PARTIAL_REFERENCE | FETCH_FAILED |
| index:H20035 | 3364 | 20261111 | AkShare / CSI | FAILED | PASS | ISSUER_HTTP_COVERAGE | FETCH_FAILED |
| index:H00922 | 3364 | 20261111 | AkShare / CSI | FAILED | PASS | ISSUER_HTTP_COVERAGE | FETCH_FAILED |
| index:H20903 | 3364 | 20261111 | AkShare / CSI | FAILED | PASS | ISSUER_HTTP_COVERAGE | FETCH_FAILED |
| index:H20915 | 3054 | 20261111 | AkShare / CSI | FAILED | ANOMALY | PARTIAL_REFERENCE | FETCH_FAILED |
| etf:512530 | 1730 | 20261113 | AkShare / Sina | RECORDED | ANOMALY | PROVIDER_TABLE | ANOMALY |
| etf:562310 | 1010 | 20261113 | AkShare / Sina | RECORDED | UNKNOWN | PROVIDER_TABLE | UNKNOWN |
| etf:510330 | 3357 | 20261113 | AkShare / Sina | RECORDED | ANOMALY | PROVIDER_TABLE | ANOMALY |
| flow:159919.SZ | 680 | 2026-11-12 | akshare / SZSE | RECORDED | PASS | SOURCE_ID_LINKED | STALE |
| flow:510300.SH | 693 | 2026-11-12 | akshare / SSE | RECORDED | PASS | SOURCE_ID_LINKED | STALE |
| flow:510310.SH | 693 | 2026-11-12 | akshare / SSE | RECORDED | PASS | SOURCE_ID_LINKED | STALE |
| flow:510320.SH | 376 | 2026-11-12 | akshare / SSE | RECORDED | PASS | SOURCE_ID_LINKED | STALE |
| flow:510330.SH | 693 | 2026-11-12 | akshare / SSE | RECORDED | PASS | SOURCE_ID_LINKED | STALE |
| flow:510350.SH | 693 | 2026-11-12 | akshare / SSE | RECORDED | PASS | SOURCE_ID_LINKED | STALE |
| dividend:ETF:510880 | 20 | 2026-01-21 | sse:510880:2026-01-16 / 上海证券交易所 | RECORDED | PASS | OFFICIAL_VERIFIED | NORMAL |
| dividend:STOCK:600519 | 33 | 2026-06-26 | 未知 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| bond_value:hs300 | 4090 | 20261109 | AkShare, Wind MCP | LOCAL_FILE | STRUCTURE_PASS | LOCAL_DERIVED | STALE |

`FETCH_FAILED` 对应 12 条中证指数的 11-12 起最新区间未返回；`STALE` 包括 6 条资金流和股债估值。历史异常与参考取数失败分别计数，避免同一行被笼统归为正常。

## 14 条指数历史核验

| 指数 | 本地记录 | 参考覆盖 | 编制机构数值一致 | 供应商 0.01 点差异 | 缺参考 | 遗留状态 |
|---|---:|---:|---:|---:|---:|---|
| 480080 | 3366 | 3366 | 3366 | 0 | 0 | IDENTITY_UNCONFIRMED:3366 |
| 480081 | 3366 | 3366 | 3366 | 0 | 0 | IDENTITY_UNCONFIRMED:3366 |
| H00821 | 3364 | 3364 | 3364 | 0 | 0 | PASS |
| H00300 | 3364 | 3364 | 3364 | 1 | 0 | VENDOR_DISAGREEMENT:1 |
| H00918 | 3364 | 3364 | 3364 | 0 | 0 | PASS |
| H00919 | 3364 | 3364 | 7 | 27 | 0 | SOURCE_EVIDENCE_INCOMPLETE:3330, VENDOR_DISAGREEMENT:27 |
| 932000CNY010 | 3126 | 3126 | 7 | 6 | 0 | SOURCE_EVIDENCE_INCOMPLETE:3113, VENDOR_DISAGREEMENT:6 |
| H00811 | 3364 | 3364 | 7 | 24 | 0 | SOURCE_EVIDENCE_INCOMPLETE:3333, VENDOR_DISAGREEMENT:24 |
| H00813 | 3364 | 3364 | 3114 | 24 | 0 | SOURCE_EVIDENCE_INCOMPLETE:242, VENDOR_DISAGREEMENT:24 |
| H20180 | 3364 | 3364 | 3363 | 0 | 0 | INVALID_REFERENCE:1 |
| H20035 | 3364 | 3364 | 3364 | 0 | 0 | PASS |
| H00922 | 3364 | 3364 | 3364 | 0 | 0 | PASS |
| H20903 | 3364 | 3364 | 3364 | 0 | 0 | PASS |
| H20915 | 3054 | 2989 | 2989 | 12 | 65 | CALENDAR_REVIEW:38, NO_REFERENCE:65, VENDOR_DISAGREEMENT:12, CALENDAR_EXCEPTION:1 |

总计 46,552 条本地记录、46,487 条至少有一种参考、36,403 条编制机构数值一致；`PASS` 29,603 条。原始来源未知但编制机构参考数值已吻合 29,952 条，仍不得回填原始来源。明细见 [异常与 94 个日期](../../../.scratch/windows-v2-20261116/anomaly-validation.json)、[收敛总表](../../../.scratch/windows-v2-20261116/verification/convergence-summary.json)。

- 94 条供应商点位均比本地高 0.01 点，跨 2013–2026 年；其中 29 条编制机构直接响应与本地一致。其余差异仍是供应商精度或修订未判，不放宽 0.005 点容差。
- H20180 2013-06-28：本地推导修复值 4303.99，编制机构响应为 0.0；0 非有效点位，修复值未取得可用独立当日点位，状态 `INVALID_REFERENCE`，继续保留原值及待判。
- H20915 2026-11-07：本地周六值 12514.56，当前编制机构响应无该日参考，状态 `NO_REFERENCE`；未删除。2018-06-18：编制机构 6906.26 与本地一致，但与 A 股休市日重合且该指数采用独立日历，状态 `CALENDAR_EXCEPTION`，仍需发行人日历书面证据。另有 38 条 `CALENDAR_REVIEW`。
- 480080/480081：各 3,366 条编制机构数值吻合，计价货币身份仍 `CURRENCY_UNCONFIRMED`，不把数值一致等同身份验证。

## 最新参考来源与 403

11-12 至 11-13 再探：H00300、H00821 的 CSI `index-perf` 返回 HTTP 403、`text/html`，响应体仅留 SHA256；CNI 480080 同期返回 2 行。见 [脱敏探测结果](../../../.scratch/windows-v2-20261116/provider-probe-final.json)。前述线上集成测试只覆盖 2013 年和截至 2026-11-11 的历史窗口，不能证明当前中证尾部可获取。403 的确切权限或限流原因未获上游确认，不能据此伪造最近两日的匹配。

ETF 备用源是 AkShare/Sina，三个 ETF 的候选价经 HTBR 独立收盘校核后在隔离环境发布；其真实上游不是东方财富。日经 Wind MCP 在本次隔离测试可返回重叠区间，但通过中文名称查询的全收益口径仍标记 `WIND_MCP_NAME_LOOKUP_UNVERIFIED_TR`，不计入 14 条指数的权威全收益证明。

日经临时基准的 2026-11-16 响应曾在东京盘中给出午夜时间戳、但缺失成交额和成交量，且两次查询数值变化。已增加东京收盘时间与完整成交字段的写入门禁，以及读取时对盘中行的隔离。隔离库保留原始响应和该候选行供追溯；API 现只展示截至 2026-11-13 的有效日线，见 [读取门禁结果](../../../.scratch/windows-v2-20261116/nikkei-read-guard.json)。正式库未写入该测试行。

## Windows 定时、故障与恢复

- 手动 `scripts/run_daily_verified.ps1 -OverlapDays 7 -VerifyOnly` 检查 14 条、不触发发布；脚本增加 `-PythonExe` 以指定 Windows Python。临时任务计划程序首次因 PowerShell 把 pandas 的 stderr 警告当错误而失败；改用隔离包装器分别重定向 stdout/stderr，第二次 `LastTaskResult=0`，完成后已注销临时任务。见 [定时结果](../../../.scratch/windows-v2-20261116/scheduled-task-result-second.json)、[标准输出](../../../.scratch/windows-v2-20261116/scheduled-verify-stdout.log)。未安装永久系统任务。
- 固定样本覆盖数据源中断、Sina 未核验候选隔离、数值冲突、SQLite 事务回滚、JSON/Manifest 暂存失败、指针切换失败与恢复、Windows 文件占用重试；选出的 13 个故障测试全通过，并核实旧 Snapshot 指针仍可读。见 [故障测试明细](../../../.scratch/windows-v2-20261116/fault-validation.json)。
- 未通过门禁的候选不覆盖已发布价格；单一系列失败可通过逐条任务诊断展示，当前 12 条失败已显示具体起始日与 `SOURCE_TRAILING_UNAVAILABLE`。

## 测试命令与结果

```powershell
$env:ETF_DATA_DIR = 'D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\windows-v2-20261116'
D:\Anaconda3\python.exe -m scripts.backup_db --target (Join-Path $env:ETF_DATA_DIR 'etf_market.db')
D:\Anaconda3\python.exe -m scripts.daily_verified --verify-only --overlap-days 7 --through 20261113
D:\Anaconda3\python.exe -m scripts.update_data --require-reference-verification
& .\scripts\run_daily_verified.ps1 -OverlapDays 7 -VerifyOnly -PythonExe 'D:\Anaconda3\python.exe'
D:\Anaconda3\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8016
D:\Anaconda3\python.exe -m pytest -q
$env:RUN_INDEX_ONLINE = '1'
D:\Anaconda3\python.exe -m pytest tests/test_index_verification_online.py -q
$env:ETF_TEST_URL = 'http://127.0.0.1:8016'
D:\Anaconda3\python.exe tests/ui_live_smoke_v2.py
D:\Anaconda3\python.exe tests/ui_workbench_smoke.py
D:\Anaconda3\python.exe tests/ui_workbench_interactions.py
```

- 离线 pytest：451 通过、10 跳过（这 10 项是显式选择的在线测试），0 失败；[JUnit](../../../.scratch/windows-v2-20261116/offline-final.xml)。
- 真实 Provider 线上测试：10 通过、0 失败、0 跳过；仅覆盖既定较早窗口；[JUnit](../../../.scratch/windows-v2-20261116/online.xml)。
- Playwright：核心页面桌面/移动 16 组、工作台路由 32 组、交互操作和数据中心失败/重试固定样本均通过；复合图实测 3 条 line + 1 条 bar 在同一 ECharts 对象；[UI 验收 JSON](../../../.scratch/windows-v2-20261116/ui/acceptance/result.json)。

关键截图：[数据中心桌面](../../../.scratch/windows-v2-20261116/ui/acceptance/data-center-desktop.png)、[数据中心移动](../../../.scratch/windows-v2-20261116/ui/acceptance/data-center-mobile.png)、[红利成长复合图](../../../.scratch/windows-v2-20261116/ui/acceptance/dividend-growth-composite-desktop.png)、[三棱镜](../../../.scratch/windows-v2-20261116/ui/acceptance/prism-desktop.png)、[五年之锚](../../../.scratch/windows-v2-20261116/ui/live/live-anchor-1440.png)、[股息研究](../../../.scratch/windows-v2-20261116/ui/live/live-dividend-research-1440.png)、[资金流向](../../../.scratch/windows-v2-20261116/ui/live/live-fund-flow-1440.png)、[股债性价比](../../../.scratch/windows-v2-20261116/ui/live/live-bond-value-1440.png)。

## 未解决事项与下一步

1. 与 CSI 确认 `index-perf` 对 2026-11-12/13 的 HTTP 403 原因和授权方式，待真实官方响应可用后补做 12 条尾部逐日核验；保持旧 Snapshot 可用。
2. 向编制机构取得 480080/480081 计价货币、H20915 原生交易日历和 2026-11-07 官方解释；H20180 零值当日需独立非零正式点位或修订公告。
3. 94 个 0.01 点供应商差异保留日期清单及原始哈希，逐条确认第三位小数/修订来源；目前不改容差。
4. Windows 本地正式任务需由使用者选定触发时间和 Python 绝对路径后注册；本次只完成临时定时任务与手动运行验收。
5. pandas 对 numexpr/bottleneck 版本发出兼容警告；不影响本次结果，但 Windows 环境可在锁定依赖版本后消除。
6. Wind 日经临时基准仍需核实正式代码及收益口径；隔离库中盘中候选行保留为证据，目前由 API 隔离，后续东京收盘后应由有效完整日线替换。
