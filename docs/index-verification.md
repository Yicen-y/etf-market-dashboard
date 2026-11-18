# 14 条指数核验专项（2026-11-15）

`scripts/config.py` 的 `INDEXES` 是唯一对象注册表。核验只追加参考、任务、结果及质量证据，不改写正式 `index_prices` 或 JSON Snapshot。SQLite 一致性副本、逐日结果、异常结论和官方资料哈希分别见 `data/verification/baseline/`、`verification-report.json`、`exception-conclusions.json`、`identity/identity-evidence.json`。

## 运行

```powershell
python -m scripts.index_verification audit
python -m scripts.index_identity_evidence
python -m scripts.index_verification calendar
python -m scripts.index_verification verify-window --code H00821 --start 20130603 --end 20130701
python -m scripts.index_verification verify-window --code H00821 --start 20261008 --end 20261111
python -m scripts.index_verification verify-full --resume
python -m scripts.index_verification reassess
python -m scripts.index_verification report
python -m scripts.index_verification_integrity
powershell -File scripts/run_daily_verified.ps1 -OverlapDays 7
```

每日脚本调用 `scripts.daily_verified`，逐指数按自身最近 7 个交易日取得重叠窗口。单条参考请求失败只记录该指数为未取得，其他指数继续；随后更新器只允许有同口径、带哈希的编制机构参考证据的新增或变化点位发布，否则旧快照继续有效。`--verify-only` 可先单独检查参考源，`--sample-history` 轮转抽检旧窗口。GitHub 定时工作流和服务端更新入口也启用了严格门禁；直接运行旧 CLI 不带门禁参数仍保留兼容行为。分批运行使用稳定任务 ID，`--resume` 仅重试未成功批次，原始响应按 SHA-256 保存；历史修订单独记录。历史补缺用 `verify-full --resume`。

## 数据源与身份

| 对象 | 历史来源 | 身份证据 | 原始层级 |
|---|---|---|---|
| 12 条中证指数 | AkShare/CSI、直接 CSI `index-perf` | 中证官方资料 PDF 与响应英文全称、代码 | 部分完整 HTTP 响应；其余为 AkShare DataFrame 序列化 |
| 480080、480081 | 国证官方 HTTPS 日线接口、AkShare/CNI | 国证官方资料 PDF、英文指数列表与请求代码 | 每条 3,366 个本地点位均有官方 HTTPS 原始响应及哈希 |
| ETFirst | H00919 试查返回空历史 | 不能作本轮数值核验来源 | 无有效参考行 |
| Wind MCP | 本周调用额度已满（429） | 暂不能补充对账 | 无有效参考行 |

AkShare/CSI 与直接 CSI HTTP 指向同一上游，AkShare/CNI 与国证 HTTPS 也指向同一上游；各自不能算两个独立发布机构。中证历史接口是 `https://www.csindex.com.cn/csindex-home/perf/index-perf`，国证日线接口是 `https://hq.cnindex.com.cn/market/market/getIndexDailyDataWithDataFormat`。适配器保存 HTTP 原始字节、请求参数、响应哈希、时间与真实上游。国证接口返回四位小数，本地逐日差异按 0.00005 容差核验。旧 AkShare 批次仅保存解析后的 DataFrame：其点位相等列入 `numeric_match`，但综合状态改为 `SOURCE_EVIDENCE_INCOMPLETE`，不能作为已完成的权威来源核验，也不能通过每日发布门禁。14 份官方资料及哈希已落盘；国证[英文指数列表](https://www.cnindex.com.cn/eng/indices/cni/style/index.html?act_menu=2&index_type=202)明确将 480080 列为 TRI，官方 PDF 列出 480080/480081 的 R 代码；但计价货币尚缺明确资料字段，故两条即使数值全相等仍为 `IDENTITY_UNCONFIRMED`。

## 403 诊断

AkShare 1.18.64 的 `stock_zh_index_hist_csindex` 对 CSI `index-perf` 直接执行 GET 后调用 `r.json()`，未先检查 HTTP 状态。失败时实际响应为 **403、`text/html`**，故被包装成 JSON 解析错误。相同接口和参数后来返回 200；原先 84 个失败批次重试成功，三条试点的 42 个完整历史批次亦成功。随后密集请求又出现 403。证据与暂时性网关限制或限流相符，但没有上游说明，不能进一步确定根因，也不能保证持续可用。核验器记录脱敏状态、内容类型和响应体哈希；本地没有可用的服务器执行环境或主机地址，未做服务器侧访问对比。不得通过伪装身份或绕过访问控制处理此问题。

## 专项异常

| 指数与日期 | 结论 | 证据 |
|---|---|---|
| H20180，2013-06-28 | 推导值 **暂无法独立确认** | 本地 4303.99；中证原始 HTTP 为 0.00。原始参考本身异常，不能把推导修复视为官方点位。 |
| H20915，2026-11-07 | **确认非交易日日期异常**，未改动正式行情 | 周六本地 12514.56；中证参考无该日；本地 11 月 9 日同值。[港交所交易时段](https://www.hkex.com.hk/Global/Exchange/FAQ/Securities-Market/Trading/Securities-Market-Operations?sc_lang=en)为周一至周五。 |
| H20915，2018-06-18 | **确认非交易日占位行**，未改动正式行情 | 中证响应点位沿用前日、成交量为零；[港交所 2018 年假日日历](https://www.hkex.com.hk/-/media/hkex-market/services/circulars-and-notices/participant-and-members-circulars/sehk/2017/mo_dt_063_17_e)列为端午节假日。 |

中证接口若从非交易日开始请求，可能额外返回一条使用下一交易日点位、却标成请求起始日的行。已用独立的 AkShare/Sina 内地交易日历及交易日起始窗口复核；2013-06-01、2018-06-18、2026-10-01 等参考行按日历异常列示，不当作本地缺口。H20915 仍按自身市场及港股通规则审查，不能套用 A 股日历。

## 测试与未解事项

离线测试覆盖匹配、容差、身份冲突、非交易日、修订、幂等、失败回滚、原始响应与发布门禁。真实中证 Provider 测试曾因 403 失败，接口恢复时 3 项可获取性测试通过；加强为“早期和近期区间逐日匹配”后，最近 6 项在线中证测试均遇 403。此前独立重取的六个区间及三条全历史 HTTP 原始响应仍已保存并通过哈希检查。国证两条全历史已重新取得官方 HTTPS 原始响应，早期和近期的 4 项在线测试最终均通过；首次运行其中 2 项曾遇本机代理 TLS 握手失败，重试成功，说明可用性仍会波动。每日实跑中证接口再次遇 403，返回码 2，正式行情和快照摘要保持不变。完整覆盖表及所有未核验日期见 `verification-report.json`。

仍需取得 CNI 两条指数的明确计价货币证据、解释 H20915 的其他 65 个无参考日期与 38 个待复核零成交量日期，并为 H20180 推导值寻找独立授权历史记录。当前没有服务器主机配置，无法判定服务器访问是否优于本机。下一步应向中证确认 `index-perf` 的稳定访问约定或使用正式授权渠道；Wind 额度重置后可再试，但需先核对 Wind 代码和收益口径。

## 华泰柏瑞授权接口补充核对

使用已授权的华泰柏瑞指数接口完成 14 条代码的精确映射、静态资料和近期日行情试查。接口元数据表明日行情经聚源通道提供；这是另一条供应商取数通道，尚不能证明与中证或国证发布源在底层完全独立。原始业务响应、请求、时间、追踪号、哈希和逐日差异保存在 `data/verification/htbr/`，可运行 `python -m scripts.htbr_index_report` 离线复核全部证据哈希。真实试查需 Python 3.10 以上及华泰柏瑞授权技能；本机可运行 `& 'D:\Anaconda3\envs\IStock\python.exe' -m scripts.htbr_index_probe --codes H00919 H00811 --start 20261008 --end 20261111`。

H00919、932000CNY010、H00811、H00813 的全部本地历史日期均有供应商点位；分别有 27、6、24、24 个日期相差 0.01 点，其余按供应商两位小数的 0.005 点容差一致。四条合计 13,137 条一致、81 条供应商冲突。H00300 最近窗口也有一个 0.01 点供应商冲突，而中证官方原始响应与本地点位一致，故不可用供应商值覆盖官方记录。国证原始点位为四位小数，华泰柏瑞日行情为两位小数；补充核对按供应商公布的两位小数精度判断，不能用于确认原始四位数。

H20180 的 2013-06-28 周边七条本地记录在该接口均无点位，因此推导值仍未获独立确认。H20915 的 2018-06-18 和 2026-11-07 在华泰柏瑞日行情中均无记录，邻近日有数据，支持日历异常结论。接口静态资料提供英文全收益名称和基日，但本轮不自动把供应商数值相等提升为编制机构原始来源已核验；正式行情、Manifest 和快照保持不变。
