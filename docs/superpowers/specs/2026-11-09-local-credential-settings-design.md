# 本地数据源凭证设置设计

## 1. 目标与范围

为本地 ETF 看板增加统一的凭证设置入口，允许使用者显式配置三类数据源：

- Wind MCP
- 华泰柏瑞 ETF
- 南方基金 ETFirst

凭证仅供本机后端数据采集使用，不写入 SQLite、JSON、前端静态资源、浏览器 `localStorage`、日志或 Git。该功能不增加登录、用户系统、远程部署或权限管理。

## 2. 存储方案

三类凭证统一写入 Windows Credential Manager，通过 Python `keyring` 访问。

服务名统一为 `etf-market-dashboard`，凭证账号分别为：

| 数据源 | 凭证项 |
|---|---|
| Wind MCP | `WIND_MCP_AUTH` |
| 华泰柏瑞 ETF | `HTBR_ETF_API_KEY` |
| 南方 ETFirst | `ETFIRST_API_KEY` |

读取顺序为：必要时保留现有环境变量兼容能力，其次读取 Windows Credential Manager。网页 API 永远只返回是否已配置、脱敏状态和测试结果，不返回凭证值。

如果当前数据源的官方 CLI 或 skill 已有自己的认证配置，后端设置适配器负责调用其既有配置机制；不复制认证逻辑，也不把 Key 拼接到 URL 或命令日志中。

## 3. 后端设计

新增独立凭证模块，职责包括：

- provider 白名单与凭证项映射；
- 保存、删除、读取配置状态；
- 规范化 Wind Authorization 前缀；
- 屏蔽明文输出；
- 对 Windows Credential Manager 不可用的情况返回明确错误；
- 为测试连接提供统一入口。

新增接口：

```text
GET    /api/settings/credentials
PUT    /api/settings/credentials/{provider}
DELETE /api/settings/credentials/{provider}
POST   /api/settings/credentials/{provider}/test
```

其中 `provider` 只允许 `wind`、`htbr`、`etfirst`。

请求体只接受当前 provider 对应的 Key；响应仅包含：

- provider；
- configured；
- masked；
- message；
- tested_at（连接测试接口）。

保存接口不在响应中回显 Key。删除接口幂等处理，重复删除视为成功。未知 provider、空凭证、非 Windows 凭证库后端和上游测试失败均返回可读错误，但错误信息不得包含凭证内容。

## 4. 数据源适配

凭证设置只负责保存和配置，不改变现有数据计算逻辑。

- Wind：复用 `scripts.wind_credentials.get_authorization()`，新增网页保存/删除入口。
- ETFirst：读取 `ETFIRST_API_KEY`，在 ETFirst CLI 调用或认证配置操作中使用；不把 Key 固定写入项目文件。
- 华泰柏瑞 ETF：读取 `HTBR_ETF_API_KEY`，按照已安装 skill 的配置入口注入；如果当前 skill 仅支持外部凭证配置，则保存后执行其配置命令并隐藏输入。

连接测试必须使用最小只读请求，并设置超时；测试失败不删除已有有效凭证。数据刷新继续使用现有锁和错误处理。

## 5. 前端设计

沿用现有导航、卡片、按钮、状态提示和响应式布局。

设置页建议路径：`web/settings.html`，脚本和样式分别为 `web/settings.js`、`web/settings.css`。

每个数据源卡片包含：

- 数据源名称和用途说明；
- 密码输入框；
- 显示/隐藏按钮；
- 保存按钮；
- 删除按钮；
- 测试连接按钮；
- 已配置/未配置状态；
- 最近操作结果。

页面加载时只读取配置状态，不读取明文。保存、删除和测试均显示加载中、成功和失败状态，并禁止重复提交。页面支持键盘操作、`label` 关联、`aria-live` 状态提示和窄屏布局。

导航增加“设置”入口。现有页面不改变业务交互；若设置页被直接打开，也应保持统一导航和返回路径。

## 6. 测试设计

后端测试覆盖：

- provider 白名单；
- Windows Credential Manager 读写调用；
- 保存、读取状态、删除幂等；
- Wind Authorization 规范化；
- 空值和未知 provider 拒绝；
- 响应和日志不包含明文 Key；
- 上游测试失败不覆盖已有凭证。

前端静态/行为测试覆盖：

- 设置页存在三类凭证卡片；
- 页面只显示状态，不显示原 Key；
- 保存、删除、测试按钮调用正确接口；
- 错误信息可见且不泄露凭证；
- 导航入口与响应式布局存在。

现有项目回归测试继续运行，尤其是 Wind、股息率、ETF 数据刷新和导航测试。

## 7. 风险与处理

- Windows Credential Manager 不可用：拒绝降级为明文文件，提示使用者安装/启用 `keyring` 的 Windows 后端。
- ETFirst 或华泰柏瑞 skill 的认证接口可能随版本变化：适配器通过已有 CLI/skill 配置入口调用，失败时明确提示，不伪造“已连接”。
- API 测试可能触发上游限频：测试入口采用最小请求、超时和服务端锁，不支持高频连续点击。
- 本地凭证状态属于当前 Windows 用户，换电脑或换用户不会自动迁移。

## 8. 验收标准

1. 用户可在设置页分别保存三类 Key。
2. 重启本地服务后，设置状态仍然保留。
3. API 响应、前端页面、日志和 Git diff 中均不存在明文 Key。
4. Wind、ETFirst、华泰柏瑞的数据刷新逻辑能够读取各自凭证。
5. 任一数据源测试失败时，页面显示明确失败原因且不破坏其他数据源配置。
6. 现有 ETF 轮动、股息率、资金流向、五年之锚和红利研究功能回归测试不受影响。
