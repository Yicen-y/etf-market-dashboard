# ETF Market Dashboard 数据质量合同

本合同适用于本地 FastAPI + SQLite 看板。任何行情、指数、分红或资金流指标只能使用通过质量门禁的规范记录；原始记录只追加、不删除、不静默覆盖。

## 记录层级

| 层 | 主要字段 | 用途 |
|---|---|---|
| `raw_observations` | `symbol`, `kind`, `trade_date`, `value_raw`, `unit_raw`, `provider`, `upstream_publisher`, `fetched_at`, `raw_sha256`, `fetch_batch_id`, `source_version` | 保留上游原始事实和来源；历史来源不可还原时使用 `PROVENANCE_UNKNOWN`。 |
| `quality_issues` | `issue_code`, `severity`, `raw_record_id`, `resolution_status` | 记录零值、非有限值、日期、重复冲突和来源问题。 |
| `canonical_observations` | `normalized_value`, `normalized_unit`, `selected_raw_id`, `quality_status`, `batch_id` | 仅质量门禁通过的记录进入指标计算。 |
| `release_manifest` | `snapshot_id`, `status`, `provider_summary`, `raw_hashes`, `formula_version`, `published_at` | 发布版本指针；前端同一次加载固定一个 `snapshot_id`。 |

## 允许使用的状态

- `PASS`：值为有限正数、日期和标的身份合法、没有未解决冲突。
- `WARNING`：存在需要复核但不阻断展示的异常，例如单日极端变动候选。
- `BLOCKED`：零值、负值、NaN、Infinity、未知字段、冲突、来源不足或缺少必要端点；不得进入指标。
- `INCOMPLETE`：数据存在但覆盖或组成不满足公式要求；API 返回 `null` 和原因，不能用零替代。

## 行情和指数

- ETF价格和指数点位必须是 `finite(value) and value > 0`。
- 交易日采用 `YYYYMMDD`，标的代码必须属于本次请求的 universe。
- 同标的、同日期、同版本的不同值进入冲突审计，禁止 `dict.update` 静默覆盖。
- 指数适配器只接受已知具名日期列和收盘列；列名/schema变化即阻断。
- `H20180/20130628=0` 保留在历史表并登记 `LEGACY_INVALID_OBSERVATION`，不进入规范发布数据或任何指标窗口。

## 轮动指标

- A/B 先按同一真实交易日对齐。
- 40日收益差要求当天和准确的 40 个交易日端点；区间有缺失时返回 `null`。
- RSI14 需要连续 14 个有效变化；中间缺失会重建初始化序列。增益、损失均为零时 RSI=50，仅损失为零且增益为正时 RSI=100。
- MA242/布林带要求 242 个合规比值点，缺一即 `null`。
- Python 计算指标并写入发布快照；JavaScript 只读取快照并展示。

## 分红和资金流

- 分红现金统一保存为 `Decimal` 的元/份；`PER_10` 必须除以 10。
- TTM 使用观察日前 365 个自然日内实际除息的税前现金事件、未复权价格和可追溯公告版本。完整事件覆盖未核验时 `value_pct=null`。
- 资金流仅称“估算净申赎”：`Δ调整后份额 × 当日NAV`，不得解释为交易成交资金或国家队买卖。
- 份额单位、官方统计日、NAV日和公司行为比例必须明确；组合缺成员时合计为 `null/INCOMPLETE`。

## 发布流程

`collect → validate → reconcile → calculate → stage → SQLite transaction → publish current_manifest`

ETF、指数和衍生指标先写入 `data/releases/<snapshot_id>/`，最后只用 `os.replace()` 切换 `data/current_manifest.json`。采集、校验、SQLite或JSON失败时，旧 manifest 不变，旧页面仍可用。

## 服务暴露

HTTP 不再静态挂载整个 `data/` 目录。前端只能通过 `/api/snapshot` 和 `/api/snapshot/data/{dataset_name}` 读取允许的数据集；SQLite、公告、备份和原始文件没有静态URL。
