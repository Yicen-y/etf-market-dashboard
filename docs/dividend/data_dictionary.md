# 红利数据字典（D0 增量）

`dividend_events.event_id` 表示经济事件；`dividend_revisions.revision_id` 表示预案、修订或实施公告版本。`ex_date` 是经济生效日期，`disclosed_at/known_at` 是公开可知时间，`observed_at` 是本地抓取时间。原始每10份金额必须在 revision 中保留，标准化每份金额写入 event。

`dividend_watchlist` 只保存本地单用户自选关系，不删除事件或证据。`source_documents.sha256` 和 `raw_source_records.sha256` 用于不可变证据去重。
