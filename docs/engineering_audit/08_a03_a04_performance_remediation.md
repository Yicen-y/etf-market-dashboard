# A03 / A04 第一轮性能整改报告

日期：2026-11-18。范围仅为指数有界读取与轮动总览缓存。当前工作区在本轮开始前已有大量未提交变更；本轮没有修改原始 SQLite、既有行情、金融公式、策略或核验放行规则。

## 根因与实际修改

**A03。** `/api/snapshot/data/index_prices.json` 每次读取、校验、解析整个发布 JSON，然后传输全部 `records`、`flatRecords` 和八组 `strategyMetrics`。当前快照中仅 `strategyMetrics` 的 `ensure_ascii=False` JSON 估算已约 15 MB；页面一次只展示当前策略，`flatRecords` 不被主图使用。`web/app.js` 原本对同一快照的指数请求复用一个 Promise，但策略切换仍依赖整包。新增 `/api/snapshot/index-view`，按 `strategy` **或** `codes` 选择指数，并支持 `start`/`end`（`YYYYMMDD`，均可省略）。未给日期时返回该策略全历史；指标使用发布快照中已经计算的逐点结果，先投影再筛选，不重新计算窗口。旧全量 URL 保持原样。主图按当前策略请求，ETF 全收益复合图请求 `etf-index` 三条指数；同快照同策略复用 Promise，快照变化清空前端缓存。新增接口目前仍完整读取和哈希校验发布文件，这是保留完整性保障所付出的冷请求成本；SQLite 查询为零。

**A04。** `/api/rotation/overview` 原来每次读取两份快照并从全历史重新生成九组总览。现以 `DATA_ROOT`、快照 ID、两文件路径和**实际文件 SHA256** 为键，缓存最多四个总览结果。每次命中前流式核对文件哈希与 Manifest；换版本或文件变化会失效。缓存仅保存聚合结果，不改变 `build_overview` 的计算。当前接口没有策略 ID 或用户参数，缓存完整九组总览比拆为逐策略缓存更简单；未做增量指标计算，因为发布快照已含指标，且这会增加公式一致性风险。

修改文件：`scripts/index_view.py`（新）、`server.py`、`web/app.js`、`tests/test_index_view.py`（新）、`tests/test_rotation_overview.py`、`tests/bench_a03_a04.py`（新）、`tests/bench_a03_browser.py`（新）。

## 测试环境与方法

Windows、本机 Python 3.9、FastAPI TestClient、Headless Chrome；快照 `20261117T211724-1c548b20`。基准脚本用 SQLite Backup API 将原库复制到临时目录，复制 Manifest 和当前发布文件，设置 `ETF_DATA_DIR` 指向副本，测试结束删除临时目录。每个 API 12 次顺序请求，P95 为小样本最近秩；用 `sqlite3.connect` 包装与 trace callback 记录请求中的连接/SQL 次数。浏览器脚本在隔离 Uvicorn 进程访问同一页面，旧方案通过拦截新 URL、以旧全量 API 响应替换，其他页面代码不变；两方案各 5 次新页面加载，计时从导航到三棱镜观察值与新鲜度可见。命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -B tests/bench_a03_a04.py
python -B tests/bench_a03_browser.py
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -B -m pytest -q -p no:cacheprovider
node --check web/app.js
```

## 前后实测

下表“优化前”来自本轮修改前同一基准脚本；“优化后”来自最终版本再次运行。12 次样本不能稳定估计 P99，也不是公网网络指标。

| 场景 | 优化前 P50/P95 | 优化后 P50/P95 | 响应字节（前 → 后） | SQLite 查询/耗时 |
|---|---:|---:|---:|---:|
| 指数主图，三棱镜所需序列 | 777.66 / 910.03 ms（旧整包） | 432.65 / 569.84 ms（新投影） | 18,768,125 → 1,161,965 | 0 / 0 ms |
| 指数主图，一组配置策略 | 777.66 / 910.03 ms（旧整包） | 437.74 / 524.81 ms（新投影） | 18,768,125 → 2,027,929 | 0 / 0 ms |
| 旧全量 API 兼容路径 | 777.66 / 910.03 ms | 763.60 / 869.38 ms | 18,768,125 → 18,768,125 | 0 / 0 ms |
| 总览 API，连续 12 次混合冷/热 | 712.59 / 783.67 ms | 33.15 / 871.66 ms | 8,837 → 8,837 | 0 / 0 ms |

总览混合 P95 由一次冷请求决定，应分别看：优化后**冷** 871.66 ms、后续 11 次**热** P50 33.03 ms；切换到新的有效快照后首次访问 911.88 ms，返回新快照 ID。最后一次测量中，快照读取段 P50/P95 为 365.47/445.49 ms；总览计算仅在冷请求和换版本首次请求执行两次，耗时约 362 ms。与优化前计算段 P50 292.86 ms 的差别是运行波动，公式未改变，不能据此声称计算本身加速。

浏览器三棱镜图表就绪：旧整包 5 次 P50 **2,048.78 ms**，新投影 5 次 P50 **1,100.89 ms**。这是同机隔离服务与 Headless Chrome 的导航到可见状态耗时；样本少，不推断其他设备。一次 `prism → dividend-hs300 → prism` 切换仅发出两次指数投影请求，回到已访问策略未重复请求；ETF 首页全收益复合图正常就绪。

## 正确性与兼容性

- 当前真实快照中，`prism`、`etf-index` 和八组配置策略共 10 种投影均保留 **3,087 个历史日期**；选中指数的每个点位与原始快照逐点相同；三棱镜预计算字段及八组策略各自的 `strategyMetrics` 逐点相同。
- 固定夹具验证日期范围、代码筛选、无效策略、旧快照 ID、错误日期顺序；旧 `/api/snapshot/data/index_prices.json` 返回结构不变。原总览的计算函数未改；缓存测试验证同版本只计算一次、换版本重新计算、文件损坏返回 503。
- 全量回归：**503 passed，24 skipped，2 个本机可选 pandas 依赖警告**；`node --check web/app.js` 通过。24 项跳过的在线/环境测试未被当作通过。未运行真实数据更新；隔离副本通过切换到另一有效快照验证首次访问失效。

## 风险与回滚

新投影接口每次仍解析全量发布 JSON，因此冷请求约 0.43 秒，后续若要优化文件解析应另行评估完整性与内存风险。总览热请求每次仍哈希读取发布文件，约 33 ms，避免缓存掩盖文件损坏；`lru_cache(maxsize=4)` 限制进程内结果数，跨进程各有独立缓存，但按文件哈希失效。浏览器请求按策略缓存，切换快照会清空；未改变图表结构或指标口径。

回滚时让 `web/app.js` 恢复使用旧全量指数接口，移除新路由及 `scripts/index_view.py`；总览去掉 `@lru_cache` 和哈希键包装，恢复直接调用 `build_overview`。既有全量 API、数据库结构和数据无需迁移或回滚。
