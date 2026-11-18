# 性能审计

## 环境、方法与可复现命令

Windows 本机 Python 3.9；当前未提交工作区与发布快照 `20261117T211724-1c548b20`。只读打开 SQLite (`mode=ro`)；未运行数据更新、未写原库。直接调用 `scripts.snapshot.read_dataset` 与 `scripts.rotation_overview.build_overview` 各 12 次，`time.perf_counter()` 计时；JSON 体积按 `json.dumps(..., ensure_ascii=False).encode()` 估算。另用 SQLite Backup API 将原库一致性备份到 `tempfile.TemporaryDirectory`，复制 Manifest 与当前 release，设置 `ETF_DATA_DIR` 指向临时目录后，通过 FastAPI `TestClient` 对四个接口各发 12 次请求。测试命令核心如下：

```python
from scripts.snapshot import read_manifest, read_dataset
from scripts.rotation_overview import build_overview
from scripts.config import DATA_ROOT
import time
m = read_manifest(DATA_ROOT)
t = time.perf_counter(); index = read_dataset(DATA_ROOT, m, 'index'); print(time.perf_counter()-t)
etf = read_dataset(DATA_ROOT, m, 'etf')
t = time.perf_counter(); build_overview(m['snapshot_id'], index, etf); print(time.perf_counter()-t)
# 隔离 API 基准：先以 sqlite3.Connection.backup() 和 shutil.copyfile()
# 将数据库、Manifest、当前 release 复制到临时目录，再设置 ETF_DATA_DIR。
# from fastapi.testclient import TestClient; with TestClient(app) as c: c.get(route)
```

## 实测

| 操作 | 样本/数据量 | 本机耗时 | 含义 |
|---|---:|---:|---|
| ETF 快照读取、哈希、JSON 解析 | 3,359 日；约 0.68 MB 响应 JSON | P50 11.19 ms；样本 P95 13.51 ms | 仅服务端函数，未计网络/浏览器 |
| 指数快照读取、哈希、JSON 解析 | 3,087 日；约 20.38 MB 响应 JSON | P50 378.31 ms；样本 P95 437.81 ms | 整包解析是确定成本 |
| 轮动总览纯计算 | 8 组策略，已加载内存的两份数据 | P50 335.36 ms；样本 P95 363.62 ms | 未计再次读快照与 HTTP |
| `/api/snapshot` | 193 B | P50 2.22 ms；样本 P95 3.14 ms；样本最大 43.78 ms | 隔离副本 TestClient |
| `/api/snapshot/data/etf_prices.json` | 620,166 B | P50 29.12 ms；样本 P95 48.12 ms；样本最大 59.52 ms | 隔离副本 TestClient |
| `/api/snapshot/data/index_prices.json` | 18,768,125 B | P50 809.06 ms；样本 P95 904.64 ms；样本最大 1039.17 ms | 隔离副本 TestClient |
| `/api/rotation/overview` | 8,837 B | P50 749.14 ms；样本 P95 843.73 ms；样本最大 919.18 ms | 隔离副本 TestClient |

12 次样本不足以稳定估算 P99，故只报告样本最大值，不充当 P99。SQLite 文件约 123 MB；只读计数：`index_prices` 46,604 行、`etf_prices` 6,103 行、资金流 raw 4,072 行、metrics 3,840 行、`dividend_quotes` 1,862 行、`raw_observations` 61,055 行。未测 CPU/峰值内存、真实网络下 P50/P95/P99、数据库/计算/序列化各段的 API 细分及浏览器加载；TestClient 耗时不等于用户感知耗时。

## 查询计划与瓶颈定位

```sql
EXPLAIN QUERY PLAN SELECT * FROM index_prices
 WHERE index_code='H00922' AND trade_date>='20200101' ORDER BY trade_date;
-- SEARCH index_prices USING INDEX idx_index_prices_code_date (index_code=? AND trade_date>?)
EXPLAIN QUERY PLAN SELECT * FROM dividend_quotes
 WHERE security_id='510880' ORDER BY trade_date;
-- SEARCH dividend_quotes USING INDEX sqlite_autoindex_dividend_quotes_1 (security_id=?)
```

代表性价格查询已有匹配索引，不建议凭表大小新增索引。更明确的瓶颈位于 JSON 整包读取与 Python 总览重算：`server.py:493-505` 每次调用重读两个快照并计算；`server.py:509-520` 返回完整快照；`web/app.js:25-35` 缓存当前快照的 Promise，避免同页面重复请求，但新快照仍整包传输。`dividend/service.py:227-247` 为每个历史报价调用 `_calculation_coverage`，其内部多次查询，属代码证据支持的潜在 N×查询风险；本轮未实测该接口，因此不填写虚构延迟。

## 有价值的优化与验收

1. 指数查询：先记录浏览器 Network 中传输、解析和首图渲染时间；按策略返回所需序列与区间，保留完整快照下载作诊断。预期减少字节量，**具体收益待复测**。成本 2–4 天，风险为前后端日期/口径不一致；用同快照逐点比对和图表契约测试验收。
2. 总览：用 `(snapshot_id, 计算版本)` 作为进程内缓存键，快照切换自然失效。成本约 0.5–1 天；验收为冷/热 HTTP 延迟和相同结果哈希，避免缓存旧版。无需 Redis。
3. 分红历史：记录查询次数和请求耗时，再一次性取覆盖证据或批量预计算。成本 1–2 天；验收为 1Y/3Y/5Y 结果逐点一致，查询次数不随日数线性放大。
4. 前端：基于真实浏览器记录首屏请求、图表渲染与切换耗时；当前没有 Lighthouse 或 Performance 记录，不声称已有前端卡顿。保留收益曲线与差值柱在同一图。
