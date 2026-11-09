# 红利策略整合验收记录

**日期：** 2026-11-05  
**范围：** 基于 `docs/ETF投资看板_五年之锚与红利三策略_整合开发需求_v3.0.md` 的本轮增量实施。此报告区分已实现代码与被数据证据阻断的合同项，不将部分实现称为完整交付。

## 本轮已完成

- 新增 `scripts/dividend/research.py` 纯函数：H00922对数线性OLS固定as-of/扩展点时模式、残差样本标准差及指数尺度通道、A/H共同点40区间收益差、官方股息率减CN10Y百分点利差与经验CDF分位。
- 新增只读 API `scripts/dividend/research_api.py` 并注册在 `server.py`：
  - `GET /api/research/dividend-regression`
  - `GET /api/research/dividend-ah`
  - `GET /api/research/dividend-yield`
- 新增 `web/dividend-research.html/js/css` 页面并加入侧边导航。
- H20922回归页面标示 `UNVERIFIED_SOURCE`；A/H与官方股息率缺失时返回明确状态，不补值、不拿错误指数替代。
- 五年之锚、三棱镜和数据质量基线测试继续通过。

## 数据证据状态

本机SQLite快照 `20261104T212450-113cbb77`：H00922与H20903各3359个交易日记录（2012-12-31至2026-11-04）；每个序列3356条标为 `PROVENANCE_UNKNOWN`，只3条记录有AkShare来源标签。该标签不是官方核验凭据。H20915、000922、930915在 `index_prices` 中均为0行。

因此：

- H00922回归数值可作为**非交易性研究预览**，但真实源数据准确性尚未完成逐日官方校验。
- A/H共同日比较没有H20915真实历史数据，当前API回传 `MISSING_SERIES`，不是完成的策略页面数据。
- 中证官方股息率2和中国债券信息网CN10Y历史序列尚未接入；股息率API回传 `MISSING_OFFICIAL`。
- 不输出因数据不足而不可验证的条件收益、回测或稳健性结论。

## 测试与冒烟

- `python -m pytest tests/test_dividend_research.py tests/test_server.py tests/anchor tests/test_prism_metrics.py tests/test_reliability_p0.py -q`：69 passed（执行时包含FastAPI参数弃用警告；之后将`regex`改为`pattern`，需在最终验证复跑）。
- `python -m pytest -q`：216 passed，0 failed；输出包含pandas对本机numexpr/bottleneck版本的两条警告，以及上述FastAPI弃用警告（弃用项随后修正，仍需复跑全量确认）。
- `node --check web/dividend-research.js`：通过。
- TestClient：回归API 200；A/H缺序列API 200且返回`MISSING_SERIES`；股息率API 200且返回`MISSING_OFFICIAL`；页面静态资源200。

## 公式/口径

- 回归：`y=ln(P)`，`x=(date-date0)/365.2425`；OLS残差样本标准差`s_e=sqrt(SSE/(n-2))`；趋势`exp(alpha+beta*x)`；上下通道`trend*exp(±k*s_e)`；`Z=residual/s_e`；年化趋势率`exp(beta)-1`。固定as-of只用于事后描述，扩展模式才是点时序列。
- A/H：要求41个共同有效点计算40间隔收益差；`D40=(A_t/A_{t-40})-(H_t/H_{t-40})`，缺失未做前值填充。
- 股息率利差：`DY2(%) - CN10Y(%)`，单位pp；样本不足不算分位。

## 尚未完成 / 不能验收

1. P0：真实数据源注册、官方数据核对、索引元数据与可靠性事实表未完整建立。
2. P2：H20915获取、数据质量/共同休市日历、三棱镜第八组配置和复合图尚未实现；现在只有纯计算函数和缺数API。
3. P3：官方指数股息率2、CN10Y采集与历史版本控制未实现，只有明确缺失API。
4. P4：红利三策略统一回测、条件收益、参数敏感性、滚动样本外和交叉策略报告未实现。
5. 页面尚未做真实浏览器截图验收；现有H00922曲线依赖来源未核验的本地快照。

## 结论

这是可运行的研究模块初版，不是需求v3.0的完整交付。原工程全量pytest未见回归失败，但关键真实历史数据源缺失阻止了P0、P2、P3和P4退出验收。不得把本地研究预览解释为已核验策略表现。
