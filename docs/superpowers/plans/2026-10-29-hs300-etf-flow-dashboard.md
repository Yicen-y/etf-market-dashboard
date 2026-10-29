# 沪深300ETF资金流向监测看板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有本地 FastAPI ETF 看板中增加一个可离线运行、可审计、能够每日自动抓取官方公开数据并增量写入 SQLite 的“沪深300ETF资金流向监测看板”，优先完成份额曲线、估算净申赎计算、累计净申赎和每日净申赎三张 P0 核心图表。

**Architecture:** 沿用仓库现有的 FastAPI 本地服务、SQLite 和原生 JavaScript + ECharts 架构，不引入新的前端构建链或强制 Streamlit。资金流功能使用独立的 `scripts/fund_flow/` 领域模块和 `fund_flow_` 前缀数据库表，与现有 ETF 价格/指数策略表增量共存；网页通过 FastAPI API 读取已审核的清洗结果和质量状态。P0 的每日主路径是官方公开页面采集，CSV 用于首次历史回填、缺口补录和爬虫失败时的兜底，Tushare 作为拥有权限时可启用的可选适配器，不能成为应用启动依赖。

**Tech Stack:** Python 3.9+、FastAPI、SQLite、Pandas、Pydantic/dataclasses、ECharts、pytest、CSV、可选 Tushare Pro。

## Global Constraints

- P0 必须支持官方公开页面自动采集、最近交易日增量更新、CSV 上传/预览/验证后入库，以及无 Token 离线启动。
- P0 的“刷新数据”按钮必须抓取最近若干交易日并幂等写入 SQLite；不得要求用户每天手动上传 CSV。
- 所有真实行情数据必须携带来源、取得时间、数据单位、份额口径和状态；测试集只能使用明确标注为模拟的数据。
- 份额变化不得直接解释为“国家队交易”；页面统一使用“ETF资金流向 / 估算净申赎”。
- 份额合并、拆分和分红必须使用通用公司行为机制，不能为 510310 写一次性硬编码。
- 未核验的份额口径、缺失前一交易日、缺失 NAV、来源冲突或疑似公司行为必须返回 `WARNING` 或 `BLOCKED`，不得静默填零或跨日计算。
- 510310 的真实合并事件只作为带官方公告出处的初始化事件记录和回归测试依据，不添加虚构的日行情。
- 公式必须使用统一的“万份 / 元每份 / 亿元”计量单位，并在页面和 README 中显示。
- 保留现有 `etf_prices`、`index_prices` 和策略看板行为；新表采用 `fund_flow_` 前缀并通过增量迁移创建。
- API Token 只从环境变量或本地配置读取，禁止写入 CSV 样例、测试输出、日志或 Git。
- P0 完成后必须通过 T01—T10 自动化测试，并能使用没有网络和 Token 的模拟 CSV 启动页面。
- 爬虫只使用官方公开入口或得到许可的公开接口，遵守站点访问频率、robots/使用条款和正常 HTTP 行为；不绕过登录、验证码或访问限制。
- 爬虫失败时保留历史库和上次成功状态，不用空响应覆盖有效数据；每次采集保存 URL、抓取时间、响应校验值、字段映射和错误信息。

---

## 文件结构与职责

新增和修改文件按以下边界组织：

```text
etf-market-dashboard/
  app.py                                  # 可选兼容入口；若保留 server.py，则明确等价启动命令
  server.py                               # 注册资金流 API 和静态页面
  requirements.txt                        # pandas、pydantic 等新增依赖
  README.md                               # 安装、导入、公式、限制和测试结果
  docs/HS300_ETF_FLOW_METHOD.md           # 资金流口径、事件审核和来源说明
  data/
    etf_market.db                         # 复用现有数据库，新增 fund_flow_ 表
    samples/fund_flow_demo.csv            # 只含明确标记为模拟的数据
  scripts/fund_flow/
    __init__.py
    models.py                              # 数据模型、枚举和接口类型
    config.py                              # ETF 池、预设组合、单位和阈值配置
    db.py                                  # SQLite 增量 schema、事务和查询
    providers/base.py                     # ETFDataProvider Protocol
    providers/csv_provider.py             # CSV 解析、字段映射和单位标准化
    providers/sse_provider.py             # 上交所公开ETF规模页面适配器
    providers/szse_provider.py            # 深交所公开ETF数据页面适配器
    providers/nav_provider.py             # 独立单位净值数据适配器
    providers/announcement_provider.py   # 官方公告元数据和候选公司行为
    providers/tushare_provider.py         # 可选 Tushare Pro 适配器
    services/calendar.py                  # 交易日、日期缺口和窗口规则
    services/corporate_actions.py         # 通用折算/拆分/分红事件审核和复权
    services/quality.py                   # Q1-Q10 质量规则
    services/flows.py                     # DeltaS、F、累计、滚动和强度计算
    services/ingest.py                    # 导入预览、验证、提交和增量重算
    services/sync.py                      # 官方页面增量同步、重试和最近窗口重取
    services/export.py                    # 清洗明细和组合汇总 CSV 导出
  web/
    fund-flow.html                        # 独立资金流看板页面
    fund-flow.js                          # 筛选、导入、图表和导出交互
    fund-flow.css                         # 页面布局、状态颜色和提示样式
  tests/
    test_fund_flow_units.py
    test_fund_flow_calculations.py
    test_fund_flow_corporate_actions.py
    test_fund_flow_quality.py
    test_fund_flow_aggregate.py
    test_fund_flow_import.py
    test_fund_flow_api.py
    test_fund_flow_workflow.py
```

现有 `scripts/storage.py` 不直接扩展资金流业务逻辑；资金流模块通过 `scripts/fund_flow/db.py` 复用同一个 SQLite 文件，但所有 SQL 表名、模型和事务入口保持独立。

---

## Task 1: P0 数据模型、配置和 SQLite 增量 schema

**Files:**
- Create: `scripts/fund_flow/__init__.py`
- Create: `scripts/fund_flow/models.py`
- Create: `scripts/fund_flow/config.py`
- Create: `scripts/fund_flow/db.py`
- Modify: `scripts/config.py` only to expose the existing database path to the new module
- Test: `tests/test_fund_flow_units.py`

**Interfaces:**
- Produces `RawETFRecord`, `CleanETFRecord`, `DailyMetric`, `CorporateAction`, `QualityIssue`, `ImportJob` and typed status literals.
- Produces `init_fund_flow_schema(path: Path) -> None`, `open_fund_flow_connection(path: Path) -> sqlite3.Connection` and `seed_default_fund_master(path: Path) -> None`.
- `RawETFRecord` fields: `etf_code`, `record_date`, `effective_trade_date`, `published_at`, `total_share`, `share_unit`, `share_scope`, `share_date_basis`, `nav`, `close`, `total_size`, `source_id`, `source_version`, `import_batch_id`.
- `CleanETFRecord` fields: `etf_code`, `trade_date`, `shares_wan`, `nav`, `size_yi`, `share_scope`, `validation_status`, `error_codes`, `source_id`.
- `DailyMetric` fields: `etf_code`, `trade_date`, `shares_adj_wan`, `nav_adj`, `delta_shares_wan`, `net_flow_yi`, `cum_flow_yi`, `intensity_pct`, `calc_version`, `status`.

- [ ] **Step 1: Write unit tests for model validation and schema idempotency.**

```python
def test_schema_can_be_initialized_twice(tmp_path):
    db_path = tmp_path / "etf_market.db"
    init_fund_flow_schema(db_path)
    init_fund_flow_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert "fund_master" in names
    assert "fund_flow_etf_daily_raw" in names
    assert "fund_flow_etf_daily_metrics" in names
```

- [ ] **Step 2: Run the focused test and verify it fails because the new models/schema do not exist.**

Run: `python -m pytest tests/test_fund_flow_units.py -q`

Expected: FAIL with an import or missing-table error.

- [ ] **Step 3: Implement the models and additive schema.**

The schema must include `fund_master`, `fund_flow_etf_daily_raw`, `fund_flow_index_daily_raw`, `fund_flow_corporate_actions`, `fund_flow_etf_daily_clean`, `fund_flow_etf_daily_metrics`, `fund_flow_data_sources` and `fund_flow_import_jobs`. Raw rows are versioned by `import_batch_id`; clean rows have a unique key on `(etf_code, trade_date, share_scope)`; metric rows have a unique key on `(etf_code, trade_date, calc_version)`.

The initial master data must contain the six configured ETFs:

```python
ETF_UNIVERSE = {
    "510300.SH": {"name": "华泰柏瑞沪深300ETF", "group": "core"},
    "510310.SH": {"name": "易方达沪深300ETF", "group": "core"},
    "510330.SH": {"name": "华夏沪深300ETF", "group": "core"},
    "159919.SZ": {"name": "嘉实沪深300ETF", "group": "core"},
    "510320.SH": {"name": "中金沪深300ETF", "group": "extended"},
    "510350.SH": {"name": "工银瑞信沪深300ETF", "group": "extended"},
}
```

Preset groups must be `original_shanghai_five`, `core_four` and `all_six`. `original_shanghai_five` must contain `510300.SH`, `510310.SH`, `510320.SH`, `510330.SH`, `510350.SH`.

- [ ] **Step 4: Run the focused test and the existing test suite.**

Run: `python -m pytest tests/test_fund_flow_units.py tests/test_data_contract.py -q`

Expected: the new tests and all existing tests pass.

- [ ] **Step 5: Commit the schema boundary.**

```cmd
git add scripts/fund_flow tests/test_fund_flow_units.py scripts/config.py
git commit -m "feat: add ETF fund flow data model"
```

---

## Task 2: AKShare 官方份额采集、独立 NAV、CSV 回填和增量同步

**Files:**
- Create: `scripts/fund_flow/providers/base.py`
- Create: `scripts/fund_flow/providers/csv_provider.py`
- Create: `scripts/fund_flow/providers/sse_provider.py`
- Create: `scripts/fund_flow/providers/szse_provider.py`
- Create: `scripts/fund_flow/providers/nav_provider.py`
- Create: `scripts/fund_flow/providers/tushare_provider.py`
- Create: `scripts/fund_flow/services/ingest.py`
- Create: `scripts/fund_flow/services/sync.py`
- Create: `data/samples/fund_flow_demo.csv`
- Create: `.env.example` additions for `TUSHARE_TOKEN`, `FUND_FLOW_HTTP_TIMEOUT`, `FUND_FLOW_RETRY_COUNT`
- Test: `tests/test_fund_flow_import.py`
- Test: `tests/test_fund_flow_providers.py`
- Test: `tests/test_fund_flow_sync.py`

**审查结论与复用边界：**
- AKShare 是 MIT 许可的公共数据工具库；本项目通过已发布包调用接口，不复制其内部实现。
- `digger-yu/etf` 是 MIT 许可，可复用其“按日抓取、深交所窗口回填、分层脚本”的设计；但其聚合结果和 AUM 字段不直接作为本项目的净申赎结果，所有接口输出必须经过字段、单位和日期核验。
- `zxtcc/szse-etf-share` 未发现许可证文件，只参考其对深交所单日/窗口接口、分页、重试和去重的观察，不复制代码。
- `steve849739/Etf-tracker` 未发现许可证文件，只参考其采集、更新、展示分层，不复制代码。所有实际数据必须来自可追溯的公开来源。

**Interfaces:**
- `class ShareProvider(Protocol): fetch(codes: list[str], start: date, end: date) -> list[RawETFRecord]`，返回原始份额、单位、日期口径、来源 URL、抓取时间和响应校验值。
- `class NavProvider(Protocol): fetch_nav(codes: list[str], start: date, end: date) -> list[RawNAVRecord]`，必须与份额接口独立，返回单位净值元/份和来源元数据。
- `AkshareSSEProvider.fetch(...)` 调用 AKShare 的 `fund_etf_scale_sse(date=YYYYMMDD)`，核验 `基金代码`、`基金份额` 字段及其万份口径。
- `AkshareSZSEProvider.fetch(...)` 调用 AKShare 的 `fund_scale_daily_szse(start_date=..., end_date=..., symbol="ETF")`，按不超过接口窗口的区间回填，并核验分页、日期和万份口径。
- `parse_csv(file: BinaryIO, source_id: str) -> ImportPreview` 只预览不写库；`commit_import(preview, db_path) -> ImportJob` 在事务中提交。
- `sync_recent(db_path, provider_chain, start, end, retry_policy) -> SyncReport`：按“AKShare 份额 → 独立 NAV → 官方公告/页面核验 → CSV/可选 Tushare 兜底”的顺序执行；失败时保留上次成功数据。

- [ ] **Step 1: Write provider contract tests before implementation.**

测试用 monkeypatch 模拟 AKShare 返回的数据，不调用真实行情网络；覆盖：SSE/SZSE 字段映射、万份单位、日期规范化、空值保留、接口异常重试、重复行、来源元数据、独立 NAV 关联。

```python
def test_akshare_sse_maps_share_units_and_source(monkeypatch):
    monkeypatch.setattr(
        ak, "fund_etf_scale_sse",
        lambda date: pd.DataFrame([{"基金代码": "510300", "基金简称": "沪深300ETF", "基金份额": "123,456.78"}]),
    )
    rows = AkshareSSEProvider().fetch(["510300.SH"], date(2024, 1, 2), date(2024, 1, 2))
    assert rows[0].total_share == pytest.approx(123456.78)
    assert rows[0].share_unit == "万份"
    assert rows[0].source_id.startswith("akshare:sse")


def test_sync_never_uses_aum_delta_as_flow(nav_rows, nav_rows_current):
    report = sync_recent(...)
    assert report.metrics[0].net_flow_yi == pytest.approx(
        (nav_rows_current[0].shares_wan - nav_rows[0].shares_wan)
        * nav_rows_current[0].nav / 10000
    )
```

- [ ] **Step 2: Run focused tests and verify they fail before implementation.**

Run: `python -m pytest tests/test_fund_flow_providers.py tests/test_fund_flow_sync.py -q`

Expected: FAIL because the provider chain and sync service do not exist.

- [ ] **Step 3: Implement AKShare primary providers.**

Use the verified public AKShare functions only. SSE history is requested one trading day at a time; SZSE history is requested in provider-safe windows (maximum 6 calendar months, implemented with 180-day chunks), with explicit retry/backoff and a small request interval. Skip weekends only as an optimization; the returned exchange rows remain authoritative. Never silently convert an empty response into zero shares.

The provider must normalize exchange code to `510300.SH` / `159919.SZ`, normalize date to `YYYY-MM-DD`, and normalize shares to `万份` only after applying an exchange-specific source-unit mapping. The mapping is tested against documented examples and range checks: SSE `基金份额` is treated as the source unit documented by the SSE/AKShare adapter; SZSE `基金份额` is treated as raw shares where the AKShare daily example is in shares. If a future AKShare version changes the unit or column type, the provider fails visibly and creates a `BLOCKED` issue instead of silently dividing/multiplying. Preserve raw values and record the exact AKShare function, request parameters, source-unit mapping, response row count, retrieval time, and checksum in `fund_flow_data_sources`.

- [ ] **Step 4: Implement an independent NAV provider.**

Use a separately named adapter and source metadata for historical daily NAV. It may use a stable AKShare NAV/history endpoint or a separately configured official/public fund-data endpoint after field-level verification. Do not derive NAV from AUM/shares unless the source explicitly identifies it as unit NAV. If NAV is unavailable or conflicts with an independently retrieved value, persist the row with `WARNING`/`BLOCKED`; do not calculate flow with zero or with total asset size.

- [ ] **Step 5: Implement complete history backfill and daily incremental sync.**

The default start date is the last trading day of 2023, resolved from the exchange calendar. Backfill through today for every configured ETF; daily sync re-fetches a recent overlap window (default 5 trading days) to repair late-published/corrected rows and then upserts by `(etf_code, trade_date, source_scope)`. All writes are idempotent and transactional. A failed provider cannot delete or overwrite the last successful clean record.

Provide both a CLI and a service entry point:

```cmd
python -m scripts.fund_flow_sync --backfill --start 2023-12-29
python -m scripts.fund_flow_sync --incremental --overlap-days 5
```

The web refresh button will call the same service rather than implement a second data path. A local Windows Task Scheduler recipe is documented later, but is not required for offline tests.

- [ ] **Step 6: Implement CSV fallback and optional Tushare adapter.**

Accept `YYYY-MM-DD` and `YYYYMMDD`; accept source units `份`, `万份`, `亿份`; normalize shares to `万份`; accept `万元` and `亿元` for asset size and normalize to `亿元`; accept scopes `on_exchange`, `total_fund`, `unknown`; accept bases `pre_open`, `post_close`, `unknown`. Reject unknown units, non-positive NAV, invalid dates and missing `ts_code` instead of treating them as zero.

The sample CSV must contain only rows with a `SIMULATED` source marker and dates outside the real analysis window, for example `2099-01-04`; its README comment must state that it is not market data. Tushare maps `etf_share_size` only when the user explicitly chooses it and has permission; it never becomes a startup dependency or a hidden fallback.

- [ ] **Step 7: Run tests and commit the acquisition boundary.**

Run: `python -m pytest tests/test_fund_flow_import.py tests/test_fund_flow_providers.py tests/test_fund_flow_sync.py -q`

Expected: all provider/import/sync tests pass without network access, without a Token, and without real market fixtures.

```cmd
git add scripts/fund_flow/providers scripts/fund_flow/services/ingest.py scripts/fund_flow/services/sync.py scripts/fund_flow_sync.py data/samples .env.example tests/test_fund_flow_import.py tests/test_fund_flow_providers.py tests/test_fund_flow_sync.py
git commit -m "feat: add official ETF share sync providers"
```

---

## Task 3: 公司行为事件、510310 合并处理和日期口径

**Files:**
- Create: `scripts/fund_flow/services/calendar.py`
- Create: `scripts/fund_flow/services/corporate_actions.py`
- Create: `data/source_events/510310_consolidation.json`
- Test: `tests/test_fund_flow_corporate_actions.py`

**Interfaces:**
- `resolve_previous_trading_date(rows: Sequence[CleanETFRecord], trade_date: date) -> date | None`.
- `validate_corporate_action(action: CorporateAction) -> list[QualityIssue]`.
- `apply_share_unit_adjustment(rows: Sequence[RawETFRecord], actions: Sequence[CorporateAction]) -> list[CleanETFRecord]`.
- `detect_candidate_actions(rows: Sequence[RawETFRecord], share_jump_threshold: float = 0.10) -> list[CorporateAction]` returns `discovered` candidates only.
- `action.status` values are exactly `discovered`, `source_verified`, `basis_verified`, `applied`, `rejected`.

- [ ] **Step 1: Write tests for a simulated 2-to-1 consolidation and unverified 510310 behavior.**

```python
def test_two_for_one_consolidation_does_not_create_flow():
    rows = simulated_rows(before_shares_wan=100, before_nav=2, after_shares_wan=50, after_nav=4)
    action = CorporateAction(
        etf_code="510310.SH", action_type="consolidation", event_date=date(2024, 1, 2),
        ex_date=date(2024, 1, 3), ratio=0.5,
        first_post_record_date=date(2024, 1, 3), status="basis_verified",
    )
    cleaned = apply_share_unit_adjustment(rows, [action])
    assert cleaned[1].shares_wan == 50
    assert cleaned[0].nav == 4
    assert cleaned[1].delta_shares_wan == 0


def test_510310_without_first_post_record_date_is_blocked():
    action = load_seed_action("510310_consolidation")
    assert action.ratio == 0.49977589
    assert action.status == "source_verified"
    assert "corporate_action_unverified" in validate_corporate_action(action)[0].error_codes
```

- [ ] **Step 2: Run focused tests and verify failure before implementation.**

Run: `python -m pytest tests/test_fund_flow_corporate_actions.py -q`

Expected: FAIL because event application and validation are not implemented.

- [ ] **Step 3: Implement the generic adjustment rule.**

For a verified event with `r = new shares / old shares`, adjust all pre-event rows to the post-event unit:

```text
S_adj[t] = S_raw[t] * r
N_adj[t] = N_raw[t] / r
```

Keep post-event rows unchanged. Apply multiple verified events in chronological order. Never adjust only shares, never apply an event twice, never treat cash dividends as share actions, and never apply an action with `first_post_record_date` missing or status below `basis_verified`.

- [ ] **Step 4: Seed the 510310 event metadata without quote data.**

Store the official announcement URL, title, page range, event date `2024-09-20`, next-workday date `2024-09-23`, ratio `0.49977589`, pre/post shares and NAV from the project specification, and status `source_verified`. Leave `first_post_record_date` unset until the source-record basis is verified; affected metrics must be `BLOCKED`. The JSON file contains source evidence only, not fabricated market history.

- [ ] **Step 5: Implement candidate detection and explicit review state.**

Use the configured 10% share-jump candidate rule and inverse NAV check only to create `discovered` warnings. A candidate cannot automatically become `basis_verified` or `applied`.

- [ ] **Step 6: Run tests and commit.**

Run: `python -m pytest tests/test_fund_flow_corporate_actions.py -q`

Expected: T02 and T03 pass, including the blocked state for an unverified first post-record date.

```cmd
git add scripts/fund_flow/services/calendar.py scripts/fund_flow/services/corporate_actions.py data/source_events tests/test_fund_flow_corporate_actions.py
git commit -m "feat: add auditable ETF corporate actions"
```

---

## Task 4: 清洗、质量规则和资金流计算引擎

**Files:**
- Create: `scripts/fund_flow/services/quality.py`
- Create: `scripts/fund_flow/services/flows.py`
- Test: `tests/test_fund_flow_calculations.py`
- Test: `tests/test_fund_flow_quality.py`
- Test: `tests/test_fund_flow_aggregate.py`

**Interfaces:**
- `validate_daily_records(rows: Sequence[CleanETFRecord]) -> list[QualityIssue]` implements Q1-Q10 with `PASS`, `WARNING`, `BLOCKED`.
- `calculate_daily_metric(current: CleanETFRecord, previous: CleanETFRecord | None, status: str) -> DailyMetric`.
- `calculate_series(rows: Sequence[CleanETFRecord], actions: Sequence[CorporateAction], start: date, end: date) -> list[DailyMetric]`.
- `aggregate_selected_etfs(metrics: Sequence[DailyMetric], selected_codes: list[str], start: date, end: date) -> list[dict]` calculates each ETF first, then sums money values.
- `calculate_rolling_flow(metrics: Sequence[DailyMetric], window: int) -> float | None` returns `None` when the window is incomplete.
- `calculate_intensity(flow_yi: float, previous_size_yi: float | None) -> float | None` returns `None` for missing or zero denominator.

- [ ] **Step 1: Write T01, T04, T05, T06, T07 and T09 calculation tests.**

```python
def test_daily_flow_uses_wan_shares_and_nav():
    previous = clean("510300.SH", "2024-01-02", shares_wan=100, nav=4)
    current = clean("510300.SH", "2024-01-03", shares_wan=110, nav=4)
    metric = calculate_daily_metric(current, previous, "PASS")
    assert metric.delta_shares_wan == 10
    assert metric.net_flow_yi == pytest.approx(0.004)


def test_missing_nav_blocks_flow_without_zero_fill():
    current = clean("510300.SH", "2024-01-03", shares_wan=110, nav=None)
    metric = calculate_daily_metric(current, previous, "BLOCKED")
    assert metric.net_flow_yi is None
    assert metric.status == "BLOCKED"


def test_multi_etf_aggregate_sums_money_not_shares():
    result = aggregate_selected_etfs(metrics, ["510300.SH", "510310.SH"], start, end)
    assert result[0]["net_flow_yi"] == pytest.approx(0.004 + 0.012)
    assert result[0]["coverage_codes"] == ["510300.SH", "510310.SH"]
```

- [ ] **Step 2: Run focused tests and verify they fail.**

Run: `python -m pytest tests/test_fund_flow_calculations.py tests/test_fund_flow_quality.py tests/test_fund_flow_aggregate.py -q`

Expected: FAIL because the calculation services are not implemented.

- [ ] **Step 3: Implement the exact metric formulas.**

Use only same-scope, same-unit, valid adjacent trading-day rows:

```text
DeltaS[i,t] = S_adj[i,t] - S_adj[i,prev_trading_day]
F[i,t] = DeltaS[i,t] * N_adj[i,t] / 10000
Intensity[i,t] = F[i,t] / A[i,prev_trading_day] * 100
```

If the previous effective trading-day row is absent, set `delta_shares_wan`, `net_flow_yi` and dependent cumulative values to `None` with `missing_previous_day`. If any selected ETF is missing on a combination date, the default aggregate is `incomplete` and includes `coverage_ratio`, `coverage_codes`, `missing_codes`; it is not treated as zero.

- [ ] **Step 4: Implement cumulative and rolling windows.**

Set the 2023 final trading day cumulative base to zero. Calculate the first 2024 trading-day flow from the 2023 final trading-day shares. Cumulative values stop or become unavailable across blocked gaps. Rolling 5/20/60-day values require a complete window and are otherwise `None`.

- [ ] **Step 5: Implement Q1-Q10 quality checks.**

Persist every issue with `rule_id`, ETF code, trade date, observed value, threshold, source ID, action, and review note. Q1, Q3, Q4, Q5, Q6, Q7 and Q9 block affected calculations; Q2, Q8 and Q10 warn unless the scope/date basis is unresolved, in which case they block the affected aggregate.

- [ ] **Step 6: Run all calculation tests and commit.**

Run: `python -m pytest tests/test_fund_flow_calculations.py tests/test_fund_flow_quality.py tests/test_fund_flow_aggregate.py -q`

Expected: T01, T04, T05, T06, T07, T08, T09 and the quality rules pass.

```cmd
git add scripts/fund_flow/services/quality.py scripts/fund_flow/services/flows.py tests/test_fund_flow_calculations.py tests/test_fund_flow_quality.py tests/test_fund_flow_aggregate.py
git commit -m "feat: calculate audited ETF net subscriptions"
```

---

## Task 5: 导入、同步、质量、查询和 CSV 导出 API

**Files:**
- Create: `scripts/fund_flow/services/export.py`
- Create: `scripts/fund_flow/api.py`
- Modify: `scripts/fund_flow/services/sync.py` only to expose the API-safe sync report
- Modify: `server.py`
- Test: `tests/test_fund_flow_api.py`

**Interfaces:**
- `GET /api/fund-flow/overview?preset=core_four&start=2024-01-01&end=latest`
- `GET /api/fund-flow/series?codes=510300.SH,510310.SH&start=...&end=...&frequency=daily`
- `GET /api/fund-flow/quality?start=...&end=...`
- `POST /api/fund-flow/import/preview` accepts a multipart CSV and returns row count, field mapping, warnings and errors without writing.
- `POST /api/fund-flow/import/commit` accepts a validated import batch ID and writes raw/clean/metric rows transactionally.
- `POST /api/fund-flow/sync` starts an idempotent recent-window sync using the same AKShare-first provider chain as the CLI; it returns provider status, latest date, inserted/updated counts and quality issues.
- `GET /api/fund-flow/export/clean.csv?...` and `GET /api/fund-flow/export/summary.csv?...`
- `GET /api/fund-flow/health` returns data counts, latest trade date, source status and blocked issue count.

- [ ] **Step 1: Write API contract tests.**

```python
def test_fund_flow_health_is_available(client):
    response = client.get("/api/fund-flow/health")
    assert response.status_code == 200
    assert {"latestTradeDate", "qualityState", "dataExists"}.issubset(response.json())


def test_import_preview_does_not_write(client, simulated_csv):
    response = client.post(
        "/api/fund-flow/import/preview",
        files={"file": ("demo.csv", simulated_csv, "text/csv")},
    )
    assert response.status_code == 200
    assert response.json()["committed"] is False
```

- [ ] **Step 2: Run API tests and verify they fail.**

Run: `python -m pytest tests/test_fund_flow_api.py -q`

Expected: FAIL because routes are not registered.

- [ ] **Step 3: Implement read-only overview/series/quality endpoints.**

Support presets and arbitrary ETF selection. For weekly/monthly views, aggregate daily flow by summing daily `net_flow_yi`; do not compute a month-end share difference times a single NAV. Return `status`, `qualityIssues`, `coverageRatio` and `source` alongside every series.

- [ ] **Step 4: Implement preview, commit and export endpoints.**

Preview must not mutate SQLite. Commit must re-read the preview batch, refuse unvalidated batches, write in a transaction, and recalculate only affected dates plus the recent re-fetch window. Export must include raw/adjusted shares, NAV, delta shares, flow, cumulative flow, status, source ID, action ID and calculation version.

- [ ] **Step 5: Implement the refresh endpoint with failure-safe semantics.**

The endpoint must reuse `sync_recent`, reject concurrent syncs with a visible `409`/busy state, return partial provider failures as structured warnings, and never replace valid historical rows with an empty provider response. The UI must show “刷新中 / 完成 / 部分失败” and the last successful update time.

- [ ] **Step 6: Run API and existing server tests.**

Run: `python -m pytest tests/test_fund_flow_api.py tests/test_server.py -q`

Expected: all new routes and old routes pass without changing existing strategy dashboard contracts.

```cmd
git add scripts/fund_flow/services/export.py scripts/fund_flow/api.py server.py tests/test_fund_flow_api.py
git commit -m "feat: expose ETF fund flow APIs"
```

---

## Task 6: P0 资金流看板页面和三张核心图表

**Files:**
- Create: `web/fund-flow.html`
- Create: `web/fund-flow.js`
- Create: `web/fund-flow.css`
- Modify: `web/index.html` to add a visible “沪深300 ETF资金流向” entry
- Test: `tests/test_fund_flow_workflow.py`

**Interfaces:**
- `fund-flow.html` consumes `/api/fund-flow/overview`, `/api/fund-flow/series`, `/api/fund-flow/quality` and `/api/fund-flow/export/*`.
- `fund-flow.js` exposes `loadOverview()`, `loadSeries()`, `renderSharesChart()`, `renderCumulativeFlowChart()`, `renderDailyFlowChart()`, `renderQualityState()` and `downloadCsv()`.
- The page uses the existing ECharts asset and does not require a frontend build step.

- [ ] **Step 1: Write static contract tests for the page and workflow.**

```python
def test_fund_flow_page_has_three_p0_chart_containers(client):
    html = client.get("/web/fund-flow.html").text
    assert "shares-chart" in html
    assert "cumulative-flow-chart" in html
    assert "daily-flow-chart" in html
    assert "估算净申赎" in html


def test_workflow_does_not_require_real_market_fixture():
    sample = Path("data/samples/fund_flow_demo.csv").read_text(encoding="utf-8")
    assert "SIMULATED" in sample
```

- [ ] **Step 2: Run the page contract test and verify it fails.**

Run: `python -m pytest tests/test_fund_flow_workflow.py -q`

Expected: FAIL because the page and link do not exist.

- [ ] **Step 3: Implement the page shell and controls.**

The top area must show latest trade date, last update time, quality state, selected preset, selected ETF names, latest daily flow, 5/20/60-day flow, cumulative flow since the 2024 first trading day, coverage ratio and blocked issue count. Controls must include the three presets, arbitrary ETF checkboxes, date range, daily/weekly/monthly frequency, a “刷新全部数据” button calling `/api/fund-flow/sync`, CSV preview/commit, and clean/summary export. The refresh result must identify whether AKShare, independent NAV, official verification and fallback providers succeeded.

- [ ] **Step 4: Implement G1 ETF shares history.**

Render each selected ETF as an independent line in `万份`; provide a toggle between raw and adjusted units; mark verified corporate action dates; on hover show raw shares, adjusted shares, NAV, source and status. Do not add together different ETF share counts in the overview.

- [ ] **Step 5: Implement G2 cumulative estimated net subscriptions.**

Render the selected combination’s `C[t]` from zero at the 2023 base and from the first 2024 trading day in the selected window. Include optional per-ETF contribution lines. Display `BLOCKED`/`INCOMPLETE` gaps visually and in the tooltip instead of joining them as normal numbers.

- [ ] **Step 6: Implement G3 daily flow bars and rolling totals.**

Render daily `F_total[t]` as positive/negative bars and optional 5/20/60-day rolling lines. Use Chinese market color convention only for financial meaning: red for positive net subscription/profit-like increase and green for negative net redemption; use a neutral color for `NA` or blocked states. The legend and tooltip must say “估算净申赎”，not “国家队买入/卖出”。

- [ ] **Step 7: Add data management and audit sections.**

Show import preview, source URLs, raw/clean counts, missing dates, duplicate/conflict issues, unresolved corporate actions and the definition warning that daily ETF shares cannot identify institution identity. Add a link to `docs/HS300_ETF_FLOW_METHOD.md`.

- [ ] **Step 8: Run page/API tests and commit.**

Run: `python -m pytest tests/test_fund_flow_workflow.py tests/test_fund_flow_api.py tests/test_server.py -q`

Expected: P0 page contracts pass and the existing dashboard remains available at `/web/`.

```cmd
git add web/fund-flow.html web/fund-flow.js web/fund-flow.css web/index.html tests/test_fund_flow_workflow.py
git commit -m "feat: add ETF fund flow P0 dashboard"
```

---

## Task 7: README、方法文档、离线运行和完整验收

**Files:**
- Create: `docs/HS300_ETF_FLOW_METHOD.md`
- Modify: `README.md`
- Modify: `requirements.txt`
- Modify: `.github/workflows/daily-update.yml` only if a separate future sync workflow is explicitly enabled; P0 local mode must not depend on it
- Test: all `tests/test_fund_flow_*.py` and existing tests

**Interfaces:**
- Documentation must define CSV template, database tables, formulas, event status, quality states, sources, evidence limits, and local commands.
- Documentation must include `docs/research/2026-10-29-etf-data-reference-projects.md` as the audit record for the four reference projects, including license status and API reuse decisions.
- The README must distinguish implemented P0, planned P1 and planned P2; it must not claim that unimported real market data has been reproduced.

- [ ] **Step 1: Write documentation acceptance checks.**

```python
def test_method_document_mentions_units_and_limits():
    text = Path("docs/HS300_ETF_FLOW_METHOD.md").read_text(encoding="utf-8")
    assert "DeltaS" in text
    assert "亿元" in text
    assert "不能识别国家队" in text
    assert "510310" in text
```

- [ ] **Step 2: Implement documentation and dependency updates.**

README commands must work from the repository root:

```cmd
python -m pip install -r requirements.txt
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

The document must also describe the first-run and daily paths:

```cmd
python -m scripts.fund_flow_sync --backfill --start 2023-12-29
python -m scripts.fund_flow_sync --incremental --overlap-days 5
```

Then open `http://127.0.0.1:8000/web/fund-flow.html` and use “刷新全部数据” for the same incremental service path. The README must include a Windows Task Scheduler example that runs the incremental command after the expected exchange publication time, while stating that the UI button remains the manual recovery path. It must describe CSV import as the no-network/history-gap path and Tushare as optional. The sample data section must state `SIMULATED` and must not present its values as real market data.

- [ ] **Step 3: Run the full test suite and the manual offline smoke test.**

Run:

```cmd
python -m pytest -q
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Expected:

- T01—T10 pass;
- the server starts without `TUSHARE_TOKEN`;
- the existing `/web/` strategy dashboard remains usable;
- the new `/web/fund-flow.html` loads with zero or simulated rows;
- provider failure leaves the previous successful rows intact and exposes a structured warning;
- the refresh endpoint and CLI use the same sync service and are idempotent;
- previewing a CSV does not write before commit;
- after committing a simulated CSV, G1/G2/G3 show only the supplied rows and quality status;
- no API key or fabricated real quote appears in the repository.

- [ ] **Step 4: Commit the complete P0 documentation and dependency state.**

```cmd
git add README.md docs/HS300_ETF_FLOW_METHOD.md requirements.txt tests
git commit -m "docs: document ETF fund flow P0"
```

---

## P1/P2 后续路线（不纳入本次 P0 验收）

### P1

- Tushare permission-enabled cross-check and additional recent-window fallback;
- independent official-page cross-check beyond the AKShare wrapper;
- G4 沪深300指数与申赎双轴对照；
- G5 申赎强度比较；
- 增量重算日志、季度份额对账和缺口预警。

### P2

- `fund_holder_reports` 持有人披露表和正式年报/中报证据录入；
- G6 国家队持仓披露证据图表；
- 自动发现疑似公司行为并进入人工审核队列；
- 定时任务、消息通知、备份和部署。

这些扩展不得改变 P0 的净申赎公式、公司行为审核状态和“不能从日频份额识别国家队身份”的展示约束。

## Self-review checklist

- 需求覆盖：P0 AKShare 优先份额采集、2023 年末起历史回填、每日增量、SQLite 去重、独立 NAV、份额合并、净申赎、G1/G2/G3、质量状态、导出和 T01—T10 均有对应任务。
- 参考项目审查：四个项目均有明确的 API/实现/许可证结论；无许可证的项目只作设计参考，不复制代码；MIT 项目也只复用经过本项目测试验证的思路或接口。
- 真实数据约束：示例数据明确为 `SIMULATED`；510310 只保存官方事件证据，不写入虚构行情。
- 口径一致：份额使用万份、NAV 使用元/份、资金流使用亿元；每只 ETF 先算金额再聚合。
- 失败安全：缺失、冲突、未核验事件和跨日缺口返回 `None`/`BLOCKED`，不会静默填零。
- 来源可审计：每次请求记录 provider、函数/URL、参数、抓取时间、响应校验值、字段映射和错误；AKShare 份额与独立 NAV 不混为同一来源。
- 现有项目兼容：新表使用 `fund_flow_` 前缀，新页面和 API 独立，现有策略路由及测试继续运行。
- 计划无未定义接口：各任务已声明输入、输出、文件和测试命令，可按任务顺序执行。
