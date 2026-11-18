# 数据核验与自动运行交付记录（2026-11-15）

本记录区分参考响应覆盖、编制机构数值匹配、供应商差异和完整身份确认。逐日证据在 `data/etf_market.db` 的 `index_converged_status`、`index_reference_batches`、`index_reference_observations`、`index_reference_failures`；原始响应在 `data/verification/raw/` 和 `data/verification/htbr/`。机器可读汇总见 `data/verification/convergence-summary.json`。

## 第一阶段：核验结果收敛

`python -m scripts.index_convergence` 得到 14 条指数、46,552 个唯一指数日期。表中“编制机构一致”仅是点位一致数量；身份、币种、来源和日历仍分别判定。“供应商差异”包含华泰柏瑞高 0.01 点的日期，不通过放宽容差消除。

| 指数 | 本地 | 参考覆盖 | 编制机构一致 | 华泰柏瑞一致 | 供应商差异 | 无参考 | 身份/特殊状态 |
|---|---:|---:|---:|---:|---:|---:|---|
| 480080 | 3366 | 3366 | 3366 | 3 | 0 | 0 | 官方币种未确认 |
| 480081 | 3366 | 3366 | 3366 | 3 | 0 | 0 | 官方币种未确认 |
| H00821 | 3364 | 3364 | 3364 | 3 | 0 | 0 | 编制机构资料已留证 |
| H00300 | 3364 | 3364 | 3364 | 2 | 1 | 0 | 2026-11-10 供应商高 0.01 |
| H00918 | 3364 | 3364 | 3364 | 3 | 0 | 0 | 编制机构资料已留证 |
| H00919 | 3364 | 3364 | 7 | 3337 | 27 | 0 | 其余编制机构原始 HTTP 尚未覆盖 |
| 932000CNY010 | 3126 | 3126 | 7 | 3120 | 6 | 0 | 同上 |
| H00811 | 3364 | 3364 | 7 | 3340 | 24 | 0 | 同上 |
| H00813 | 3364 | 3364 | 3114 | 3340 | 24 | 0 | 同上 |
| H20180 | 3364 | 3364 | 3363 | 3 | 0 | 0 | 2013-06-28 推导值无独立正值佐证 |
| H20035 | 3364 | 3364 | 3364 | 3 | 0 | 0 | 编制机构资料已留证 |
| H00922 | 3364 | 3364 | 3364 | 3 | 0 | 0 | 编制机构资料已留证 |
| H20903 | 3364 | 3364 | 3364 | 3 | 0 | 0 | 编制机构资料已留证 |
| H20915 | 3054 | 2989 | 2989 | 2975 | 12 | 65 | 独立日历；38 个零成交量日期待复核 |

四条华泰柏瑞全历史系列原有 81 条一分差异；另发现 H00300 一条、H20915 十二条，共 94 条。原始供应商数值最多两位小数，无法证明舍入规则。29 条有编制机构 HTTP 原始响应支持本地值。影响测算及年份/日期明细见上述 JSON 和 `docs/index-convergence.md`。H20915 2018-06-18 为港交所休市且中证零成交量占位；2026-11-07 为周末本地记录，未删除；其 65 个本地日期两个渠道均无参考。H20180 2013-06-28 中证返回零，不能用来证明本地推导值。国证 480080/480081 的官方点位全覆盖，官方币种材料仍不足。

阶段验收：唯一日期数与正式行数一致；来源、身份、数值、日历独立显示；未决项明确保留，阶段工程门槛通过，金融事实未决项没有被宣称通过。

## 第二阶段：集中式数据中心

`/web/data-center.html` 和只读 `/api/data-center` 汇总 26 条实际系列，包含 14 指数、3 ETF 行情、6 份额/资金流、2 股息和 1 估值系列；指数逐日接口为 `/api/data-center/indexes/{code}`。页面提供类型、状态、来源筛选、异常证据、版本、来源诊断和最近增量核验。当前估值系列缺乏统一逐日状态来源，明确显示“未知”。原有 5 类聚合卡片保留兼容。

本机真实服务返回 26 条系列；最近一次参考采集后 25 条运行状态正常、1 条未知、未恢复的来源失败 0 条。历史失败仍在证据表。16 组桌面/手机页面冒烟均返回 200、无页面脚本错误或横向溢出；证据在 `docs/engineering-v2/evidence/live-smoke.json`。这不构成全部图表数值的独立验算。

## 第三阶段：每日增量与故障隔离

`python -m scripts.daily_verified --overlap-days 7` 按每条指数自己的最近 7 个已存交易日取重叠窗口。单指数参考失败记录为 `REFERENCE_UNAVAILABLE` 或 `REFERENCE_ERROR`，其余指数继续；失败文本不进入公开诊断。可用 `--sample-history` 对每条指数轮转抽检 20 个较早交易日，`--verify-only` 仅更新参考证据与报告。单日结果原子写入 `data/verification/daily/YYYYMMDD.json`，同日重跑覆盖该结果；原有参考批次以稳定主键重复执行。Windows 脚本及 GitHub Actions 已调用该入口。

发布仍调用 `update_dataset(require_reference_verification=True)`：新增或变化的指数点位必须具有同口径、原始哈希有效的编制机构参考；否则整次发布为 `WITHHELD`，旧 Manifest 和快照保持可读。历史日历异常在严格模式下保留于正式表和扁平快照，不因每日刷新删除；策略计算继续使用适用交易日历。ETF 备用源仍走原有隔离及人工证据流程。**本次只执行了真实 `--verify-only`，未执行真实发布。**

2026-11-13 截止的真实增量取数结果：14 条参考请求均取得响应，0 条接口失败；记录见 `data/verification/daily/20261113.json`。这表示可获取，不等于 14 条全部已通过身份和历史数值门禁。此前 HTTP 403 的中证接口本次可访问；旧 403 响应摘要仍在 `index_reference_failures`，根因（临时权限、限流或环境）尚不能凭一次恢复确定。

## 测试与数据保护

- 离线 pytest 的 XML 记录：`data/verification/offline-test-20261115.xml`；真实 Provider 在线 10 个窗口的独立记录：`data/verification/online-test-20261115.xml`。默认 pytest 跳过这 10 个在线用例，在线结果必须另计。
- `python -m scripts.index_verification_integrity` 核对正式 `index_prices` 与 SQLite 一致性基线、Manifest 和指数 JSON 起始摘要，均保持不变；306 个已采集原始批次及身份资料哈希无失败。
- 本机 UI 报告：`docs/engineering-v2/evidence/live-smoke.json`。固定样本 UI 与数据库测试见 `tests/`。

## Windows / Linux 运行

Windows 本地：`powershell -File scripts/run_daily_verified.ps1 -OverlapDays 7`。Linux 或计划任务：在代码目录设置绝对路径 `ETF_DATA_DIR` 指向独立持久目录，再运行 `python -m scripts.daily_verified --overlap-days 7`；调试时先用 `--verify-only`。定期执行 `--sample-history`，全历史补证可用 `python -m scripts.index_verification verify-full --resume`。代码包、SQLite 一致性备份和失败时恢复旧代码链接的步骤见 `docs/engineering-v2/04-deployment.md`。本次未连接真实 Linux 服务器执行部署或发布。

当前限制：H20180 推导值、H20915 特殊日历与缺失日期、国证币种证据及 94 条供应商一分差异仍需编制机构进一步材料；每日发布门禁对新增指数点位依赖可用的官方原始响应。数据中心非指数系列的逐证券诊断与任务状态仍较粗，发布任务尚不支持按数据集分别提交独立快照。
