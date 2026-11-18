# 修改记录、兼容性与剩余风险

本阶段新增 `scripts/providers.py`（ETF 收盘试点）、`scripts/data_center.py`、`scripts/jobs.py`、`scripts/package_code.py`、`scripts/backup_db.py`、`scripts/deploy_code.sh`、独立数据中心页面、CI 矩阵、离线测试和本目录文档。`scripts/config.py` 引入 `ETF_DATA_DIR`，`server.py` 和部分研究/股息模块改用同一数据根目录。快照读取继续走 `scripts/snapshot.py`。并发测试发现 Windows 读句柄短暂阻止 Manifest 指针替换，`scripts/storage.py` 现在对该特定 `PermissionError` 做 2 秒内短重试，超时仍向上报告且保留旧版。`server.py` 增加数据中心与任务路由，并将写操作限制为本机对等端。旧 `/api/update` 返回方式保留，主图等既有 API 格式未主动更改。

本阶段**没有修改真实历史数据内容**。现有 `data/etf_market.db` 的工作树修改和三份备份删除是开始本阶段前已存在的状态；本阶段保留了它们，未执行真实数据清理、迁移、回滚或服务器部署。测试用的三份公告 PDF 与 Manifest 只复制到 `tests/fixtures/dividend-official/`，原始证据未移动或删除。`.gitignore` 新增运行数据规则，但 Git 已跟踪的 385 个 `data/` 文件仍在索引中。部署前应核实服务器权威版本及独立目录后再分批解除跟踪。

兼容：未设置 `ETF_DATA_DIR` 时仍用仓库 `data/`；新 API 为增量接口；SQLite jobs 使用独立 `jobs.db`，无需修改现有市场表。回滚代码可以恢复旧目录/软链，但新任务状态文件与已有市场数据不应随代码回滚而删除。

剩余高优先级工作：将 ETF Provider 试点扩展成全部数据集的能力矩阵与四维 Quality Gate；所有数据集的精确采集/验证/发布状态；进程重启后自动续跑任务及跨进程全流程测试（目前超时任务可识别并重试）；生产交易日历自动采集、每张图的数据详情；Linux 实际安装与首次数据迁移；所有业务页面离线 Playwright fixture。`docs/engineering-v2/05-test-report.md` 给出逐项门槛，当前不能宣称 V2 已全部完成。主看板刷新按钮已改用新 job API，旧同步 `/api/update` 仍为兼容保留，直接调用它仍可能阻塞 HTTP 请求。

当前真实来源核验、价格口径和更近交易日获取均未被本次离线测试证明。用户无需删除数据；下一阶段先验证服务器目录/服务配置，再做隔离环境中的跨平台与真实上游抽查。
