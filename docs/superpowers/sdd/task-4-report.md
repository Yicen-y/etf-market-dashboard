# Task 4 实施报告：本地凭证设置页面

## 完成内容

- 新增 `web/settings.html`，提供 Wind MCP、华泰柏瑞 ETF、南方 ETFirst 三个凭证卡片。
- 新增 `web/settings.js`，接入凭证状态查询、保存、删除和连接测试接口。
- 新增 `web/settings.css`，沿用现有主题变量，支持桌面、平板和窄屏布局。
- 修改 `web/navigation.js`，增加“设置”入口，并仅在设置页设置 `aria-current="page"`。
- 新增 `tests/test_settings_ui.py`，覆盖页面结构、三类提供方、密码输入、操作按钮、无浏览器存储、导航激活状态等静态契约。

## 安全处理

- 页面只请求并展示 `configured` 与 `masked` 状态，不接收后端返回的明文密钥。
- 密钥只通过 HTTPS/本地 API 请求体发送给后端，不写入 `localStorage`、`sessionStorage` 或 URL 参数。
- 页面操作失败只显示通用错误，不把后端异常响应或请求内容回显到界面。
- 现有 `data/etf_market.db` 修改未加入本任务提交。

## 验证

```text
python -m pytest tests/test_settings_ui.py tests/test_dashboard_navigation.py -q
10 passed

node --check web/settings.js
passed
```

## 使用入口

启动本地 FastAPI 服务后打开 `/web/settings.html`，或从左侧导航的“设置”进入。
