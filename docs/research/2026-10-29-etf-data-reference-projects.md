# ETF 份额 / NAV 数据参考项目审查

审查日期：2026-10-29（Asia/Shanghai）。

本笔记记录四个参考项目的只读代码审查结论。没有复制外部代码，也没有把外部仓库中已提交的数据当作本项目的真实行情数据。

## 结论

| 项目 | 可采用内容 | 许可证与复用边界 |
| --- | --- | --- |
| [AKShare](https://github.com/akfamily/akshare) | `fund_etf_scale_sse`、`fund_scale_daily_szse` 份额入口；`fund_etf_fund_info_em` 历史单位净值入口 | MIT；本项目优先依赖已发布包，不复制内部实现；仍需遵守交易所和数据源条款 |
| [digger-yu/etf](https://github.com/digger-yu/etf) | AKShare 份额采集、SSE 逐日回填、SZSE 分段回填、按代码/名称映射的设计 | MIT；可借鉴并在保留版权/许可证前提下复用经验证的薄逻辑；禁止照搬其“最新 NAV 填满全部历史”的处理 |
| [zxtcc/szse-etf-share](https://github.com/zxtcc/szse-etf-share) | 深交所窗口、分页、重试、日期去重的观察 | 未发现许可证；只参考公开 API 行为和设计，不复制代码 |
| [steve849739/Etf-tracker](https://github.com/steve849739/Etf-tracker) | 采集、更新、展示分层及日常增量的设计 | 未发现许可证；只参考设计，不复制代码；其实现没有独立 NAV 流 |

## API 与单位核验

### AKShare 份额接口

AKShare 文档将 `fund_etf_scale_sse(date="YYYYMMDD")` 定义为上交所指定日期的 ETF 份额数据，包含基金代码、统计日期和基金份额；该接口是单日查询。`fund_scale_daily_szse(start_date, end_date, symbol="ETF")` 定义为深交所基金规模日频接口，日期区间不能超过 6 个月，返回日期、基金代码和基金份额。

两地接口的源字段同名，但不能仅凭列名假定单位相同。适配器必须保存源单位与标准单位，并用文档样例、数量级检查和官方抽样核验确认转换。应用内部统一为：

- 份额：万份；
- 单位净值：元/份；
- 资金流：亿元。

AKShare 的 `fund_etf_fund_info_em(fund, start_date, end_date)` 返回净值日期、单位净值和累计净值，可作为独立 NAV 事实流。它不能替代交易所份额，也不能用 AUM 变化推导净申赎。

### 参考实现中的重要风险

- `digger-yu/etf` 的份额接口调用方式和历史回填窗口值得参考，但其历史脚本把一个代表 ETF 的最新 NAV 写到多个历史日期，不能用于本项目的逐日 NAV 估值。
- `digger-yu/etf` 的第三方实时份额 fallback 没有经过本项目要求的日期与单位审计，因此只能做显式标记的候选 fallback，不得默认参与资金流计算。
- `zxtcc/szse-etf-share` 采用深交所接口的窗口、分页和重试思路有参考价值，但其证书处理不能直接复制到生产；本项目优先使用验证过的 TLS，必要时通过受控 CA 配置并记录警告。
- `steve849739/Etf-tracker` 的 Excel/JSON 持久化不满足本项目的 SQLite、独立 NAV 和质量审计要求，只参考分层结构。
- “请求成功但返回空表”不能直接解释为当日份额为零；必须记录空响应、失败窗口并保留上一份有效数据。

## 本项目采用的实现边界

1. 首选 AKShare 份额接口，按交易所分别处理日期和单位；SSE 按交易日逐日请求，SZSE 以不超过接口上限的窗口回填。
2. NAV 单独由 `NavProvider` 获取，并按 ETF 代码和净值日期与份额对齐；缺失 NAV 时流量为 `BLOCKED`，不填零。
3. 从 2023 年最后交易日开始回填，按 `(etf_code, trade_date, source_scope)` 幂等写入 SQLite；每日增量默认重取最近 5 个交易日以吸收迟发布/更正。
4. 所有请求记录 provider、函数或 URL、参数、抓取时间、响应行数、原始单位、标准单位、字段映射、校验摘要和错误信息。
5. 510310 的 2024 年 9 月份额合并必须作为经过来源核验的公司行为事件处理，不能通过普通异常波动规则自动修正。
6. 净申赎严格使用：

   $$\Delta S_{i,t}=S^{adj}_{i,t}-S^{adj}_{i,t-1}$$

   $$F_{i,t}(\text{亿元})=\frac{\Delta S_{i,t}(\text{万份})\times N^{adj}_{i,t}(\text{元/份})}{10000}$$

   不使用 AUM 差值替代该公式。

## 主要一手来源

- [AKShare MIT 许可证](https://github.com/akfamily/akshare/blob/main/LICENSE)
- [AKShare 公募基金/ETF 文档](https://github.com/akfamily/akshare/blob/main/docs/data/fund/fund_public.md)
- [digger-yu/etf LICENSE](https://github.com/digger-yu/etf/blob/main/LICENSE)
- [digger-yu/etf 日常抓取](https://github.com/digger-yu/etf/blob/main/scripts/fetch_data.py)
- [digger-yu/etf 历史回填](https://github.com/digger-yu/etf/blob/main/scripts/backfill_data.py)
- [zxtcc 深交所客户端](https://github.com/zxtcc/szse-etf-share/blob/main/src/szse_client.py)
- [steve849739 采集层](https://github.com/steve849739/Etf-tracker/blob/main/etf_fetch.py)

