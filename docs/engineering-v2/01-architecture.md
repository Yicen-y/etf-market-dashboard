# V2 架构与实际边界

现有主链：`providers.DataRequest`（ETF 收盘试点）→ `fetch_data.FetchResult` → `update_data` 的来源门禁与质量检查 → `storage` 写入 SQLite 和 prepared release → `current_manifest.json` 原子指向已发布 JSON → `snapshot.read_dataset` 校验后供 API、业务页面读取。`DataProviderManager` 只处理能力匹配、传输错误有限重试和短熔断，绝不授权发布。候选新浪数据仅记录 Raw 与质量问题，未经明确策略与重叠对账不得进入 Canonical。

本阶段新增：`ETF_DATA_DIR` 使运行数据独立于代码；`data_center.build_data_center` 只读汇总清单、数据库、质量问题与任务记录；`jobs` 用独立 SQLite `jobs.db` 在跨进程事务中认领同一数据集/日期的任务；`/api/jobs/update` 立即返回 job ID，后台执行原有更新函数，主看板轮询此任务。任务状态与市场数据发布状态分开，部分同步失败会显示 PARTIAL，健康接口仍可读旧版但标记 DEGRADED。`/api/update` 为兼容旧调用方继续同步运行。

发布状态机已有 `prepared` → 文件核验 → Manifest 指针切换 → `published` 与恢复逻辑。`release_id`/`snapshot_id` 绑定见 `scripts/storage.py`；失败不会把 prepared 版本给读端。SQLite 和文件系统没有跨介质 ACID，故由发布指针决定读端可见版本。

安全边界：服务应绑定 `127.0.0.1`；所有 POST/PUT/PATCH/DELETE 还检查实际对等端为 loopback，反向代理若开放这些路径须另设访问控制。数据中心只读，任何来源核验未知一律 `UNKNOWN`。

任务表每 15 秒刷新心跳；超过 90 秒无心跳的 QUEUED/RUNNING 任务只读查询显示 ORPHANED/FAILED，新的认领会原子标记旧任务并允许重试。旧 `jobs.db` 自动迁移心跳与采集/校验/发布三阶段列。尚未完成：将 ETF 试点 Provider 契约扩展到指数/分红/份额/股债并统一能力清单、逐数据集任务阶段回调、进程重启后自动续跑未完成任务，以及所有业务模块统一经 Snapshot Reader 读数。当前数据中心只对 ETF/指数发布文件执行强校验，其他数据集的状态仍较粗。
