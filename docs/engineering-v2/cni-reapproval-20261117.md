# 国证 480080 / 480081 双路径放行补录与正式增量发布

## 原因

开始时正式快照为 `20261117T144646-997729f0`，两条指数的正式最新日均为 `20261113`；`index_route_approvals` 对这两条指数没有记录，正式国证参考批次也只覆盖到 `20261113`。此前 `20261117T105243-ec61f3e1` 版本曾按双路径规则放行并发布 `20261116`，但后续受控回滚后的当前库没有沿用该版本的放行记录。数据中心调用 `gate_index_candidates` 检查当前点位，因缺少逐日放行证据返回“尚未核验”。这是当前正式数据证据状态，并非规则没有实现。

## 本次核验和发布

先对正式 SQLite 做一致性备份，并封存当前 Manifest 与 JSON 到 `D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\cni-reapproval-20261117\formal-before`；备份 `integrity_check=ok`，事后复算文件与 `backup_inventory.json` 一致。所有获取、门禁和发布步骤先在 `...\cni-reapproval-20261117\work` 隔离副本通过，再在正式数据目录重新实时取数。没有用隔离数据库覆盖正式数据库。

| 指数 | 日期 | 国证直连 | AkShare/CNI | 逐日门禁 |
|---|---|---:|---:|---|
| 480080 成长100R | 2026-11-13 | 8928.4511 | 8928.4511 | 通过 |
| 480080 成长100R | 2026-11-16 | 8187.6154 | 8187.6154 | 通过 |
| 480081 价值100R | 2026-11-13 | 8078.5654 | 8078.5654 | 通过 |
| 480081 价值100R | 2026-11-16 | 8218.8424 | 8218.8424 | 通过 |

两条路径同属国证上游，属于用户明确认可的**同上游双路径数值放行**，不声称独立上游验证，也不把缺失的官方计价货币字段伪装为已确认。原始国证 HTTP 响应、AkShare 解析帧、采集时间、请求日期、两份 SHA-256、归档路径及逐日相等检查见[正式来源证据](evidence/cni-reapproval-20261117/formal-route-evidence.json)；四条原始文件均通过哈希复算。本轮请求至 `20261117`，两条路径共同可用的最新日期为 `20261116`，因此未发布 11 月 17 日国证点位。

正式环境仅运行 `--index-only --end-date 20261116 --require-reference-verification`。结果为 `PUBLISHED`，新快照 `20261117T194829-8cf69d60`。对比发布前备份：ETF 业务行仍为 6103，逐行不变；指数行从 46588 增至 46590，**只新增**两条上述 11 月 16 日点位；无删除、无旧值修订。旧版本两份不可变发布文件哈希不变。新 Manifest 与 ETF/指数 JSON SHA-256 分别为 `38ae8a7c50138605d4610967db569b182a25a0ed603283369030cf423816e054`、`de9e5c2999fd9b96d609b445e63a901a5ef56ca11f3db2ba7d5dd238e5500b17`、`505421ac42489dfff05110e866825ee65411783bd211580c563c4b1d4ec1c5a3`。逐行与版本检查见[正式发布校验](evidence/cni-reapproval-20261117/formal-release-check.json)。

FastAPI `/api/snapshot`、`/api/data-center` 返回 HTTP 200 和新快照；两条指数的 `current_quality_status=PASS`、已发布日 `20261116`、身份说明 `ROUTE_APPROVED_CURRENCY_UNCONFIRMED`。数据中心显示 `snapshot_database_consistency=MATCH`；九组策略输入日期及计算截至日均为 `20261116`、状态均为 `MATCH`。桌面和移动端浏览器 4 组检查通过，见[UI 结果](evidence/cni-reapproval-20261117/data-center-cni-pass-ui.json)及[480080 当前质量截图](evidence/cni-reapproval-20261117/data-center-480080-1440-quality.png)。相关离线回归 19 项通过；隔离副本重复更新返回 `UNCHANGED` 且版本不变。

## 状态边界与回滚

数据中心“当前质量”现在为 `PASS`，表示**当前已发布点位**符合用户接受的双路径规则。历史质量仍列为未完全核验：本次只对 11 月 13 日和 16 日建立逐日放行记录，不能把 3367 条历史记录一并宣称为双路径已核验。官方币种字段仍未明示，身份栏继续如实标注。此前的历史异常和来源记录均未删除或覆盖。

如后续发现发布内容有误，先停止本地 API 和更新任务、确认无 SQLite sidecar，再执行已封存备份的回滚：

```powershell
Set-Location 'D:\我的坚果云\09-Codex\02-软件应用学习\etf-market-dashboard'
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.windows_local_release rollback --data-dir 'D:\我的坚果云\09-Codex\02-软件应用学习\etf-market-dashboard\data' --backup-dir 'D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\cni-reapproval-20261117\formal-before' --expected-current '20261117T194829-8cf69d60'
```

本次没有启用 Windows 无人值守任务。
