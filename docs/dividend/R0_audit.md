# R0 现状核查

日期：2026-11-01（Asia/Shanghai）

## 结论

- 真实技术栈：Python 3.9 + FastAPI + sqlite3 + 原生 HTML/CSS/JS + ECharts。
- 现有入口：`web/index.html` 已有“红利看板”，其下有“ETF股息率”和“股票股息率”两个占位 `<span>`；没有红利页面路由或 API。
- 现有服务：`server.py` 挂载 `/web`、`/data`、`/api/health`、`/api/update`，并挂载 `/api/fund-flow`。现有轮动数据仍由 `web/app.js` 和原有 JSON 计算展示。
- 现有 SQLite：`data/etf_market.db` 由资金流向模块使用；红利表尚不存在。本次采用增量表，不改资金流表。
- 现有样式：`web/styles.css`；不重做全局布局。

## 保护与基线

- 数据库备份：`data/etf_market.db.r0-20261101-005710.bak`。
- 完整回归：`python -m pytest -q` → **85 passed, 2 warnings**。
- 直接调用 `pytest -q` 在本机中文路径下出现导入路径问题；这不是业务测试失败，后续统一使用 `python -m pytest -q`。
- 工作区在 R0 前已有其他未提交改动；本次不回滚、不覆盖、不重排这些文件。

## R0 阶段边界

本阶段没有重做导航，没有修改轮动、三棱镜或资金流向计算。红利功能从新增 `scripts/dividend` 域、增量 SQLite 表和局部页面挂载点开始。
