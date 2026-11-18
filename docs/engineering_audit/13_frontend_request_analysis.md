# 前端请求、重绘与竞态分析

## 请求链路证据

固定快照 `20261117T211724-1c548b20`、Chrome 157、1440×900 的隔离浏览器 Network 记录如下。一次页面初次加载各取一次；表中请求数为 GET API，大小为响应 body 字节数，并非传输层压缩量。修改前后这些页面数值相同；本轮没有把必要的 Manifest 请求当作重复请求删除。

| 页面 | API 链路 | 请求数 | 响应体积合计 | 判断 |
| --- | --- | ---: | ---: | --- |
| 三棱镜 | `/api/snapshot` → `/api/snapshot/index-view?strategy=prism&snapshot_id=…` | 2 | 1,162,158 B | Manifest 用于版本固定；无重复序列请求 |
| 沪深300红利收益比较 | Manifest → `index-view?strategy=dividend-hs300` | 2 | 2,028,122 B | 无重复序列请求 |
| 沪深300成长收益比较 | Manifest → `index-view?strategy=growth-value-300` | 2 | 2,029,436 B | 无重复序列请求 |
| 五年之锚默认视图 | `/api/anchor/metrics?index_code=all` → `index_code=H20903` | 1 → 1 | 2,271,081 → 910,591 B | 原请求包含当前视图不绘制的 H00922；改用现有单指数协议 |
| 沪深300ETF资金流 | `/api/fund-flow/overview?preset=core_four…` | 1 | 739,640 B | 无重复请求 |

原始 Network、浏览器 Trace 和页面截图分别见 [修改前](evidence/before_frontend_round2.json)、[修改后](evidence/after_frontend_round2.json)、[前 Trace](evidence/before_anchor_trace.zip)、[后 Trace](evidence/after_anchor_trace.zip)、[资金流 Trace](evidence/after_flow_trace.zip)。三棱镜与指数对比页面的实测链路由 `request_chains` 字段保存。

## 绘图、筛选与生命周期

- 五年之锚 `web/anchor.js` 在页面脚本执行时创建 3 个 ECharts 实例；日期范围更改只对现存实例调用 `setOption()`。5 次近五年筛选均未新增 API，请求数 0、实例 ID 不变，图表序列仍有 3,368 行。不能为了默认窗口缩短服务端历史数据，否则全历史和自定义区间会失效。
- `web/app.js` 的 Manifest 与投影请求是版本一致性流程；初始请求链中没有同一接口重复发起。策略/日期变化会更新图表配置，属于可见业务变化。三棱镜交互绑定使用 `prismInteraction.bound` 防止重复；目前没有证据证明拆分 `app.js` 或全量重写会改善性能。
- 资金流页面单次初始加载只有一个 overview 请求，图表实例在初始化时建立，筛选变化调用同一 `load()`。首次布局偏移与图表高度无关，见 [布局分析](14_fund_flow_layout_review.md)。
- 发现实际请求竞态：快速把五年之锚均线周期从 1250 改为 1000、并延迟首个响应，原页面最终显示 MA1250，但控件为 1000；资金流快速把 `core_four` 改为 `all_six`，原页面最终显示 4 张卡片，但控件为 6 只。修改前后的 `races` 字段保存请求结束次序和最终状态。

## 处理与验证

`web/anchor.js` 与 `web/fund-flow.js` 在每次新加载时递增本地 load ID、中止上一个 `fetch`，只允许最新请求提交结果和错误信息。重复注入慢旧响应后，五年之锚控件和图表均为 MA1000；资金流为 `all_six` 且显示 6 张卡片；旧请求 `AbortError` 不覆盖页面。没有引入跨版本持久缓存或新基础设施。快速切换可能让服务器已开始的旧计算继续至请求断开，这不影响展示一致性。

HTTP 409 路径另用 [隔离浏览器回归](evidence/round2_browser_metrics.json) 验证：一次版本过期后重新取 Manifest 与投影，真实快照切换后的 409 恢复到新 snapshot_id；持续 409 时投影最多请求 2 次并显示错误，无无限重试。A03/A04/A08 相关后端实现未改。页面导航为整页跳转，旧页面的 JS/图表随文档销毁；未发现需新增定时器清理的路径。本轮不将正常刷新或用户主动改变策略的请求称为重复请求。

## 暂不修改的项目

主图 `setOption()` P50 约 66–71 ms，完整 `render()` 约 79–83 ms，没有显著不必要重绘证据。五年之锚内存改善主要随响应数据减少；长任务数量未稳定减少。三棱镜、两类指数比较及资金流的首屏请求数未下降，保留其现有链路。`app.js` 较大，但当前测量不支持为了拆文件而承担回归风险；若未来修改频率或长任务证据上升，再按 API/图表/状态边界拆分。
