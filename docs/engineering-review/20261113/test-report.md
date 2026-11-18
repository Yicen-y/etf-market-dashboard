# 测试与接口核验（2026-11-13）

- 原始工程复测曾出现 351 passed、4 failed；已区分 A/H 初始成本缺陷与三个过时测试契约，并修复代码或更新契约。
- Windows：`python -m pytest -q` → **388 passed，0 failed，0 skipped**；两个本机 pandas 可选加速依赖版本警告。
- WSL Ubuntu 20.04 / Python 3.11 独立虚拟环境：相同命令 → **388 passed，0 failed，0 skipped**；一个 Starlette/AnyIO 弃用警告。依赖由 `requirements.txt` 全新安装，覆盖了实际 Linux 路径读取。
- 定向测试覆盖跨平台路径、备用源隔离与同口径比较、原始文件哈希、SQLite 事务回滚、Manifest 切换失败后恢复、现有快照/SQLite/API 同值、A/H 成本和时序。
- FastAPI TestClient 对当前快照的 `/api/health`、`/api/ready`、`/api/snapshot`、ETF/指数快照、轮动总览、五年之锚和抽样溯源接口返回 200。其他业务接口在完整测试中有独立覆盖。`/api/dividend/search` 无必填参数时返回预期的 422。
- Chrome + Playwright：七个主要页面在 1440、768、390 像素均加载成功，无 JS 页面错误和文档级横向溢出；检查导航、筛选、日期输入、表格展开、说明弹层及主复合图 4 条折线加 1 条柱状系列。截图保存在本机临时目录 `C:\Users\Yicen\AppData\Local\Temp\etf-ui-evidence\`。
- `git diff --check`、`node --check web/app.js`、`python -m compileall -q server.py scripts` 均退出 0。

未执行真实上游网络刷新，也未把旧历史记录强行补链；这样避免未经核验的金融数据被覆盖。
