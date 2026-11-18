# 沪深300ETF资金流页面布局偏移复现与整改

## 复现环境与定位

Headless Chrome 157、固定隔离快照、1440×900 和 1100×900 CSS px；每个视口冷启动 5 次，1440 热重进 5 次。Playwright 在文档最早阶段安装 `PerformanceObserver(type='layout-shift', buffered=true)`，排除近期用户输入，记录来源元素的前后位置与 CLS。页面在 `DOMContentLoaded` 之后、overview API 返回前后分别读取 DOM bounding box。命令与原始记录见 [基准脚本](../../tests/bench_frontend_round2.py)、[前](evidence/before_frontend_round2.json)、[后](evidence/after_frontend_round2.json)。

原页面 `#universe`、`#summary`、`#etf-cards` 初始均为空，由 `web/fund-flow.js` 在 overview 返回后填充。其高度在 1440 宽度分别从 0 增至 26.89、93.69、141.95 px，导致 `.fund-flow-primary-chart` 顶部从 y=469.28 移到 731.81（+262.53 px）。在 1100 宽度，摘要和 ETF 卡片换行后分别增至 203.38、293.91 px，图表顶部从 y=565.39 移到 1,089.56（+524.17 px）。PerformanceObserver 的 shift sources 指向这些异步卡片及其下方内容。图表容器本身原已预留 390 px，不是起因；未发现横向溢出。

## 最小修改

在 `web/fund-flow.html` 为上述三处加入与当前 4 ETF 布局结构一致的不可见占位内容，`web/fund-flow.css` 用 `visibility:hidden` 让它们参与正常布局。真实内容到达时原有 JS 替换节点，未固定整页高度，也未隐藏溢出或改图表数据。CSS 原有 1100、700、480 px 断点使占位卡片与真实卡片按同一网格换行。修改涉及已有前端文件；API 和金融计算未变。

| 布局指标 | 修改前 | 修改后 | 变化 |
| --- | ---: | ---: | ---: |
| 1440 冷页 CLS P50/P95，n=5 | 0.108181 / 0.108181 | 0.001167 / 0.001167 | -98.9% |
| 1100 冷页 CLS P50/P95，n=5 | 0.223769 / 0.223769 | 0.001201 / 0.001201 | -99.5% |
| 1440 热重进 CLS P50，n=5 | 0.108181 | 0.001167 | -98.9% |
| 1440 图表面板顶部，API 前→后 | 469.28→731.81 px | 731.81→731.81 px | 大位移消失 |
| 1100 图表面板顶部，API 前→后 | 565.39→1,089.56 px | 1,089.56→1,089.56 px | 大位移消失 |
| 页面横向溢出 | 5/5 无 | 5/5 无 | 无回退 |
| overview 请求数/响应体积 | 1 / 739,640 B | 1 / 739,640 B | 无变化 |

[修改前数据返回前截图](evidence/before_flow_cold_1440.png)、[修改后数据返回前截图](evidence/after_flow_cold_1440.png)、[修改后数据就绪截图](evidence/after_flow_ready_1440.png) 显示图表位置已预先稳定。首个冷页的浏览器 Trace：[前](evidence/before_flow_trace.zip)、[后](evidence/after_flow_trace.zip)。

另测 1152×720 CSS px、device scale 1.25（相当于 1440×900 物理像素下 125% 缩放的有效 CSS 空间），修改后 CLS 0.007883，5 次一致且无横向溢出。最初脚本曾在 `DOMContentLoaded` 后动态设置 CSS `zoom`，其测试操作自身造成大幅位移；该组修改前的 0.287037 已判为无效，**不参与前后对比**。修正后的缩放记录仅为修改后兼容性检查。

## 边界与风险

占位结构对应默认 4 ETF；切换到 6 ETF 后内容可能自然增高，此属用户主动筛选后的布局变化，CLS 会排除近期输入。API 错误或无数据路径会清空卡片，未单独做失败态 CLS 压测，不能声称该路径无位移。剩余约 0.0012 的首屏 CLS 由顶部其他异步细节产生，未达到本轮进一步改动的证据门槛。真实内容、图例、表格和图表序列均与修改前一致。
