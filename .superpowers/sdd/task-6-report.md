# Task 6：统一 Wind provider 公共别名

## 变更

- 在 `scripts/credential_settings.py` 的 `normalize_provider` 中增加 `wind` 到 canonical provider `wind_mcp` 的别名映射。
- 保留已有 `htbr` 到 `htbr_etf` 的别名行为不变。
- 增加凭证服务测试，验证 `wind` 使用现有 `WIND_MCP_AUTH` 账户，并返回 canonical `wind_mcp`。
- 增加设置 API 测试，验证 `/api/settings/credentials/wind` 保存后返回 `wind_mcp`，且不返回凭证内容。
- 测试隔离本机 Wind 环境变量，避免本地凭证干扰测试结果。

## 验证

执行：

```text
python -m pytest tests/test_credential_settings.py tests/test_settings_api.py -q
node --check web/settings.js
```

结果：`34 passed`；Node 语法检查通过。pytest 仅有项目环境中既有的 pandas 可选依赖版本警告。

## 安全与范围

- API 和服务仍只返回 canonical provider/status，不返回任何明文凭证。
- 未修改 `data/etf_market.db`。
- 未输出或写入真实凭证。
