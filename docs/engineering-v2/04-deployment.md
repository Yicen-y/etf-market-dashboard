# 代码与数据分离部署

本地开发默认仍读仓库 `data/`。服务器须先把现有真实数据**人工核对并迁移**到独立持久目录，再将 `ETF_DATA_DIR` 设置为该绝对路径。不能用本地旧 `.db` 或 JSON 覆盖服务器可能较新的数据；首次迁移前先用 `python -m scripts.backup_db --target <新的备份路径>` 创建一致性 SQLite 备份，核对 Manifest、release 引用与权限。

Windows 代码包示例（输出放仓库外）：

```powershell
python -m scripts.package_code D:\deploy\etf-code.zip
```

此包只含 `server.py`、`scripts/`、`web/`、README 和 requirements；`scripts/seeds/source_events/` 内保留一份经审阅的份额折算元数据种子，运行时若独立数据目录有更新版本则优先读外部文件。包不含 `data/`、密钥及备份。通过经授权的文件传输方式上传后，Linux 在已准备 `ETF_DATA_DIR` 和服务单元的条件下先预览：

```bash
ETF_DATA_DIR=/srv/etf-data bash scripts/deploy_code.sh /tmp/etf-code.zip /opt/etf-dashboard etf-dashboard.service
```

核对目标与包后，把 `--apply` 加到末尾。脚本在 `/opt/etf-dashboard/releases/` 建新代码目录，原子切换 `current` 软链，重启服务并检查本机 `/api/ready` 及部署前后的快照 ID；失败恢复旧代码链接。它不复制、不清理持久数据。服务应以 `127.0.0.1:8000` 启动，环境配置 `ETF_DATA_DIR`；有反向代理时对所有写操作另加访问控制。

只读空间/清理预览：`python -m scripts.storage_audit`。备份采用 SQLite Backup API：`python -m scripts.backup_db --target /srv/etf-data/backups/<唯一文件名>.db`。脚本拒绝覆盖已有备份；恢复应在停服务、核实旧版快照与 DB 对应关系后另行执行。**本次未对真实服务器执行迁移、部署、恢复或清理。**

Git 当前仍跟踪大量 `data/` 运行文件；`.gitignore` 只阻止新增文件自动纳入索引，不会自动解除已跟踪项。应先确认独立数据根目录完整、服务器是否有更近版本，再审阅 `git ls-files data` 的 385 项并分批 `git rm --cached`；该操作仅修改索引，不能在未核对数据前批量执行。官方公告 PDF 测试所需的三份文件及 Manifest 已复制为 `tests/fixtures/dividend-official/`，测试改用固定 fixture，未删除原始证据。历史改写与真实数据删除不在本次范围。
