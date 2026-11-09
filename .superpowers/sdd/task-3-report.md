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
