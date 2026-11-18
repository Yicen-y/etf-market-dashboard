# Windows 正式运行前验收（2026-11-17）

正式快照 `20261116T194338-32527f07`；隔离快照 `20261116T212333-7262a956`。一致性备份及可回滚包：`D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\release-ready-20261116\rollback-package`。
正式 Manifest/JSON 哈希不变：`True`；正式全部 SQLite 表逻辑摘要不变：`True`；正式市场行情表摘要不变：`True`。一致性备份数据库文件的字节哈希可因 SQLite 页布局与正式文件不同，故按全部逻辑表复核。隔离 SQLite 完整性 `ok`；数据库与快照 `MATCH`；API 三端点均返回相同版本。

## 国证身份结论

官方事实资料分别列出 480080、480081 的 R 版本，收益口径可确认；官方编制方案与 2024 年修订公告支持名称、基日及现行适用期。已取到的官方资料及日行情响应均未明确两条 R 序列的点位计价货币。身份门禁继续保持 `IDENTITY_UNCONFIRMED`；详见 [官方证据核查](cni-identity-20261116.md)。

## 14 条指数最新状态

| 指数 | 11 月 16 日参考 | 质量门禁 | 已发布截止 | 原因 |
|---|---|---|---|---|
| 480080 成长100R | CNI official HTTPS / 20261116 | 未通过 | 20261113 | IDENTITY_UNCONFIRMED |
| 480081 价值100R | CNI official HTTPS / 20261116 | 未通过 | 20261113 | IDENTITY_UNCONFIRMED |
| H00821 沪深300红利 | CSI official HTTP / 20261116 | 通过 | 20261116 | — |
| H00300 沪深300 | CSI official HTTP / 20261116 | 通过 | 20261116 | — |
| H00918 沪深300成长 | CSI official HTTP / 20261116 | 通过 | 20261116 | — |
| H00919 沪深300价值 | CSI official HTTP / 20261116 | 通过 | 20261116 | — |
| 932000CNY010 中证2000 | CSI official HTTP / 20261116 | 通过 | 20261116 | — |
| H00811 中证细分有色 | CSI official HTTP / 20261116 | 通过 | 20261116 | — |
| H00813 中证细分化工 | CSI official HTTP / 20261116 | 通过 | 20261116 | — |
| H20180 中证银行 | CSI official HTTP / 20261116 | 通过 | 20261116 | — |
| H20035 沪深300非银金融 | CSI official HTTP / 20261116 | 通过 | 20261116 | — |
| H00922 中证红利 | CSI official HTTP / 20261116 | 通过 | 20261116 | — |
| H20903 中证A股 | CSI official HTTP / 20261116 | 通过 | 20261116 | — |
| H20915 港股通高股息投资人民币全收益 | CSI official HTTP / 20261116 | 通过 | 20261116 | — |

参考原始响应的请求参数、采集时间、真实上游、SHA-256 和归档路径见机器可读证据；AkShare 与编制机构直连属于同一上游，不作独立来源。

## 26 条序列与策略日期

四维状态汇总：`{'acquisition_status': {'SUCCEEDED': 24, 'NOT_RUN': 2}, 'freshness_status': {'STALE': 2, 'CURRENT': 15, 'UNKNOWN': 9}, 'current_quality_status': {'UNVERIFIED': 3, 'PASS': 23}, 'release_status': {'USING_PREVIOUS': 2, 'PUBLISHED': 15, 'NOT_APPLICABLE': 9}}`。逐系列原始状态、来源和受影响模块见 JSON 的 `series`。

| 策略 | 输入指数 | 共同有效日 | 计算截至 | 结果 |
|---|---|---|---|---|
| 三棱镜轮动 | 480080 / 480081 | 20261113 | 20261113 | MATCH |
| 沪深300红利与沪深300轮动 | H00821 / H00300 | 20261116 | 20261116 | MATCH |
| 沪深300成长与沪深300价值轮动 | H00918 / H00919 | 20261116 | 20261116 | MATCH |
| 中证2000与沪深300轮动 | 932000CNY010 / H00300 | 20261116 | 20261116 | MATCH |
| 中证细分有色与中证细分化工轮动 | H00811 / H00813 | 20261116 | 20261116 | MATCH |
| 中证银行与沪深300非银金融轮动 | H20180 / H20035 | 20261116 | 20261116 | MATCH |
| 沪深300红利与沪深300成长轮动 | H00821 / H00918 | 20261116 | 20261116 | MATCH |
| 中证红利与中证A股轮动 | H00922 / H20903 | 20261116 | 20261116 | MATCH |
| 中证红利 / 港股通高股息（人民币全收益） | H00922 / H20915 | 20261116 | 20261116 | MATCH |

九组策略均与各自已发布输入序列的共同有效日一致；三棱镜停在 11 月 13 日，其余八组到 11 月 16 日。页面保持原 ECharts 图表。

## 隔离更新、故障与重复执行

真实 Provider 增量取得 14/14 条参考；12 条通过门禁并发布，2 条国证沿用旧版；3 条 ETF 更新至 11 月 16 日。首次运行生成隔离发布版本。第二次运行发现可选上游字段引起的无意义新版本，已修复；第三次真实运行返回 `UNCHANGED`，快照 ID 保持不变。

单指数模拟 HTTP 403：{'status': 'PASS', 'failed_code': 'H00300', 'latest_fetched_count': 13, 'http_status': 403, 'snapshot_unchanged': True, 'market_unchanged': True}。模拟发布中断：{'status': 'PASS', 'publication': {'status': 'WITHHELD', 'reason': 'FETCH_OR_VALIDATION_FAILED', 'error_type': 'OSError'}, 'snapshot_unchanged': True, 'market_unchanged': True}。真实规模隔离回滚：{'status': 'PASS', 'before': '20261116T212333-7262a956', 'after': '20261116T194338-32527f07', 'integrity': 'ok', 'backup_inventory_match': True}。故障演练均在隔离副本，行情表与前一快照保持不变。

## 自动化验收

离线 `D:\Anaconda3\envs\QuaTra\python.exe -m pytest -q`：470 passed、24 skipped；在线设置 `RUN_INDEX_ONLINE=1` 与 `INDEX_ONLINE_TARGET=20261116` 后运行两组 Provider 测试：24 passed。Playwright 16 个页面/视口组合、数据中心策略日期桌面与移动端、三棱镜及沪深300红利图均通过。截图和 JSON 位于 `evidence/release-ready-20261117/`。

## 正式发布与回滚操作

**尚未执行正式发布。** 操作前停止本地 FastAPI 与 Windows 定时任务，确认无其他进程写入正式库。现有封存包在上述备份目录；若正式数据已改变，必须重新制作一致性备份。

```powershell
$project = 'D:\我的坚果云\09-Codex\02-软件应用学习\etf-market-dashboard'
$formal = Join-Path $project 'data'
$backup = 'D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\release-ready-20261116\rollback-package'
Set-Location $project
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.windows_local_release preflight --data-dir $formal
# 核对输出 snapshot_id 与备份包均为 20261116T194338-32527f07，且 integrity=ok。
$env:ETF_DATA_DIR = $formal
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.daily_verified --through 20261116 --overlap-days 7
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.windows_local_release preflight --data-dir $formal
# 若需要回滚，先再次停止 API/定时任务；如下命令保留后续不可变快照文件。
$current = (Get-Content -LiteralPath (Join-Path $formal 'current_manifest.json') -Raw | ConvertFrom-Json).snapshot_id
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.windows_local_release rollback --data-dir $formal --backup-dir $backup --expected-current $current
```

回滚脚本会校验备份清单、SQLite 完整性与快照哈希，检测 WAL/SHM 等侧文件；遇到活动连接或备份不一致则拒绝操作。正式运行后应再核对 `/api/snapshot`、数据中心、策略日期及 Manifest 文件哈希。

## 仍待处理

历史 0.01 点供应商差异 94 条，及 H20180 2013-06-28、H20915 2018-06-18/2026-11-07 的状态与原始哈希见证据 JSON。两条国证 R 指数的币种及其历史有效期仍需编制机构正式说明；不放宽门禁。此前中证 HTTP 403 的单一成因仍未确定，当前在线测试已恢复。
