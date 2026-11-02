# Wind MCP 历史指数校验设计

## 目标

在本地 ETF 看板工程中接入 Wind Alice MCP，通过官方 Streamable HTTP 服务查询已授权的指数数据，将 Wind 历史点位与本地数据逐日核对，并生成可追溯差异报告。Wind 用于校验，日常数据增量仍由现有 ETFirst/AKShare 流程完成。

## 官方接入信息

- MCP endpoint：`https://mcp.wind.com.cn/vserver_wind_tools/mcp/`
- 传输：Streamable HTTP
- 认证：HTTP `Authorization` 请求头；值由账户在 Alice Market 页面的一键配置提供。
- 官方手册不固定工具名和参数，因此客户端先调用 `tools/list`，再由显式配置或命令行参数选择工具；不臆造 Wind 工具名或字段。

## 结构与边界

- `scripts/wind_mcp_client.py`：同步 HTTP MCP 客户端；实现 initialize、notifications/initialized、tools/list、tools/call；保留服务端返回的 session id；处理 JSON 与 SSE 响应、HTTP/MCP 错误、超时和重试边界。
- `scripts/wind_validator.py`：把 Wind 工具输出规范化为 `(index_code, trade_date, close_value)`，并与数据库/JSON 快照比较，产生 `MATCH`、`LOCAL_MISSING`、`WIND_MISSING`、`VALUE_MISMATCH`、`INVALID_RESPONSE` 等结果。
- `scripts/validate_wind.py`：命令行入口；支持列出工具、指定工具与 JSON 参数、校验单个/全部配置指数、输出终端摘要和机器可读报告。
- `reports/wind/`：运行时报告目录，默认不纳入版本控制，报告记录请求工具、日期范围、代码映射、数据口径、返回行数、差异和时间戳，不包含 Authorization。
- `requirements.txt`：优先用项目现有 `requests` 传递依赖；若它不是明确依赖，则增加兼容当前 Python 的直接依赖。

## 配置与凭据

- endpoint 默认使用官方地址，可用 `WIND_MCP_URL` 覆盖。
- Authorization 从 `WIND_MCP_AUTH` 环境变量读取，不写入仓库、SQLite、日志或报告。
- 工具名与参数 JSON 通过参数显式传入，工具 schema 由 `tools/list` 展示并验证。
- 指数代码映射单独配置，需明确本地轮动标的（如 480080、480081、H00821 等）在 Wind 中的代码，以及价格/全收益口径。无法无歧义映射的标的标记为 `UNMAPPED`，不猜代码。

## 校验规则

1. 日期按交易日原样对齐；不插值、不前值填充。
2. 仅比较相同指数口径、相同日期的原始收盘点位。
3. 默认绝对/相对容差为零并同时报告差值；如 Wind 数据精度或接口舍入要求容差，必须在报告配置中显式声明。
4. 报告只读，不改写 canonical 数据。后续数据修正须有明确 Wind 来源证据及独立的人工确认步骤。
5. 所有 MCP 原始响应可选择性落盘时须先脱敏，不保存认证头；数据库不保存 MCP session/token。

## 错误处理

- 缺少凭据、认证失败、工具不存在、工具参数不符合 schema、网络超时、服务端错误、非 JSON/SSE 响应均给出可诊断错误。
- session id 仅在单次客户端生命周期内存储。
- 对 GET/列表读取可有限重试；工具调用仅在明确可安全重试的传输失败时重试，避免重复计费/重复执行。
- Wind MCP 不可用时保留本地数据，校验任务失败并记录状态，不影响 ETFirst/AKShare 更新。

## 测试

使用本地 mock HTTP server 覆盖握手/session、tools/list、tools/call 的 JSON 和 SSE 响应、MCP 错误、认证头不泄漏、字段规范化、日期对齐、差异分类、空数据与缺口。另提供真实连接的手动 smoke-test 命令；不在自动测试中调用真实 Wind 服务或消耗账户额度。

## 风险与边界

Wind MCP 的实际工具列表、具体指数历史行情工具、输出结构、授权范围和批量点数限制，必须以用户账户当前 `tools/list` 和返回 schema 为准。未取得有效 Authorization 前，客户端可以完成实现和 mock 测试，但无法完成真实 Wind 行情校验。
