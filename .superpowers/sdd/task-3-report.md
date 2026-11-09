# Task 3 报告：FastAPI 凭证设置接口

## 状态

已完成并提交。Task 3 的四个接口已接入现有 `scripts.credential_settings`，不返回任何凭证明文。

实现提交：`fc1dc28 feat: expose credential settings API`

## 修改文件

- `server.py`
  - 引入 `CredentialRequest` Pydantic 请求模型。
  - 增加凭证提供方白名单校验。
  - 增加状态查询、保存、删除和连接测试四个接口。
  - 连接测试结果只保留安全字段：提供方、配置状态、测试状态、远程验证标识和脱敏消息。
- `tests/test_settings_api.py`
  - 覆盖状态只读返回、保存、删除、测试、未知提供方、空凭证、测试失败和无明文泄露。

## API

```text
GET    /api/settings/credentials
PUT    /api/settings/credentials/{provider}
DELETE /api/settings/credentials/{provider}
POST   /api/settings/credentials/{provider}/test
```

支持的 `{provider}`：

- `wind_mcp`
- `htbr_etf`
- `etfirst`

保存请求格式：

```json
{"key": "用户自己的凭证"}
```

保存成功只返回：

```json
{"provider": "wind_mcp", "configured": true}
```

不会在响应、错误消息或测试结果中返回保存的 Key。未知提供方返回 `404`，空 Key 返回 `400`，提供方测试失败返回 `502`。

## 测试命令及结果

由于当前环境直接调用 `pytest` 时没有自动把项目根目录加入模块搜索路径，使用了项目根目录显式设置的 `PYTHONPATH`：

```powershell
$env:PYTHONPATH=(Get-Location).Path
pytest tests/test_settings_api.py -q
```

结果：`10 passed`。

```powershell
pytest tests/test_server.py tests/test_wind_credentials.py -q
```

结果：`7 passed`。

```powershell
python -m py_compile server.py tests/test_settings_api.py
```

结果：通过。

测试输出包含已有 pandas 依赖版本警告，但没有测试失败。

## 风险与后续事项

1. `ETFirst` 和 `HTBR` 当前凭证测试按 Task 1/2 的约定，只能诚实返回本地检查通过但未验证远程服务的 `not_verified` 状态；该状态通过 API 返回 `502`，不会误报连接成功。
2. 真实 Windows Credential Manager 的存取由现有凭证模块负责，本 Task 没有改变存储策略。
3. 本 Task 只实现后端接口，设置页面、导航入口和前端交互属于后续任务。
4. 工作区中原有的 `data/etf_market.db` 修改和计划文件未纳入本 Task 提交，已保留不动。

## Task 3 审查问题修复（追加）

针对 `task-3-review.md` 中的 I-1、I-2 已完成修复。

### I-1：provider 规范统一

- 在 `scripts.credential_settings` 增加公开的 `normalize_provider()`。
- `htbr` 兼容别名和 `htbr_etf` canonical 值统一映射为 `htbr_etf`。
- API 层改为复用该规范化函数，不再自行维护另一套 provider 枚举规则。
- API 测试覆盖 `htbr`、`htbr_etf` 两个公开值，并验证传给存储层和响应中的值均为 `htbr_etf`。

### I-2：API 边界错误脱敏

- 状态查询、保存、删除的底层异常分别固定为“凭证状态查询失败”“凭证保存失败”“凭证删除失败”。
- 连接测试异常固定返回 `502` 和安全的 `check_failed` 结果。
- 连接测试结果的 `message` 不再透传底层文本：成功、未验证和失败分别使用固定消息。
- 即使底层异常包含请求 Key、Bearer 前缀或其他敏感文本，也不会出现在 HTTP 响应中。

### 修复后的验证

执行：

```powershell
$env:PYTHONPATH=(Get-Location).Path
pytest tests/test_settings_api.py tests/test_server.py tests/test_wind_credentials.py -q
```

结果：`23 passed, 2 warnings`。

另执行：

```powershell
python -m py_compile server.py scripts/credential_settings.py tests/test_settings_api.py
git diff --check
```

结果：均通过。两个警告仍为本机 pandas 依赖版本警告，与本次功能无关。

修复提交：`97cf879 fix: unify credential providers and redact API errors`。
