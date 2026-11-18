# 万得全A（881001.WI）核验与增量更新

截至 2026-11-17，`wind_index_daily_prices` 保存 2019-01-02 至 2026-11-17 的 1,909 个交易日。以 AkShare `tool_trade_date_hist_sina` 提供的交易日期集合逐日比对，缺口、非交易日、重复日期均为 0。1,909 条记录的 `verification_status` 为 `PASS`；`wind_index_calendar_checks` 保存日期集合、SHA-256 和核验时间。此标记只证明日历完整性和 Wind 返回数据的基本格式，不代表点位经第二家行情源复核。

Windows 本地人工增量运行：

```powershell
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.wind_alla_incremental incremental
```

默认截至北京时间 16:00 后的当天，否则截至前一天。也可显式指定 `--through YYYY-MM-DD`。程序先取交易日历；没有新交易日时返回 `UNCHANGED`，不请求 Wind、不改写点位。出现新交易日时，仅请求最后已入库日期前 14 个日历日到目标日的 Wind 日线，比较重叠区间的原有数值，核对新增日期是否完整、是否为交易日。通过后同一 SQLite 事务写入新增点位、Wind 原始响应与哈希、日历核验记录。Wind 失败、缺日、非交易日或旧点位被修订时终止事务，保留原有数据供人工检查。

该序列与现有 14 条策略指数隔离，增量命令不生成或切换 JSON Snapshot，也不修改策略输入。每次正式人工运行前应使用 SQLite 一致性备份；首次新增交易日的在线更新仍须实际运行验收。
