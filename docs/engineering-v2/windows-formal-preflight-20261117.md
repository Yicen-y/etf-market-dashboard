# Windows 正式发布前只读检查（2026-11-17）

**结论：有条件 GO，仅限经用户批准后的受控增量发布。** 正式快照 `20261116T194338-32527f07`；隔离验收快照 `20261116T212333-7262a956`。目标完整交易日 `2026-11-16`。无人值守每日运行暂为 NO-GO，须在发布验收后补齐近 5 日运行记录与 Windows 任务计划。

## 正式环境与备份

正式 SQLite `PRAGMA integrity_check=ok`。正式库与 Manifest 指向的指数、ETF JSON 均逐条一致，缺失、额外与数值冲突均为 0；`snapshot_database_consistency=MATCH`。预检前后正式文件哈希一致：`True`。

SQLite Backup API 封存包：`D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\release-preflight-20261117\formal-backup`。备份清单与文件哈希一致：`True`；备份与正式 SQLite 全部表逻辑摘要一致：`True`；在真实规模隔离副本从新版本回滚到原版本：`{'before': '20261116T212333-7262a956', 'after': '20261116T194338-32527f07', 'integrity': 'ok', 'same_as_backup': True}`。

## 正式与隔离差异

| 数据集 | 正式条数 | 隔离条数 | 新增 | 删除 | 旧日期数值/来源变化 | 重复日期 |
|---|---:|---:|---:|---:|---:|---:|
| 指数 | 46576 | 46588 | 12 | 0 | 0 | 正式 0 / 隔离 0 |
| ETF | 6097 | 6100 | 3 | 0 | 0 | 正式 0 / 隔离 0 |

全部拟新增记录的日期均为 2026-11-16；新增来源为 12 条 `CSI official HTTP` 指数及 3 条 `AkShare` ETF。新增行情没有 `test`、`fixture`、`mock`、`simulated` 来源标记。14 条最近参考原始归档的 SHA-256 均可验证。逐条价格与来源见 `preflight.json`。

## 质量门禁和业务影响

隔离日任务：预期 14、参考取得 14、门禁通过 12、发布 12、沿用旧版 2。`480080`、`480081` 因官方点位计价货币证据未确认，继续停在 11 月 13 日；绝不使用已取得的 11 月 16 日数值绕过门禁。

可发布：12 条中证指数及 3 条 ETF 的 11 月 16 日新增点位。预计影响三棱镜以外的八组指数轮动、主看板、ETF 轮动总览、读取 `H20903/H00922` 的五年之锚，以及读取 `H00922/H20915` 的红利研究。三棱镜两条国证输入保留 11 月 13 日。股息事件与资金流向等独立表不会因本次行情发布自动变更。

| 策略 | 正式计算日 | 隔离计算日 | 隔离检查 |
|---|---|---|---|
| 三棱镜轮动 | 20261113 | 20261113 | MATCH |
| 沪深300红利与沪深300轮动 | 20261113 | 20261116 | MATCH |
| 沪深300成长与沪深300价值轮动 | 20261113 | 20261116 | MATCH |
| 中证2000与沪深300轮动 | 20261113 | 20261116 | MATCH |
| 中证细分有色与中证细分化工轮动 | 20261113 | 20261116 | MATCH |
| 中证银行与沪深300非银金融轮动 | 20261113 | 20261116 | MATCH |
| 沪深300红利与沪深300成长轮动 | 20261113 | 20261116 | MATCH |
| 中证红利与中证A股轮动 | 20261113 | 20261116 | MATCH |
| 中证红利 / 港股通高股息（人民币全收益） | 20261113 | 20261116 | MATCH |

数据中心当前正式目录基于本地旧参考日判断新鲜度，可能把 11 月 13 日显示为当前；隔离参考已证实 11 月 16 日为可用完整日。正式日任务运行后必须再次核对新鲜度与已发布截止日期，不把这项预检状态当作最新发布证明。

## GO 边界与待办

可在明确批准后运行正式采集、核验和部分发布；必须在开始前复核当前快照仍为 `20261116T194338-32527f07`、备份清单仍通过，停止其他本地写入进程。若快照或正式逻辑数据已变化，应重新备份和预检。当前未发现拟发布的测试行情、重复日期或历史行情覆盖。

Windows 定时任务未发现匹配的 ETF 看板任务，最近 5 个交易日的统一运行历史尚未建成。因此本报告不宣称已经达到无人值守稳定运行标准；第三阶段应在正式发布验收后实施并测试。历史 94 条 0.01 点差异、H20180、H20915 及间歇 HTTP 403 保留原状态。

## 获批后的操作与回滚

现阶段**未执行**下面的正式发布命令。先关闭本地 FastAPI 和计划任务，确保没有写入者，再在 PowerShell 执行：

```powershell
$project = 'D:\我的坚果云\09-Codex\02-软件应用学习\etf-market-dashboard'
$formal = Join-Path $project 'data'
$backup = 'D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\release-preflight-20261117\formal-backup'
Set-Location $project
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.windows_local_release preflight --data-dir $formal
$env:ETF_DATA_DIR = $formal
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.daily_verified --through 20261116 --overlap-days 7
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.windows_local_release preflight --data-dir $formal
# 若校验失败，停止进程后用封存包回滚：
$current = (Get-Content -LiteralPath (Join-Path $formal 'current_manifest.json') -Raw | ConvertFrom-Json).snapshot_id
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.windows_local_release rollback --data-dir $formal --backup-dir $backup --expected-current $current
```

正式发布后还需逐项核对 SQLite、Manifest、JSON、FastAPI、数据中心、九组轮动日期及既有业务图表；未核对前不得启动无人值守任务。

机器可读证据：`D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\release-preflight-20261117\preflight.json`。
