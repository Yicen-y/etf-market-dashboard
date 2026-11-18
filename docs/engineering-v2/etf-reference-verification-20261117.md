# 三只 ETF 当前点位核验（2026-11-17）

结论：三只 ETF 的当前点位均为 `PASS`。正式行情和当前快照 `20261117T211724-1c548b20` 未改写；仅新增独立核验证据表 `etf_reference_checks`，每只 7 行。

| ETF | 正式 11 月 17 日收盘价 | 华泰柏瑞未复权场内收盘价 | 同口径连续匹配 | 当前质量 |
|---|---:|---:|---:|---|
| 510330 | 4.221 | 4.221 | 7 个交易日 | PASS |
| 512530 | 1.748 | 1.748 | 7 个交易日 | PASS |
| 562310 | 0.814 | 0.814 | 7 个交易日 | PASS |

参考接口为华泰柏瑞 `fund-daily-quote`，实际数据链路为 `RAGAPI.FundsPerformanceHis`，请求 `adjustingMethod=3`（不复权），区别于东方财富主源及基金净值。请求参数、采集时间、逐日差值、参考原始响应路径及 SHA-256 均存入核验表；原始响应归档于 `data/verification/etf-reference/`。正式本次三份响应 SHA-256 分别为：510330 `9cdd22943f016651a088750ac4aef669e0a1df8acff13f1d2e17b38cd51c123a`，512530 `dd223869fb06bc7932fe8a1a1c63020d0962bd868cc46880cb5c65b2b6b7ca73`，562310 `fc262b4d58fb25ddc8e61b0024132ba1bb0a1fcbc4f219d2fd55627c11361ea2`。

程序要求至少 5 个本地与参考交易日，并逐日比较三位小数公布精度（绝对差不超过 0.0005 元）。任何一天冲突，整段核验均不判 `PASS`。数据中心每次读取还复查最新日期、正式点位及归档响应哈希；证据丢失或点位被修改则回到 `UNVERIFIED`。来源不可用时不伪造核验通过。

运行前通过 SQLite Backup API 及快照封存创建备份：`D:\我的坚果云\09-Codex\02-软件应用学习\.scratch\etf-verification-20261117-2130\before`。隔离副本真实取数两次，核验表始终各 7 行、状态均 PASS；正式库再独立取数一次。发布前后规范化市场内容摘要相同，Manifest 与 JSON 快照版本不变，数据中心 `snapshot_database_consistency=MATCH`。浏览器显示三只均为 `PASS / HTBR_RAW_MATCH_7D`；截图见[数据中心核验结果](../../../.scratch/etf-verification-20261117-2130/data-center-etf-pass.png)。离线自动测试 495 项通过。

手动重新核验命令：

```powershell
D:\Anaconda3\envs\QuaTra\python.exe -m scripts.etf_reference_verification
```

旧历史问题未因当前点位核验而清理：数据中心仍显示 510330 有 7 条、512530 有 36 条历史质量问题；562310 为 0 条。此处的 `PASS` 只说明最新点位及最近 7 个匹配交易日通过本次参考核对，不代表整段历史全部完成核验。
