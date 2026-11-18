# 已确认非交易日候选删除（2026-11-17）

用户明确要求直接删除已经证实为非交易日的候选。本次删除范围固定为 34 个 `(指数代码, 日期)`，先备份并在隔离副本试运行，再执行正式库删除。

| 日期 | 指数 | 删除的问题记录 | 删除的原始候选行 |
|---|---|---:|---:|
| 2018-06-18 | H00922 | 1 | 2 |
| 2026-10-31 | 11 条中证内地指数 | 11 | 11 |
| 2026-11-07 | 同上 | 11 | 11 |
| 2026-11-14 | 同上 | 11 | 11 |
| 合计 |  | **34** | **35** |

三个 2026 年日期均为星期六。2018-06-18 是上交所公告的端午节休市日：[上交所公告](https://www.sse.com.cn/disclosure/announcement/general/c/c_20180606_4567900.shtml)。H20915 的独立市场日历不在本次删除范围。

每个候选在删除前均确认不存在于 `index_prices`、`canonical_observations` 和当前指数快照，且没有其他质量问题引用待删原始行。删除仅涉及 `quality_issues` 的 34 行和 `raw_observations` 的 35 行；保留其他有效日期共用的原始响应归档文件，避免破坏它们的哈希证据。删除范围、原 issue ID 与 raw ID 可由[备份](../../../.scratch/nontrading-purge-20261117/before/backup_inventory.json)及[执行脚本](../../../.scratch/nontrading-purge-20261117/purge.py)复核。

发布前后 `etf_prices`、`index_prices`、`canonical_observations`、`release_manifest` 全行一致，Manifest 与两份 JSON 逐字节一致；SQLite `integrity_check=ok`，数据中心 `snapshot_database_consistency=MATCH`。快照仍为 `20261117T211724-1c548b20`。离线测试 498 项通过。数据中心还剩 3 条真正待复核记录：H20180 2013-06-28 两条、H20915 2026-11-14 一条。

`scripts.nontrading_candidates` 已记录这 34 个明确裁定的键；后续更新不会再把同样的候选行写回原始观察或质量问题。完整回退可在停止本地 API 后按 `scripts.windows_local_release rollback` 使用本次备份执行，须先核对当前快照版本和 SQLite sidecar 状态。
