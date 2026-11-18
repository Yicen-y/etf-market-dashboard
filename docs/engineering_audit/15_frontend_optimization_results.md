# 本轮前端性能整改结果与回滚

## 范围与修改

本轮只处理已复现的三组问题，修改前以当前工作树快照和 [修改前浏览器基准](evidence/before_frontend_round2.json) 留存回滚基线；仓库原本存在其他未提交改动，本轮未清理或重置它们。

1. 五年之锚默认视图冗余数据：`web/anchor.js` 请求当前 `data-view` 对应的现有 `/api/anchor/metrics?index_code=` 参数，双指数视图继续使用 `all`；`web/anchor.html` 更新脚本缓存版本。
2. 快速筛选时旧请求覆盖新结果：`web/anchor.js`、`web/fund-flow.js` 用 `AbortController` 和 load ID 保护最新请求；`web/fund-flow.html` 更新脚本缓存版本。
3. 资金流卡片异步插入导致 CLS：`web/fund-flow.html` 加入网格占位节点，`web/fund-flow.css` 让占位参与布局并隐藏其视觉内容。

新增复现与回归脚本：`tests/bench_frontend_round2.py`、`tests/ui_frontend_round2_regression.py`。已有浏览器回归 `tests/ui_a07_a09_browser.py` 仅增加 `round2` 输出名及同等断言，避免覆盖此前 A07/A09 的 `after` 证据。报告：[五年之锚分析](12_five_year_anchor_performance.md)、[请求链路](13_frontend_request_analysis.md)、[布局](14_fund_flow_layout_review.md)。

## 统一验收对照

环境：Windows 本机，Python 3.9.13，Headless Chrome 157.0.8103.79，视口 1440×900 CSS px，固定快照 `20261117T211724-1c548b20` 的隔离副本；前后各 5 次冷页、5 次热页及 5 次日期筛选。API 耗时来自浏览器 ResourceTiming；图表就绪为页面导航至图表 `setOption()` 后两个动画帧；响应体积为 body 字节。P95 对 5 个样本取 nearest-rank 最大值。资金流另测 1100×900 和热重进各 5 次。详见 [方法和原始样本](12_five_year_anchor_performance.md)。

| 指标 | 修改前 | 修改后 | 变化 |
| --- | ---: | ---: | ---: |
| 五年之锚默认 API P50/P95 | 1,358.80 / 1,428.80 ms | 884.70 / 1,056.60 ms | P50 -474.10 ms（-34.9%） |
| 五年之锚响应体积 | 2,271,081 B | 910,591 B | -1,360,490 B（-59.9%） |
| 首次图表就绪 P50/P95 | 1,872.79 / 2,543.89 ms | 1,345.88 / 2,103.79 ms | P50 -526.91 ms（-28.1%） |
| 热启动图表就绪 P50/P95 | 1,863.63 / 1,911.32 ms | 1,317.53 / 1,376.91 ms | P50 -546.10 ms（-29.3%） |
| 五年之锚初始 API 请求数 | 1 | 1 | 0 |
| 主图 `setOption()` P50/P95 | 70.7 / 78.2 ms | 66.3 / 69.9 ms | P50 -4.4 ms；变化较小 |
| 完整 `render()` P50/P95 | 83.3 / 96.4 ms | 79.4 / 89.4 ms | P50 -3.9 ms；变化较小 |
| 资金流 1440 冷页 CLS | 0.108181 | 0.001167 | -0.107014（-98.9%） |
| 资金流 1100 冷页 CLS | 0.223769 | 0.001201 | -0.222567（-99.5%） |

三棱镜、红利/成长对比页面仍各有 2 个必要的 Manifest＋投影请求；资金流仍为 1 个 overview 请求。API **请求次数没有减少**，五年之锚减少的是默认响应体积和服务器处理范围。`all` 直接 API P50 1,144.83→1,168.36 ms，单指数直接 API P50 784.50→814.03 ms；两者前后差异很小且均为 5 次样本波动，本轮未声称后端接口本身提速。完整样本：[前](evidence/before_frontend_round2.json)、[后](evidence/after_frontend_round2.json)。

## 回归与测试

| 项目 | 结果 |
| --- | --- |
| 单指数 vs `all` 中相应金融数据 | H20903、H00922 的 `indexes[code]` 逐项相等，快照 ID 相同；各 3,368 行 |
| 全历史与日期筛选 | “全部”覆盖 2012-12-31 至 2026-11-17；近五年切换 0 额外 API，图表实例不变 |
| 视图/策略切换 | H20903→H00922→双指数发出正确筛选请求；三棱镜及指数对比 UI smoke 通过 |
| 请求竞态 | 延迟旧响应后，五年之锚呈现 MA1000、资金流呈现 6 ETF，均与当前控件一致 |
| A03/A04/A08 | 完整 pytest 通过；浏览器一次性 409 恢复、真实快照切换、持续 409 最多 2 次请求且展示错误均通过；复合图断言通过 |
| 资金流图表/内容 | 1440 与 1100 图表容器、数据就绪均正常，初始 API 数与字节数不变；没有横向溢出或新 JS 错误 |
| 全量自动化 | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -B -m pytest -q -rs -p no:cacheprovider`：507 passed、24 skipped、2 个第三方库版本警告 |

24 skipped 的组成：14 项 `test_index_latest_online.py` 需显式 live 目标日期；`test_index_verification_online.py` 6＋4 项需主动启用 live provider。这些是会访问在线数据源的可选测试，不是本轮前端关键验证的缺口；离线隔离快照的浏览器与金融数据一致性已由 [专项回归](evidence/round2_regression.json) 和 [409/复合图回归](evidence/round2_browser_metrics.json) 补足。无需为了降低 skipped 数量修改无关用例。

## 未覆盖边界、风险与回滚

- 样本数 5，P95 对偶发调度敏感；未测试弱网、浏览器多标签压力或移动硬件。长任务没有稳定改善，继续压缩 ECharts 渲染或拆分 `app.js` 缺少明确收益证据。
- 资金流占位按照默认 4 ETF 数量布置；6 ETF 为用户主动筛选后自然扩展。错误/空数据路径的 CLS 未单独压测。125% 缩放使用首帧前 1152×720 CSS px 加 1.25 device scale，仅有修改后兼容性值 0.007883；原先动态 CSS zoom 测得的修改前值无效，未做对比。
- 用户快速改筛选时前一个 HTTP 请求可能已在服务器开始计算；浏览器忽略其结果，但不能保证取消服务器运算。未引入持久客户端缓存，不会跨 A08 快照版本留存旧数据。
- 回滚以修改前基准和本轮定点 diff 为准：恢复 `web/anchor.js` 原 `index_code=all` 请求与原加载处理，恢复 `web/fund-flow.js` 原加载处理，移除 `web/fund-flow.html` 占位、`web/fund-flow.css` 占位规则并还原对应资源缓存版本；然后重跑上述浏览器脚本和 pytest。不要对整个脏工作树执行硬重置，以免覆盖既有 A03/A04/A08/A09 工作。

本轮不修改 `app.js`，未改变金融计算、指数放行、数据核验、快照发布机制、A03 有界读取、A04 缓存或单图复合展示。
