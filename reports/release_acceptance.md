# P0 发布验收

## 结论

**PASS_WITH_LIMITATIONS**

本地数据可靠性门禁、原始值保留、规范快照、失败回滚、快照固定读取和页面/API回归均已通过；线上官方数据补抓和两个官方证据项仍是限制项，因此不作无条件 PASS。

## 验收证据

| 项目 | 结果 | 证据 |
|---|---|---|
| 非有限/非正值进入当前规范计算 | PASS | `canonical_observations` 中 0 条；H20180零值在 `quality_issues` 中 BLOCKED |
| 原始异常保留 | PASS | `index_prices` 仍保留 H20180/20130628=0.0，未插值、未前填、未删除 |
| 来源追溯结构 | PASS_WITH_LIMITATIONS | 49,509 条历史记录显式 `PROVENANCE_UNKNOWN`；新采集使用 `FetchResult` |
| 官方510880黄金样本 | PASS | `tests/dividend/test_golden_samples.py`，SSE PDF哈希和金额/单位/除息日通过 |
| 股票股息率未核验保护 | PASS | 600519 TTM 返回 `null` + `INCOMPLETE`，镜像状态保留 |
| 原子写入 | PASS | SQLite双表事务和JSON/manifest失败测试通过 |
| snapshot pinning | PASS | `/api/snapshot` + `/api/snapshot/data/*?snapshot_id=`，前端固定同一版本 |
| 静态数据安全 | PASS | `/data/etf_market.db`、`/data/raw/...` 实测 404 |
| 全量回归 | PASS | `python -m pytest -q`：131 passed，2 warnings |
| 前端语法/API兼容 | PASS | 两个 JS check、Python compileall、TestClient快照API通过 |

## 命令

```text
python -m pytest -q
node --check web/app.js
node --check web/dividend.js
python -m compileall -q scripts server.py
```

## 剩余阻断/限制

1. 当前环境访问ETFirst/AkShare上游不稳定；不能用本次离线快照声称新的线上来源已经核验。
2. `H20180/20130628` 官方正确点位尚未取得，当前只做阻断，不发布替代数值。
3. 510310份额折算比例缺少官方公告证据，资金流对应区间仍需人工核查。
