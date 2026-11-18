# 在线故障诊断与重复更新稳定性验收（Windows 本地）

## 范围和结论

本轮仅修改代码、测试和隔离副本。正式 SQLite、Manifest、两份 JSON 未被本轮修改，也未启用定时任务。开始检查时正式指针已是 `20261117T144646-997729f0`，与上轮报告中的 `20261117T120325-13132053` 不同；本轮没有切换或回滚该指针。正式一致性备份位于 `D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\online-stability-20261117\baseline`。结束时正式三份快照文件与备份 SHA-256 相同；正式 SQLite 文件的物理 SHA-256 与备份不同，但全部业务表逐行摘要、行数和 `integrity_check=ok` 相同。详见 [正式数据保护核验](evidence/online-stability-20261117/formal-protection.json)。

**五个交易日人工更新观察：PASS，限人工监控。** 同数据重跑不刷新业务记录、Canonical 选源、Manifest 或 JSON；外部请求失败时旧快照仍可用；发布指针中断时数据中心显示 `MISMATCH`，恢复后显示 `MATCH`。本结论不授权无人值守更新，也不保证中证接口每天可访问。一次 ETF 采集失败会阻止整包 ETF 更新；已核验指数可通过现有 `--index-only` 受控路径独立发布。当前未实现所有系列的任意粒度部分发布。

## 原 18 项在线失败逐项归因

原始在线批次结果为 **6 通过、18 失败、0 跳过**。18 项失败均在实际调用 `https://www.csindex.com.cn/csindex-home/perf/index-perf` 时得到 HTTP 403，尚未进入数值断言。旧批次只保留测试摘要，**没有逐请求 UTC 时间、响应体哈希或响应头**；不能倒填这些证据。该接口对 HTTP 状态错误不重试，故每项有效重试 **0 次、请求 1 次**。旧批次的精确执行时刻无法恢复，仅知为 2026-11-17 正式发布后。以下“外部”是请求失败直接原因；“代码”表示该测试本身是否发现计算程序缺陷。两类测试将 Provider 可用性作为断言，因此短时 403 会令集成测试失败；这不应改成跳过或伪造通过。

**逐项分类规则：**下表 18 项均为“外部来源故障：是；本项证明程序数值计算错误：否；测试设计问题：在线可用性断言容易随接口波动失败，但断言本身合理；环境问题：原日志不足以判定本机代理、权限、限流或服务端策略；是否需改代码：需补可追溯诊断，不需放宽核验或改成跳过”。H00922 的额外重查缺陷是另一条重复更新路径，不能倒推为第 10 项 HTTP 403 的直接原因。旧批次故障后的业务状态依正式发布报告：快照版本、行情行数及已发布 API 均保持不变；这不是新行情采集成功。

| # | 测试用例 / 目标 | 实际请求参数 `indexCode; startDate; endDate` | 返回 | 归类 / 是否改代码 |
|---:|---|---|---|---|
| 1 | `test_issuer_returns_target_close_with_raw_response[H00821]` 最新点位及原始响应 | H00821; 20261116; 20261117 | HTTP 403 | 外部；测试自身无计算错误；补诊断 |
| 2 | `test_issuer_returns_target_close_with_raw_response[H00300]` 同上 | H00300; 20261116; 20261117 | HTTP 403 | 外部；同上 |
| 3 | `test_issuer_returns_target_close_with_raw_response[H00918]` 同上 | H00918; 20261116; 20261117 | HTTP 403 | 外部；同上 |
| 4 | `test_issuer_returns_target_close_with_raw_response[H00919]` 同上 | H00919; 20261116; 20261117 | HTTP 403 | 外部；同上 |
| 5 | `test_issuer_returns_target_close_with_raw_response[932000CNY010]` 同上 | 932000CNY010; 20261116; 20261117 | HTTP 403 | 外部；同上 |
| 6 | `test_issuer_returns_target_close_with_raw_response[H00811]` 同上 | H00811; 20261116; 20261117 | HTTP 403 | 外部；同上 |
| 7 | `test_issuer_returns_target_close_with_raw_response[H00813]` 同上 | H00813; 20261116; 20261117 | HTTP 403 | 外部；同上 |
| 8 | `test_issuer_returns_target_close_with_raw_response[H20180]` 同上 | H20180; 20261116; 20261117 | HTTP 403 | 外部；同上 |
| 9 | `test_issuer_returns_target_close_with_raw_response[H20035]` 同上 | H20035; 20261116; 20261117 | HTTP 403 | 外部；同上 |
| 10 | `test_issuer_returns_target_close_with_raw_response[H00922]` 同上 | H00922; 20261116; 20261117 | HTTP 403 | 外部；另有独立 H00922 重查缺陷已修 |
| 11 | `test_issuer_returns_target_close_with_raw_response[H20903]` 同上 | H20903; 20261116; 20261117 | HTTP 403 | 外部；测试自身无计算错误 |
| 12 | `test_issuer_returns_target_close_with_raw_response[H20915]` 同上 | H20915; 20261116; 20261117 | HTTP 403 | 外部；同上 |
| 13 | `test_live_csi_reference_matches_saved_market_without_mutation[20130603-20130701-H00821]` 旧区间逐日点位与正式行情 | H00821; 20130603; 20130702 | HTTP 403 | 外部；数值比较未执行 |
| 14 | `test_live_csi_reference_matches_saved_market_without_mutation[20130603-20130701-H00918]` 同上 | H00918; 20130603; 20130702 | HTTP 403 | 外部；同上 |
| 15 | `test_live_csi_reference_matches_saved_market_without_mutation[20130603-20130701-H00300]` 同上 | H00300; 20130603; 20130702 | HTTP 403 | 外部；同上 |
| 16 | `test_live_csi_reference_matches_saved_market_without_mutation[20261008-20261111-H00821]` 近期区间逐日点位与正式行情 | H00821; 20261008; 20261112 | HTTP 403 | 外部；同上 |
| 17 | `test_live_csi_reference_matches_saved_market_without_mutation[20261008-20261111-H00918]` 同上 | H00918; 20261008; 20261112 | HTTP 403 | 外部；同上 |
| 18 | `test_live_csi_reference_matches_saved_market_without_mutation[20261008-20261111-H00300]` 同上 | H00300; 20261008; 20261112 | HTTP 403 | 外部；同上 |

2026-11-17 07:25:22 UTC 对 H00300 / 20261116 的独立请求返回 **HTTP 200**，响应为 JSON，响应体 SHA-256 `cb87496ef45376788a7cefedc5afddfb8ecbb913c9b01bbe770bcb254b4bd29d`，见 [探针记录](evidence/online-stability-20261117/provider-probe.json)。修复后在线专项两次均为 **24 通过、0 失败、0 跳过**，见 [首次](evidence/online-stability-20261117/online-test.txt)及[末次](evidence/online-stability-20261117/online-final-test.txt)。因此原 403 不是持续不可访问；旧批次没有响应头，尚不能在权限、限流或服务端防护之间进一步定因。AkShare 重复更新的 `JSONDecodeError` 是另一条路径，原异常未保留 HTTP 状态，不能认定为 403。

## 程序缺陷与修复

| 位置 | 原问题 | 修改后 |
|---|---|---|
| `scripts/storage.py` | 相同 ETF 重叠点位被再次 `UPSERT`，18 条原记录的 `updated_at` 无意义刷新；Canonical 选源也可能换成新采集批次 | 相同业务值不更新行情、来源、更新时间或选源；不同值在同一事务记 `market_price_revisions`，保留修订前后来源与原始记录 ID；SQLite 失败全部回滚 |
| `scripts/update_data.py` | H00922 的已归档官方点位因 `source!='AkShare'` 被误列为历史补查，可能在重复更新中触发不必要的失败；旧库无 `raw_observations` 表会报错 | 只有官方原始观察、归档文件和 SHA-256 均匹配时才跳过补查；缺失文件或未有证据仍复查；旧库安全退回保守查询；只为变更行情新增 Canonical 行 |
| `scripts/index_verification.py`、`scripts/daily_verified.py` | HTTP 错误缺少完整、安全的诊断；代码正确但官方名称表明价格指数时仍可能被事实资料链接误判为全收益 | 保存接口、状态、响应哈希、请求时间、参数、请求次数；日报只保留脱敏字段；明确的价格指数名称判 `IDENTITY_CONFLICT` |
| `scripts/data_center.py`、`web/data-center.js`、`web/data-center.html` | 预备发布后 SQLite 已变而指针未切换时仍显示 `MATCH`；指数聚合卡把三棱镜指标日期误作最新已发布点位日；每日 403 只在日报、不在序列采集状态 | 实际比较 SQLite 与快照价格事实；分别显示发布点位日和指标日；最新失败显示 HTTP 状态，同时保留已发布日期与质量状态，后续成功可清除失败表现；静态脚本版本已刷新 |

## 隔离更新、故障和恢复

固定样本演练使用旧正式快照的隔离副本，12 条 CSI 20261116 参考批次来自另一个封存的真实响应副本，并逐一复算原始 JSON 哈希；ETFirst 备用与 ETF 行情在演练中是固定样本，**这部分不冒充在线验收**。详细逐阶段的业务行 SHA-256、Manifest/JSON SHA-256、任务尝试、来源批次、9 组策略日期见 [六阶段证据](evidence/online-stability-20261117/isolated-cycle.json)。

| 阶段 | 结果 | ETF 行 / 指数行 | 指针与数据中心 |
|---|---|---:|---|
| 基线 | 旧有效快照 | 6097 / 46576 | `20261116T194338-32527f07` / `MATCH` |
| 首次发布 | 12 条指数、3 条 ETF 新增；H00821 主源 403 后用同口径备用且经原有参考门禁 | 6100 / 46588 | `20261117T160811-ad57b6dc` / `MATCH` |
| 完全相同重跑 | `UNCHANGED`；市场、Canonical、Manifest、JSON 哈希及行数完全不变 | 6100 / 46588 | 同一版本 / `MATCH` |
| ETF 超时、H00918 参考 403 | 整包更新不发布；其他 13 条指数的独立日报继续检查；数据中心 H00918 `FAILED`/HTTP 403、已发布日仍为 20261116 | 6100 / 46588 | 同一版本 / `MATCH` |
| 发布指针中断 | 事务内记录一条真实修订样本；旧 Manifest/JSON 仍可读，SQLite 有 `prepared`；数据中心明确报 `MISMATCH` | 6100 / 46588 | 旧版本仍可读取 |
| 故障恢复重跑 | 恢复预备发布后返回 `UNCHANGED`；修订证据仅一条；重新核验日报后 H00918 显示成功 | 6100 / 46588 | `20261117T160848-90dab3e7` / `MATCH` |

首次发布、相同重跑、来源故障、指针中断四阶段的 Manifest SHA-256 均为 `6496a959addd205c6f595ae1fee07b44715cab2a0f92fadf06c635878b454e84`；ETF JSON 均为 `98969749310df10faafa58b7f12797f3f0973ef311ee55b60cb5eba317c23ff5`；指数 JSON 均为 `6542da78eb4352978f37d214613301332285f5fa67df010f66b8d7b954df6ab9`。首次发布与同值重跑的 SQLite 业务行摘要亦逐表一致。中断阶段仅预备 SQLite 修订发生变化，故明确标为不一致；恢复时切换到新版本。

独立的 [ETF 故障期间指数发布演练](evidence/online-stability-20261117/index-only-outage.json) 从旧快照开始，模拟 ETF 接口不可用，执行受门禁保护的 `index_only`：ETF 6097 行不变，指数由 46576 增至 46588 行，9 组策略日期均 `MATCH`，新版本发布成功。指数源失败、所有源不可用时则保留原快照；不把未核验备用值写入正式行情。

离线专项覆盖 HTTP 403、429、超时、空响应、错误指数代码、价格指数冒充全收益、点位冲突、同口径备用、无可用源、修订、事务回滚、同值重复执行和数据中心状态分离。修复前上轮离线为 **474 通过、24 跳过**；修复后全套为 **490 通过、24 跳过、0 失败**，见 [pytest 日志](evidence/online-stability-20261117/offline-final-test.txt) 与 [JUnit XML](evidence/online-stability-20261117/offline-final-junit.xml)。真实 Provider 结果单列，不把跳过计作通过。

隔离数据中心浏览器检查在真实隔离 API 上运行，桌面 1440px 和移动 390px 均为 HTTP 200、无脚本错误；H00918 同时显示“失败：ReferenceHTTPError (HTTP 403)”、当前质量 `PASS`、已发布日 20261116 和历史异常，9 组策略日期仍可查看。见 [UI 结果](evidence/online-stability-20261117/data-center-403-ui.json)、[桌面截图](evidence/online-stability-20261117/data-center-403-1440.png)、[移动截图](evidence/online-stability-20261117/data-center-403-390.png)。

## 运行命令与观察要求

以下命令中的 `ETF_DATA_DIR` 必须指向隔离副本，不应换成正式 `data` 目录做故障注入：

```powershell
$env:ETF_DATA_DIR='D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\online-stability-20261117\work'
D:\Anaconda3\envs\QuaTra\python.exe -m pytest -q
$env:RUN_INDEX_ONLINE='1'
$env:INDEX_ONLINE_TARGET='20261116'
$env:INDEX_REFERENCE_RETRIES='0'
D:\Anaconda3\envs\QuaTra\python.exe -m pytest tests\test_index_latest_online.py tests\test_index_verification_online.py -q
```

最终五阶段演练实际使用独立旧快照副本 `stage-work6`，设置 `ETF_TEST_ARCHIVE_DIR=...\.scratch\online-stability-20261117\work` 后运行 `python tests\isolated_update_cycle.py`；指数独立发布演练使用另一份 `stage-work5`，额外设置 `ETF_TEST_INDEX_ONLY=1`。演练会写入指定副本，重复执行前须重新从一致性备份复制到新的隔离目录。浏览器验收以 `stage-work3` 启动 `uvicorn server:app --host 127.0.0.1 --port 8768`，再运行 `python tests\ui_online_stability.py`；验收后已停止本地服务。

连续 5 个交易日由人工观察每次 Provider 状态、质量门禁、最新交易日、发布时间、当前 Manifest 与 SQLite/JSON 一致性及 9 组策略实际日期；遇 403、429 或超时按故障记录并沿用旧版，不做强制发布。若发现快照与 SQLite `MISMATCH`，停止后续发布，先恢复预备发布或按既有回滚方案处理。无人值守仍保持关闭。
