# V2 基线（2026-11-13）

工作树在开始前已有未提交代码、`data/etf_market.db`、原始归档和三份已删除的重复备份。均视为既有状态保留，不做重置或历史数据迁移。HEAD：`dd95f2105c0edf4d11bb7cdd4b5ad33e4a0a18d3`；Windows Python 3.9.13、Node 24.15.0。

基线命令 `python -m pytest -q`：388 passed、0 failed、0 skipped，两个本机 pandas 可选加速包版本警告。真实供应商网络未包含在离线测试中。此前在 WSL Python 3.11 跑过相同规模测试，但那不是本阶段的新基线运行。

| 模块/数据集 | 采集与实际上游 | 规范化存储/发布 | API 与页面 | 口径与共享依赖 |
|---|---|---|---|---|
| 三只 ETF 日收盘 | AkShare/东方财富首选；AkShare/新浪候选隔离 | `etf_prices`、Raw/Canonical、ETF JSON release | snapshot API、主看板、轮动总览 | 元/份，东方财富请求未复权；历史来源链接未知 |
| 指数日点位 | ETFirst；AkShare/中证等回退 | `index_prices`、Raw/Canonical、指数 JSON release | snapshot、轮动、五年之锚、红利研究 | 指数点位，各指数价格/全收益定义不同；交易日历共用 |
| ETF 份额/NAV/资金流 | 交易所份额、AkShare/东方财富 NAV 等 | SQLite fund_flow 表 | fund-flow API、资金流页 | 份额万份、净值元/份、净申购估算亿元；拆并份规则独立 |
| 股息/报价 | 公告、AkShare、Wind/ETFirst 等 | SQLite dividend 表及原始文档 | dividend API、股息页 | 每份/每股现金额、TTM、不同核验层级 |
| 五年之锚/股债/研究 | 指数快照、Wind 等 | SQLite 研究表及研究 JSON | anchor、bond-value、dividend-research API | 策略结果依赖上游日期和来源；不得把内部 PASS 当外部核验 |

已复核：旧 Windows Manifest 有兼容读取；发布使用 prepared 与 Manifest 原子指针；A/H 初始成本测试存在；主源失败会隔离新浪，当前上游网络仍可能不可用。待做：统一 Provider 契约、集中数据中心、持久化任务、`ETF_DATA_DIR`、代码/数据分离部署、固定浏览器测试体系。实施顺序遵循 V2 合同各阶段，所有真实历史金融数据不因本次改造删除。
