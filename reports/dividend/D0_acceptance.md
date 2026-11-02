# D0 放行报告

日期：2026-11-01

## 结论

**FAIL（实现底座已通过，官方黄金样本与联网采集未完成）**。

| 项目 | 结果 | 证据 |
|---|---|---|
| Decimal 纯函数 | PASS，6 条 | `tests/dividend/test_domain.py` |
| SQLite 增量账本/自选幂等 | PASS，2 条 | `tests/dividend/test_db.py` |
| 独立参考复算 | PASS，1 条 | `tests/dividend/test_reference_calculator.py` |
| 510880 单位/日期离线夹具 | PASS，实际除息日 2026-01-21、1.4300/10→0.14300/份 | `tests/dividend/test_reference_calculator.py` |
| 600519 官方公告逐字段核验 | FAIL / LIMITED | 已保存公告镜像并核对关键字段；上交所静态 PDF 直链返回防护 HTML，未标记为官方核验，相关指标仍阻断为 `INCOMPLETE` |
| 真实公司行动黄金样本 | NOT_AVAILABLE | 仅实现数学纯函数，未宣称真实样本核验 |
| T01—T38 全集 | NOT_COMPLETE | 当前仓库未提供完整 T01—T38 文件；已覆盖的 D0 核心夹具和黄金样本字段测试 13 条通过 |
| 原工程回归 | FAIL（并发变更冲突） | 98 passed, 1 failed；`tests/test_fund_flow_workflow.py` 仍要求旧 `renderChart(...,"bar")` 字符串，当前 `web/fund-flow.js` 已被其他智能体改为折线实现；红利代码未触碰该文件 |
| 真实同步适配器 | PARTIAL | AkShare 适配器已接入；本机实际请求 Eastmoney 被代理拒绝，返回 error 且不写入伪造数据 |

## 质量边界

生产接口只对本地固定 510880 事件提供可计算 TTM，600519 返回 `null + INCOMPLETE`。因此没有把未核验数据格式化成看似精确的股息率。证据清单位于 `data/raw/dividend/evidence_manifest.json`；600519 仍存在官方 PDF 直链不可获取的限制，且旧工程回归存在并发变更冲突，D0 不能放行。
