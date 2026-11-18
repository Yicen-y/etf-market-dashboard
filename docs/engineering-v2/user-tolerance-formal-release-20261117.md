# 2026-11-17 Windows 本地受控正式发布

结论：**PASS**。正式快照从 `20261117T194829-8cf69d60` 更新为 `20261117T211724-1c548b20`。本次新增 14 条指数的 2026-11-17 点位；3 条 ETF 原已在正式快照中保存当日 14:48 的盘中点位，本次以 21:17 获取的收盘后响应修订该日点位。早于 2026-11-17 的行情行、来源和旧快照文件未改。

## 备份与执行

- 发布前通过 `python -m scripts.windows_local_release preflight --data-dir <正式 data>`；SQLite 完整性为 `ok`，原 Manifest 和 JSON 可读取。
- 停止本地 API 后，通过 SQLite Backup API 和文件封存创建备份：`D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\user-tolerance-release-20261117-2108\before`。`backup_inventory.json` 与备份内容一致，发布前正式库与备份库的规范化市场指纹相同。
- 先在同目录 `work` 隔离副本运行 `python -m scripts.daily_verified --through 20261117 --verify-only` 和 `python -m scripts.update_data --end-date 20261117 --require-reference-verification`。14 条官方参考均取得，14 条指数门禁均通过；隔离重复更新返回 `UNCHANGED`，快照版本未增加。
- 正式库重新实时运行上述核验和增量发布命令，没有以隔离数据库替换正式数据库。发布后重新启动本地 API。

## 行情变化

| 数据 | 发布前 | 发布后 | 变化 |
|---|---:|---:|---|
| 指数行 | 46,590 | 46,604 | 新增 14 条 2026-11-17 点位；无旧值修订或删除 |
| ETF 行 | 6,103 | 6,103 | 仅修订已有的 3 条 2026-11-17 盘中点位；无其他日期变化 |

ETF 当日修订：`510330` 4.218 → 4.221；`512530` 1.746 → 1.748；`562310` 0.812 → 0.814。修订前后均保留 AkShare／Eastmoney 原始观察、采集时间和可复算的归档 SHA-256。ETF 数据中心当前质量仍显示 `UNVERIFIED`，不能将本次行情发布等同于独立数值核验通过。

指数当日来源：`480080`、`480081` 为国证官方直连，其他 12 条为中证官方 HTTP。两条国证与 AkShare 当日分别是 7991.0659 对 7991.0659、8263.9368 对 8263.9368，属于精确相等；新设的 `<0.05` 用户容差规则本次没有用于放宽这两条的实际差异。14 条当前点位在数据中心均为 `PASS`。国证计价货币证据仍未完全确认，身份状态保留 `ROUTE_APPROVED_CURRENCY_UNCONFIRMED`；历史异常也未自动消除。

## 发布后核验

- SQLite `integrity_check=ok`；Manifest、两份版本化 JSON 和直接兼容文件的哈希一致。Manifest SHA-256：`617b6b1e546e1616bab7dd27d914e3083b94a2accca5a27124b0f585c917ad0a`；ETF JSON：`1303c6e6ae210a3a7469c4c9b87a3043f1edd447c0f1e8d35529c36fa324bfca`；指数 JSON：`a815dfff64a4c8ef047ba2c31a035b14ed5647905195f18a7f8a3bca5b3ea026`。
- 数据中心 `snapshot_database_consistency=MATCH`，26 条序列可读；9 组策略均为 `MATCH`，共同输入日和计算截至日均为 `20261117`，版本一致。
- FastAPI `/api/ready`、`/api/snapshot`、`/api/data-center`、两份 `/api/snapshot/data/*.json` 和 `/api/rotation/overview` 均读取正式新版本。
- Playwright 三棱镜和红利轮动页日期／版本检查通过；8 个核心页面在 1440px 和 390px 下共 16 次加载检查通过。发布后当前快照及门禁专项 pytest 5 项通过。新增容差规则发布前离线全量回归 493 项通过。
- 旧版本不可变文件哈希未变，`release_manifest` 无残留 `prepared` 行。

逐行变更、14 条点位门禁、策略日期和前后哈希见[正式校验 JSON](../../../.scratch/user-tolerance-release-20261117-2108/formal-check.json)。浏览器结果与截图在 `D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\user-tolerance-release-20261117-2108\ui`。

## 回滚

若后续发现发布数据错误，先停止本地 API 与更新程序，确认无 SQLite `-wal`、`-shm`、`-journal` sidecar，再执行：

```powershell
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.windows_local_release rollback --data-dir 'D:\我的坚果云\09-Codex\02-软件应用学习\etf-market-dashboard\data' --backup-dir 'D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\user-tolerance-release-20261117-2108\before' --expected-current '20261117T211724-1c548b20'
```

本次未启用 Windows 无人值守定时任务。旧历史核验问题和原始证据保留。
