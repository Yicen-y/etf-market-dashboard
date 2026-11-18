# 数据契约与来源边界

| 数据集 | 标识/单位 | 当前存储与发布 | 来源及核验语义 |
|---|---|---|---|
| ETF 日收盘 | ETF 代码、交易日、元/份 | SQLite `etf_prices`、ETF release | AkShare 东方财富首选；新浪仅候选，对账前隔离；价格未复权，不能称总收益 |
| 指数日点位 | 指数代码、交易日、点 | SQLite `index_prices`、指数 release | ETFirst/既有指数适配器；每个指数价格/全收益口径须单独核实 |
| ETF 份额/资金流 | ETF、交易日、万份/亿元等 | SQLite fund flow 表 | 净申购为估算，不代表特定投资者买入 |
| 股息 | 证券/公告/除权日、每股或每份现金额 | SQLite dividend 表 | 缺失公告为未知，不能填 0；外部事实核验独立 |
| 股债估值 | 交易日、倍数/收益率 | 研究 JSON | 依赖指数与债券输入，当前来源核验未知 |

Raw Observation 保存上游返回表的序列化或文档，不必然是 HTTP 原始报文。新 Canonical 的 raw ID、批次、上游、摘要通过 `storage` 链接；无法追溯的历史记录标 UNKNOWN。`STRUCTURE_PASS` 只证明发布文件存在、哈希及必要字段通过，绝不代表真实市场价格正确。

ETF 收盘试点请求 `DataRequest` 明确 `ETF:SH:512530` 一类市场标识、`etf_daily_close`、日期区间、未复权价格、CNY、元/份和市场日历。Provider Adapter 返回保留实际上游的 `FetchResult`；`Sina` 返回成功仍要经过 `SourcePolicy` 与重叠历史对账，不由 Provider Manager 自动发布。指数、份额、股息、股债尚未全部接入此契约。

Manifest 路径只允许数据根目录内的相对路径。Reader 接受旧 `\\` 分隔符，拒绝绝对路径、盘符、`..` 与软链接越界。已发布文件不应原地修改，修改后 SHA 校验失败且 readiness 降级。

来源策略细节见 `scripts/source_policy.py` 和 `data/source_policy.json`（若配置）。缺乏明确复权定义、币种/单位、真实主源重叠记录及审查证据时，备源数据保持候选，旧已发布快照继续供图表读取。
