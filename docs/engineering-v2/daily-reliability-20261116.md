# 最新行情获取与数据中心验收（Windows，2026-11-16）

隔离目录：`D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\daily-reliability-20261116`。正式快照 `20261116T194338-32527f07`；隔离发布快照 `20261116T204519-8fcb0c89`。
正式 Manifest、ETF JSON、指数 JSON 前后 SHA-256 一致：`{'manifest': True, 'etf': True, 'index': True}`。隔离库 `PRAGMA integrity_check=ok`，Manifest 文件哈希校验 `True`，数据库与快照 `MATCH`。

## 最新行情指标

目标日 `20261116`：预期 14 条；参考取得 14 条；质量门禁通过 12 条；发布 12 条；沿用旧版 2 条；最新参考缺失 0 条。ETF 三条均到 `20261116`，实际最近上游为 Sina，备用价经华泰柏瑞同日校核。

## 14 条指数来源与发布状态

| 指数 | 编制机构直连 | AkShare（同上游） | ETFirst | 华泰柏瑞/Gildata | 已发布截止 | 身份 / 质量 |
|---|---|---|---|---|---|---|
| 480080 成长100R | 20261116 | 20261116 | 空响应 | 20261113 | 20261113 | UNCONFIRMED / UNVERIFIED |
| 480081 价值100R | 20261116 | 20261116 | 空响应 | 20261113 | 20261113 | UNCONFIRMED / UNVERIFIED |
| H00821 沪深300红利 | 20261116 | 20261116 | 空响应 | 20261116 | 20261116 | CONFIRMED / PASS |
| H00300 沪深300 | 20261116 | 20261116 | 空响应 | 20261116 | 20261116 | CONFIRMED / PASS |
| H00918 沪深300成长 | 20261116 | 20261116 | 空响应 | 20261116 | 20261116 | CONFIRMED / PASS |
| H00919 沪深300价值 | 20261116 | 20261116 | 空响应 | 20261116 | 20261116 | CONFIRMED / PASS |
| 932000CNY010 中证2000 | 20261116 | 20261116 | 空响应 | 20261116 | 20261116 | CONFIRMED / PASS |
| H00811 中证细分有色 | 20261116 | 20261116 | 空响应 | 20261116 | 20261116 | CONFIRMED / PASS |
| H00813 中证细分化工 | 20261116 | 20261116 | 空响应 | 20261116 | 20261116 | CONFIRMED / PASS |
| H20180 中证银行 | 20261116 | 20261116 | 空响应 | 20261116 | 20261116 | CONFIRMED / PASS |
| H20035 沪深300非银金融 | 20261116 | 20261116 | 空响应 | 20261116 | 20261116 | CONFIRMED / PASS |
| H00922 中证红利 | 20261116 | 20261116 | 空响应 | 20261116 | 20261116 | CONFIRMED / PASS |
| H20903 中证A股 | 20261116 | 20261116 | 空响应 | 20261116 | 20261116 | CONFIRMED / PASS |
| H20915 港股通高股息投资人民币全收益 | 20261116 | 20261116 | 空响应 | 20261116 | 20261116 | CONFIRMED / PASS |

直连与 AkShare 使用同一编制机构上游，不算两份独立参考。华泰柏瑞接口的实际行情上游为 `gildata-jydb`，本轮仅作旁证；ETFirst 14 条近期请求均为空响应，其底层上游未披露。Wind 本周额度已耗尽，未将其列为可用实时源。两条国证指数的编制机构日行情响应未给出计价货币，虽然 11 月 16 日数值可取得，身份门禁仍保留旧版。

## HTTP 403 与故障处理

归档中有 76 次 `CSI index-perf` HTTP 403，最后一次 `2026-11-15T13:33:55.488939+00:00`。11 月 16 日直连和 AkShare 对全部 14 条取得目标日响应；本轮未复现 403。现有证据只能确认具体环节和恢复，不能把此前拒绝确定为权限、限流或网络单一原因。失败响应仅保存状态、接口名、响应哈希和时间，无凭据。

## 数据中心与策略版本

26 条系列维度统计：`{'acquisition_status': {'SUCCEEDED': 24, 'NOT_RUN': 2}, 'freshness_status': {'STALE': 2, 'CURRENT': 15, 'UNKNOWN': 9}, 'current_quality_status': {'UNVERIFIED': 3, 'PASS': 23}, 'release_status': {'USING_PREVIOUS': 2, 'PUBLISHED': 15, 'NOT_APPLICABLE': 9}}`。历史异常计数独立于当前质量。三棱镜国证双指数有效日 `20261113`；其余 8 组依赖策略逐组记录输入日期，见证据 JSON 的 `strategy_inputs`。FastAPI `/api/snapshot` 和 `/api/rotation/overview` 读取同一版本；三棱镜与沪深300红利策略 UI 分别显示 11 月 13 日与 16 日。

| 系列 | 获取 | 新鲜度 | 当前质量 | 发布 | 截止日期 | 历史质量 |
|---|---|---|---|---|---|---|
| 480080 | SUCCEEDED | STALE | UNVERIFIED | USING_PREVIOUS | 20261113 | ANOMALY |
| 480081 | SUCCEEDED | STALE | UNVERIFIED | USING_PREVIOUS | 20261113 | ANOMALY |
| H00821 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | PASS |
| H00300 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | ANOMALY |
| H00918 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | PASS |
| H00919 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | ANOMALY |
| 932000CNY010 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | ANOMALY |
| H00811 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | ANOMALY |
| H00813 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | ANOMALY |
| H20180 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | ANOMALY |
| H20035 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | PASS |
| H00922 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | PASS |
| H20903 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | PASS |
| H20915 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | ANOMALY |
| 512530 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | ANOMALY |
| 562310 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | UNKNOWN |
| 510330 | SUCCEEDED | CURRENT | PASS | PUBLISHED | 20261116 | ANOMALY |
| 159919.SZ | SUCCEEDED | UNKNOWN | PASS | NOT_APPLICABLE | 2026-11-13 | PASS |
| 510300.SH | SUCCEEDED | UNKNOWN | PASS | NOT_APPLICABLE | 2026-11-13 | PASS |
| 510310.SH | SUCCEEDED | UNKNOWN | PASS | NOT_APPLICABLE | 2026-11-13 | PASS |
| 510320.SH | SUCCEEDED | UNKNOWN | PASS | NOT_APPLICABLE | 2026-11-13 | PASS |
| 510330.SH | SUCCEEDED | UNKNOWN | PASS | NOT_APPLICABLE | 2026-11-13 | PASS |
| 510350.SH | SUCCEEDED | UNKNOWN | PASS | NOT_APPLICABLE | 2026-11-13 | PASS |
| ETF:510880 | NOT_RUN | UNKNOWN | PASS | NOT_APPLICABLE | 2026-01-21 | PASS |
| STOCK:600519 | NOT_RUN | UNKNOWN | UNVERIFIED | NOT_APPLICABLE | 2026-06-26 | UNKNOWN |
| hs300 | SUCCEEDED | UNKNOWN | PASS | NOT_APPLICABLE | 20261109 | STRUCTURE_PASS |

## 历史异常仍保留

一分差异 94 条，其中编制机构与本地数值一致 29 条；不调整 0.005 点容差。H20180 2013-06-28 官方响应零值，推导值未取得独立当日非零正式点位；H20915 2018-06-18 为日历例外；2026-11-07 周末记录即使出现数值相同的官方响应仍标记 `CALENDAR_REVIEW`；2026-11-14 的周末候选仅保留原始采集证据，不写正式行情。

## 测试与安全边界

离线 `python -m pytest -q`：464 passed、24 skipped（在线用例另行执行）；在线重点历史区间 10 passed，在线 14 条目标日 14 passed。固定故障恢复专项 27 passed；数据中心固定样本桌面/移动端通过；真实隔离页面 16 个页面/视口组合通过，策略图表日期与快照检查通过。重复每日运行返回 `UNCHANGED` 且快照指针不变。

正式行情表和三份正式快照文件未作为首次验收写入目标。一次核验投影重建命令在正式目录执行，刷新了派生的 `index_converged_status` 与报告；未改写 `index_prices`、`etf_prices` 或正式 Manifest/JSON。

## Windows 本地运行命令

在工程目录 PowerShell 中执行。先指定隔离数据目录；移除 `--verify-only` 才会按门禁尝试发布到该目录。

```powershell
$env:ETF_DATA_DIR = 'D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\daily-reliability-20261116'
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.daily_verified --through 20261116 --overlap-days 7 --verify-only
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.daily_verified --through 20261116 --overlap-days 7
D:\Anaconda3\envs\QuaTra\python.exe -m pytest -q
$env:RUN_INDEX_ONLINE = '1'; $env:INDEX_ONLINE_TARGET = '20261116'
D:\Anaconda3\envs\QuaTra\python.exe -m pytest -q tests/test_index_latest_online.py
```

## 结论与后续

Windows 本地可运行带质量门禁的部分发布：12 条中证指数和 3 条 ETF 已在隔离副本更新到 11 月 16 日；两条国证指数仍需编制机构计价货币证据。正式数据尚未切换，当前正式快照保持 11 月 13 日。建议将 `scripts.daily_verified` 配入现有 Windows 任务计划程序前先固定运行时间，并持续监测官方接口 403、ETFirst 空响应与 ETF 主源延迟。

## 证据文件

- `evidence/latest-reliability-20261116.json`：14 条来源、26 条系列、异常和哈希。
- `evidence/data-center-desktop.png`：修改前页面；`evidence/data-center-status-after-summary-20261116.png` 与 `evidence/data-center-status-after-series-20261116.png`：修改后页面。
- `evidence/latest-strategy-prism.png`、`evidence/latest-strategy-dividend-hs300.png`：策略日期和版本。
- `D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\daily-reliability-20261116\verification\latest-provider-probe\summary.json`：ETFirst、AkShare 逐条探测及原始响应哈希。
- `D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\daily-reliability-20261116\verification\htbr`：授权华泰柏瑞原始响应哈希与请求参数。
