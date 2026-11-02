# 沪深300 ETF 资金流向监测看板

## 目标与边界

本看板监测 ETF 份额变化对应的“估算净申赎”，不是把规模变化直接当作资金流，也不把份额变化自动解释为国家队或某一类投资者行为。网页可以在没有 Token 的情况下启动；刷新时优先调用 AKShare 的公开交易所适配器，独立获取单位净值，失败时保留已有历史并显示质量提示。

当前 P0 覆盖六只 ETF：510300.SH、510310.SH、510330.SH、159919.SZ、510320.SH、510350.SH。默认组合为核心四只，也支持原上海五只和全部六只。

## 数据来源和分层

采集层、存储层、指标层和展示层分开：

1. 上海市场份额：调用 AKShare `fund_etf_scale_sse(date=YYYYMMDD)`，核验 `基金代码`、`基金份额`。
2. 深圳市场份额：调用 AKShare `fund_scale_daily_szse(start_date, end_date, symbol="ETF")`，按 180 天窗口回填，源份额按接口约定换算为万份。
3. 单位净值：使用独立的 AKShare `fund_etf_fund_info_em` 适配器，不由 AUM/份额反推 NAV。
4. CSV：用于历史回填、缺口补录和离线测试；`data/samples/fund_flow_demo.csv` 明确标注为 `SIMULATED ONLY`，不是行情数据。
5. Tushare：仅作为可选适配器，只有设置 `TUSHARE_TOKEN` 后才会使用，不是启动依赖。

每条原始记录携带来源 ID、版本、抓取时间、单位、日期口径和导入批次；SQLite 通过 `fund_flow_` 前缀表与原有 ETF 看板共存。原始表保留导入版本，清洗表和指标表按代码、日期和计算版本幂等覆盖。

## 单位和公式

内部统一单位：份额为“万份”，单位净值为“元/份”，金额为“亿元”。

对 ETF $i$ 和交易日 $t$：

\[
\Delta S_{i,t}=S^{adj}_{i,t}-S^{adj}_{i,t-1}
\]

\[
F_{i,t}=\frac{\Delta S_{i,t}\times NAV^{adj}_{i,t}}{10000}
\]

因为“万份 × 元/份”得到“万元”，再除以 10000 才是亿元。正值表示估算净申购，负值表示估算净赎回。

若需要强度：

\[
Intensity_{i,t}=\frac{F_{i,t}}{A_{i,t-1}}\times100\%
\]

组合先逐 ETF 计算金额，再求和：

\[
F_{basket,t}=\sum_{i\in basket}F_{i,t}
\]

缺少前一交易日、份额、NAV 或口径不明确时，结果为 `None` 并标记 `BLOCKED`/`INCOMPLETE`，不填零。累计净申赎从可用基准行开始；第一条记录只作为累计基准，不制造虚假的当日资金流。

## 份额合并、拆分和审计

公司行为必须有事件日、比例、首个调整后记录日和核验状态，状态至少经过 `discovered → source_verified → basis_verified → applied`。大幅份额跳变只产生候选，不自动复权。

若 $r=新份额/旧份额$，对事件前记录统一到事件后单位：

\[
S^{adj}_t=S^{raw}_t\times r,\qquad NAV^{adj}_t=\frac{NAV^{raw}_t}{r}
\]

这样可以保持份额乘 NAV 的经济规模连续，避免把份额合并误判为巨额净赎回。510310 的 2024-09-20 合并事件已经保存为元数据；在官方份额记录核验首个调整后记录日前，受影响指标保持阻断，不会静默套用未经核验的日期。

## 质量状态

页面会区分正常、警告、阻断和组合不完整。接口失败、空响应、未知份额口径、缺 NAV、缺前一交易日、疑似公司行为和组合缺代码都会保留结构化提示。失败刷新不会删除历史数据。

## 本地运行

```cmd
cd /d "D:\我的坚果云\09-Codex\02-软件应用学习\etf-market-dashboard"
python -m pip install -r requirements.txt
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

打开 [http://127.0.0.1:8000/web/fund-flow.html](http://127.0.0.1:8000/web/fund-flow.html)。点击“刷新全部数据”会调用同一套同步服务；历史回填可在命令行执行：

```cmd
python -m scripts.fund_flow_sync --backfill --start 2023-12-29
python -m scripts.fund_flow_sync --incremental --overlap-days 5
```

当前测试使用明确标注的模拟 CSV 或 monkeypatch，不伪造真实行情；运行 `python -m pytest -q` 检查全部测试。
