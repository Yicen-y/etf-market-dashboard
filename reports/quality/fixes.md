# P0 数据可靠性修复记录

## 发现与修改

1. `scripts/fetch_data.py` 新增 `FetchResult`，统一携带 provider、上游、请求区间、采集时间、原始响应哈希和批次；ETF回退严格使用调用方增量起点；空响应在预期有交易日时阻断并触发回退；指数适配器从具名日期/收盘列读取，schema变化阻断。
2. `scripts/validate_data.py` 新增 ETF/指数有限正数、日期、标的身份、重复检查。`H20180/20130628=0` 保留在旧表，登记 `quality_issues`，从当前规范发布快照排除。
3. `scripts/prism_metrics.py` 修正缺失链、RSI14边界、平坦序列 RSI=50、40日交易日端点和242点窗口；每组策略均支持 Python 计算，前端优先读取 `strategyMetrics`。
4. `scripts/storage.py` 增加 `raw_observations`、`quality_issues`、`canonical_observations`、`release_manifest`、原始响应保存、SQLite双表事务和不可变 release 快照。
5. `scripts/update_data.py` 改为先采集/验证所有 ETF 和指数，再统一提交、生成派生指标和切换 manifest；冲突不再静默覆盖；历史来源迁移为 `PROVENANCE_UNKNOWN`，并显式纠正旧表误导性的 `source=akshare` 元数据，不改行情数值。
6. `server.py` 删除整个 `/data` 静态挂载，新增仅允许数据集的快照 API；`web/app.js` 首先取得 snapshot_id，再固定该版本读取 ETF 与指数。
7. `.github/workflows/daily-update.yml` 停用 GitHub Pages artifact/deploy；本地 FastAPI 仍是部署目标。
8. `scripts/dividend/service.py` 对未完整官方核验的股票分红返回 `null/INCOMPLETE`；空的已公告待派/预案不再显示 `0.0000%`。

## 测试

- 新增 `tests/test_reliability_p0.py`：坏点、有限性、增量起点、空响应、schema、来源、RSI、40日端点、SQLite回滚、JSON/manifest回滚。
- 新增静态数据暴露、snapshot pinning、Python策略对、股息不完整覆盖和空前瞻组测试。
- 全量 `python -m pytest -q`：131 passed，2 个既有 pandas 版本警告。
- `node --check web/app.js`、`node --check web/dividend.js`、`python -m compileall -q scripts server.py`：通过。

## 未决项

- 旧行情来源无法从原始旧表恢复；已标记未知，必须通过后续真实抓取补充 provider/upstream/raw hash。
- 线上数据源在当前代理环境不可稳定访问，未声称线上核验成功。
- H20180 官方点位和510310官方份额折算公告尚未取得，均保持阻断/限制状态。

## 2026-11-02 三棱镜交易日、历史缺口与预热修正

- 交易日改用交易所实际交易日历，不再用单一指数观测日代替市场日历。`2018-06-18` 为端午节休市日，已从三棱镜交易日索引排除；不对休市日插值或前值填充。
- 中证2000全收益指数 `932000CNY010` 以官方基日 `2013-12-31` 为有效历史起点。此前识别出的237个早期缺口均位于指数基日前，旧数据中的1000点占位值不再进入规范发布数据；加上休市日误报后，原238个缺口已全部正确分类。
- 中证银行全收益指数 `H20180` 的 `2013-06-28` 原始收盘值为0。依据下一实际交易日官方收盘值4303.64及当日涨跌额-20.35，按 `前收盘 = 当日收盘 - 当日涨跌额` 精确恢复为4303.99，并记录状态 `RECOVERED_FROM_NEXT_DAY_ABSOLUTE_CHANGE`；该修复不是插值或前值填充。
- 指标先使用完整历史序列计算，再将每组策略的发布序列从六项核心指标全部可用的首个交易日开始展示。40日、14日与242日窗口的正常预热仍被保留在计算过程中，但不再在页面形成误导性的开头空段；后续真实缺测仍保留为 `null`。
- 成长100R/价值100R及其余有充足早期历史的策略，指标展示起点为 `2014-03-10`；中证2000/沪深300因指数基日较晚，展示起点为 `2015-03-02`。
- 生成当前快照 `20261102T185729-290830d9`，公式版本为 `prism-v4-exchange-calendar`。审计确认目标指数自各自有效起点起缺失交易日均为0，所有已发布策略行的六项核心指标均非空。
