# 数据空间核对与清理（2026-11-13）

## 已删除

`data/backups/etf-akshare-rebuild-20261105T214641/` 中的 `current_manifest.json`、`etf_market.db`、`etf_prices.json` 三个文件与 `data/backups/etf-akshare-rebuild-20261105T214555/` 同名文件逐一 SHA-256 相同，且代码、文档没有引用被删除目录。保留较早的完整副本，删除较晚副本及空目录，共释放 **38,738,079 字节（约 36.9 MiB）**。这三个文件原本受 Git 跟踪，可从 Git 历史恢复。

## 保留依据

- `data/current_manifest.json` 指向 `20261111T214903-865e1e9e`，当前两份快照均通过哈希和接口检查。
- `data/releases/` 的其余文件没有完全重复的整套发布版本。`20261105T202024-51949b82` 与 `20261105T214647-akshare-642ae027` 的指数文件相同，但 ETF 文件不同，不能删除任一整个发布目录。其他旧发布的哈希也不同；部分版本仍由研究报告引用。七个旧目录只保留指数文件，尚不能断定其历史数据无价值。
- SQLite 的 `release_manifest` 有 20 条历史发布记录、0 条待恢复记录；数据库没有名称为 backup 或 old 的备份表。`raw_observations`、`canonical_observations` 等是溯源及业务数据，不是冗余备份，因此未删除数据库记录或执行 `VACUUM`。
- 其他 `.db`、`.bak` 备份哈希各异，有的在研究报告中作为变更前恢复点引用，暂予保留。原始证据也全部保留。

## 清理后核验

SQLite `PRAGMA integrity_check` 返回 `ok`；当前快照及存储相关 8 项测试通过。备份目录从 455,168,318 字节降至 416,430,239 字节。`data/releases/` 与当前数据库未因本次清理修改。
