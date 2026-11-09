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

## 任务级审查修复

根据 `.superpowers/sdd/task-1-review.md` 修复了两个 Important 问题：

1. 环境变量优先级：`wind_credentials.get_authorization()` 现在先读取 `WIND_MCP_AUTH` / `WIND_MCP_TOKEN`，只有环境变量为空时才初始化并访问 keyring。因此 keyring 不可用、后端异常或不支持 Windows 时，显式环境变量仍然有效；环境变量同时存在时仍优先于凭证库。
2. keyring 注入边界：凭证服务新增 `ValidatedKeyring` 包装器，公开存取操作拒绝未经验证的原始 `keyring_module`，不能通过任意对象绕过 Windows Credential Manager 校验。测试和 Wind CLI 适配器必须经过明确的包装边界。

同时修复了审查指出的重复读取问题：`list_credential_status()` 每个 provider 只读取一次凭证，再生成 `configured` 与 `masked` 字段。

新增覆盖测试：

- keyring 不可用时环境变量仍可读取；
- 环境变量优先于凭证库；
- 原始 keyring 注入不能绕过校验；
- 已验证包装器可用于测试和 CLI 适配。

### 修复后的测试命令及输出

命令：

```text
python -m pytest tests/test_credential_settings.py tests/test_wind_credentials.py tests/test_validate_wind_cli.py tests/test_wind_mcp_client.py -q
```

输出：

```text
20 passed in 2.58s
```

本次修复未输出任何真实凭证。

## 复审 I-2 与类型契约修复

针对复审指出的 `_adapter_keyring()` 绕过问题再次修复：

- `_adapter_keyring()` 现在只接受已经通过统一校验的 `ValidatedKeyring`，传入任意未验证对象会立即拒绝。
- `_backend()` 继续拒绝原始 `keyring_module`，生产公共存取路径不能通过包装器绕过 Windows Credential Manager 校验。
- 新增导出的 `CredentialStatus` `TypedDict`，只包含 `provider`、`configured`、`masked` 三个不含明文的字段；`list_credential_status()` 使用该类型标注。
- 补充回归测试，验证未验证 fake backend 不能通过直接注入或适配器入口进入服务，并验证状态类型不包含凭证明文字段。
- 旧 Wind CLI 测试改为显式使用测试包装器，生产适配器不再自动包装任意对象。

### 本次复审修复测试

命令：

```text
python -m pytest tests/test_credential_settings.py tests/test_wind_credentials.py tests/test_validate_wind_cli.py tests/test_wind_mcp_client.py -q
```

输出：

```text
21 passed in 2.66s
```

本次修复未输出任何真实凭证。
