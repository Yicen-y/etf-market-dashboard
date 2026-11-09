# Task 1：凭证服务与安全边界报告

## 状态

已完成。Task 1 的凭证服务、Wind CLI 委托和自动化测试已实现。

## 提交哈希

- 实现提交：`436b75b` — `feat: add local credential settings service`
- 报告文件作为独立文档提交，不改变上述实现提交哈希。

## 修改文件

- `scripts/credential_settings.py`
  - 新增 Wind MCP、华泰柏瑞 ETF、南方 ETFirst 三类凭证白名单。
  - 使用 `etf-market-dashboard` 服务名和固定账户映射。
  - 生产路径校验 Windows Credential Manager 后端，拒绝非 Windows 后端。
  - 提供 `get_credential`、`set_credential`、`delete_credential`、`list_credential_status`、`test_credential`。
  - 状态接口只返回 provider、configured、masked，不返回明文凭证。
  - 删除操作幂等；空值被拒绝。
- `scripts/wind_credentials.py`
  - 保留原有 CLI 行为。
  - Wind 凭证的读取、保存和删除委托给新服务。
  - 保留 `WIND_MCP_AUTH` / `WIND_MCP_TOKEN` 作为显式环境变量兼容覆盖。
- `tests/test_credential_settings.py`
  - 覆盖 provider 白名单、账户映射、掩码、幂等删除、Wind 读取、非 Windows 后端拒绝和明文排除。

## 运行的测试命令及输出

### TDD 红灯验证

命令：

```text
python -m pytest tests/test_credential_settings.py -q
```

结果：按预期在实现前失败，模块导入失败：`ImportError: cannot import name 'credential_settings' from 'scripts'`。

### Task 1 测试

命令：

```text
python -m pytest tests/test_credential_settings.py -q
```

输出摘要：

```text
6 passed in 0.09s
```

### Wind 凭证回归测试

命令：

```text
python -m pytest tests/test_wind_credentials.py -q
```

输出摘要：

```text
3 passed in 0.04s
```

### 相关测试集合与语法检查

命令：

```text
python -m pytest tests/test_credential_settings.py tests/test_wind_credentials.py tests/test_validate_wind_cli.py tests/test_wind_mcp_client.py -q
python -m py_compile scripts/credential_settings.py scripts/wind_credentials.py
```

输出摘要：

```text
17 passed in 2.67s
```

语法检查无输出并成功退出。

## 疑问或风险

- 当前 Task 只实现本地凭证服务和 Wind CLI 委托，尚未接入设置页面或 FastAPI 设置接口；这些属于后续任务。
- 环境变量是明确的兼容覆盖，优先级高于凭证库。使用者若设置了 `WIND_MCP_AUTH` 或 `WIND_MCP_TOKEN`，读取结果会优先采用环境变量。
- 生产环境要求 Windows Credential Manager 后端；在非 Windows 或未安装可用后端时，服务会拒绝保存，避免回退到明文存储。
- 测试使用内存 FakeKeyring 注入，不会读取、打印或保存真实凭证。
