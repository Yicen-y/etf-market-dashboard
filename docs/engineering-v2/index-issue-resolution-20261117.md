# 指数检查记录收敛（2026-11-17）

正式库原有 75 条未关闭的指数检查记录，数据中心因只显示最近 30 条而在“指数日点位”卡片写作“检查记录：30 条”。本次在一致性备份和隔离复核后，仅更新 `quality_issues.resolution_status` 与 `resolution_evidence_id`；没有删除记录或改写任何行情。

| 处理结果 | 数量 | 证据规则 |
|---|---:|---|
| 已解决 | 38 | 同代码、同日点位已进入当前正式快照，SQLite 与快照一致，参考门禁重新通过；包括 36 条旧“来源末日暂缺”及 2 条国证旧“缺参考”记录 |
| 已排除 | 34 | 非交易日候选未进入正式行情表、Canonical 或当前快照；保留原始问题记录及候选证据 |
| 保持待复核 | 3 | 缺少充分证据，不自动关闭 |

剩余 3 条为：`H20180 / 2013-06-28` 的 `NON_POSITIVE_INDEX_VALUE` 和 `LEGACY_INVALID_OBSERVATION`（历史推导修复仍待独立确认），以及 `H20915 / 2026-11-14` 的 `REFERENCE_GATE_CALENDAR_REVIEW`（需按所属市场日历复核）。因此数据中心仍显示“有待关注记录：3 条”，现在对应真实未决事项；不表示 2026-11-17 已发布点位缺失。

执行前备份位于 `D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\issue-resolution-20261117\before`。隔离副本先预览、应用、重复执行，第二次候选数为 0；正式库再执行同样处理。前后 `index_prices`、`etf_prices`、`raw_observations`、`release_manifest` 全行一致，质量问题总行数一致，Manifest 及 ETF／指数 JSON 字节一致。快照仍为 `20261117T211724-1c548b20`，数据中心一致性为 `MATCH`。离线自动测试 497 项通过，浏览器显示检查记录 3 条；[核对截图](../../../.scratch/issue-resolution-20261117/data-center-after.png)。

`scripts.resolve_index_issues` 提供默认只读预览与 `--apply` 执行模式；正式增量发布成功后会自动尝试关闭有新证据覆盖的旧提醒，失败不会将已成功的行情发布误报为失败。
