# ETF Market Dashboard

## V2 工程升级状态

数据中心：`/web/data-center.html`；只读诊断 API：`/api/data-center`。支持以 `ETF_DATA_DIR` 指定独立持久数据目录，未设置时仍使用仓库内 `data/`。新异步更新入口 `/api/jobs/update` 返回 job ID；原 `/api/update` 保持兼容。所有写接口仅允许本机对等端访问，公开反向代理仍须另行设置访问控制。

14 条指数核验收敛、逐日证据、数据中心扩展与增量运行命令见 [2026-11-15 交付记录](docs/verification-delivery-20261115.md)。每日参考检查可先运行 `python -m scripts.daily_verified --verify-only --overlap-days 7`；正常日程使用 `python -m scripts.daily_verified --overlap-days 7`，新增或变化的指数点位仍受参考证据门禁约束。

代码包、备份和 Linux 部署步骤见 [V2 部署说明](docs/engineering-v2/04-deployment.md)；[测试报告](docs/engineering-v2/05-test-report.md) 列出已通过和未完成的验收项。当前 V2 尚未通过完整验收，不能将离线测试视为真实行情已核验。

Windows 本地隔离发布、26 条系列状态、14 条指数遗留异常及浏览器截图见 [2026-11-16 Windows 验收记录](docs/engineering-v2/windows-local-acceptance-20261116.md)。

Python + AkShare + ECharts dashboard for comparing the 300 dividend ETF, 300 growth ETF, and HS300 ETF.

## Local use

Install the dependencies from the repository root:

```powershell
python -m pip install -r requirements.txt
python -m pip install https://www.nffund.com/wxfiles/miniapp/openu/static/assets/etfirst/0.4.2/etfirst-0.4.2.tar.gz
```

Start the local FastAPI site from the repository root:

```powershell
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000/web/` for the dashboard, or open
`http://localhost:8000/web/settings.html` for local data-source credentials.

### Local credential settings

The settings page supports Wind MCP, 华泰柏瑞 ETF, 南方 ETFirst and 同花顺 iFinD.
On Windows, install the `keyring` dependency from `requirements.txt`,
open the settings page, enter one provider credential at a time, and select
`保存凭证`. The value is stored in Windows Credential Manager and is never
returned by the API or written to browser storage, URLs, SQLite, static JSON,
or application logs. The page only shows whether a credential is configured.

Use `测试连接` after saving. A successful Wind test verifies the MCP handshake
and tool discovery. ETFirst and 华泰柏瑞 currently report a local configuration
check unless their installed provider CLI exposes a remote verification command;
that status is deliberately not presented as a successful remote connection.

To remove a credential, select `删除凭证` on the same provider card. This
deletes only that provider's entry from Windows Credential Manager. If the
server is restarted, the configured status is loaded again from the credential
manager. Do not put keys in source files, query strings, `localStorage`, or
shell history. For one-session compatibility overrides, the existing
`WIND_MCP_AUTH`, `WIND_MCP_TOKEN`, `HTBR_ETF_API_KEY`, and `ETFIRST_API_KEY`
environment variables remain supported, but the settings page is the preferred
local workflow.

After configuring the providers, run the existing refresh command when needed:

```powershell
python -m scripts.update_data
```

### iFinD index history

Get an iFinD HTTP `refresh_token` from the official SuperCommand client or its
web account page, then save it on the local settings page under 同花顺 iFinD.
The credential stays in Windows Credential Manager. `IFIND_REFRESH_TOKEN` is
also supported as a process-only override. The connection test exchanges the
refresh token for an access token without returning either token to the browser.

To fetch index history, supply the dashboard's local index code and the
**verified** iFinD symbol (including its exchange suffix):

```powershell
python -m scripts.ifind index H00300 <verified-ifind-symbol> 20261101 20261118
```

The command prints JSON rows (`tradeDate`, `indexCode`, `closeValue`) plus a
raw-response SHA-256. The iFinD symbol must be checked for the intended price
or total-return series. Fetched rows are candidates and are not written to the
database or published dashboard snapshots. The regular refresh still uses its
existing index sources.

The local API also accepts `POST /api/ifind/index-history` with JSON fields
`index_code`, `ifind_code`, `start_date`, and `end_date`. It returns the same
candidate rows and digest; this endpoint is limited to local callers.
The settings page provides an **iFinD 指数取数测试** form for this endpoint. Enter
the verified code mapping and a date range to preview the latest ten returned
rows and the raw-response digest without publishing data.

## Update workflow

### Industry total-return index archive

The 17 CSI industry total-return series requested in November 2026 are stored
in `data/etf_market.db` under `industry_total_return_indices`,
`industry_total_return_prices`, and `industry_total_return_batches`. The batch
table retains each issuer response and its SHA-256. This archive is separate
from the dashboard's published `index_prices` and snapshot files.

To incrementally refresh the archive through the CSI issuer endpoint after the
latest trading day is published, run:

```powershell
python -m scripts.industry_total_return_sync --end YYYYMMDD
```

Each series starts from its latest saved date minus seven calendar days, so
new observations and issuer corrections are captured without re-fetching the
entire history. Use `--overlap-days N` to adjust that window, `--full` for a
complete re-fetch from `--start`, or `--dry-run` to check without writing.
The sync validates each code, total-return identity, trading calendar, point
value and continuous coverage before starting one database transaction.
The existing `python -m scripts.daily_verified --overlap-days 7` daily command
now runs this incremental archive update as well. Its `--verify-only` mode
skips the archive write; `--industry-overlap-days N` adjusts the archive window.

### Industry rotation Prism

Open `/web/industry-rotation.html` from the “三棱镜策略 → 行业轮动” sidebar item.
The 17 tabs reuse one four-panel chart; `GET /api/industry-rotation/catalog`
lists them and `GET /api/industry-rotation/prism?code=H20596` returns the aligned
Prism rows. The industry series are CSI total-return indexes, while the local
Wind All A (`881001.WI`) series is an index level; the view labels this basis
difference and stops at the latest common trading date.

The GitHub workflow is retained only as a scheduled/test reference. GitHub Pages publication is disabled; the supported deployment target is the local FastAPI process above.

## Benchmark behavior

The default benchmark is 2025-12-31. The date picker accepts any date. If the selected date is not a trading day, the dashboard uses the latest trading date not after the selection and shows the actual date used.

## Data and security

The frontend reads a pinned snapshot through the local API. SQLite, raw evidence and backups are not statically exposed. Missing prices remain missing and are not converted to zero.

The supported current-data boundary is `data/current_manifest.json` plus its two
immutable files under `data/releases/`. Read the manifest once and use both
referenced files for one analysis. API clients can pin `snapshot_id` on
`/api/snapshot/data/{dataset_name}` or `/api/snapshot/index-view`; after a
pointer change, requests pinned to the previous ID receive HTTP 409 and should
fetch `/api/snapshot` again. Retained release files remain available for
rollback. The root-level
`data/etf_prices.json` and `data/index_prices.json` are legacy archival files,
not live current-data endpoints. They are no longer rewritten on publication
because two separate file replacements cannot switch one dataset atomically.

## Wind MCP history validation

The three ETF price histories (512530, 562310, 510330) are sourced through AkShare with Eastmoney as the locked primary upstream. If Eastmoney fails, AkShare's Sina response is archived as a candidate with a blocking quality issue; it is not published until its price basis and overlapping history are independently verified. Incremental ETF updates re-fetch the trailing seven calendar days. Index histories retain their existing ETFirst-first/AkShare-fallback process and require further basis reconciliation. Wind Alice can compare historical index points. The validator is read-only and writes discrepancy reports under `reports/wind/`; it does not repair SQLite or published JSON.

AkShare remains the ETF collector (Eastmoney first, Sina on transport failure). A Sina candidate can now pass when its archived payload exists and the configured Huatai-PineBridge `fund-daily-quote` feed returns the same unadjusted exchange close for every candidate date, with at least five dates and price/interval-return differences at most 0.5%. The independent response is archived with its digest. If the feed is unavailable or prices conflict, the candidate remains quarantined and the data center lists its price and issue. A local reviewer may enter an evidence ID in the data center to approve the exact archived candidate digest; the next refresh still runs structural checks before publication. The existing reviewed `data/source_policy.json` + hash-verified Eastmoney overlap gate remains available. AkShare supplies a DataFrame, so the stored payload is a serialization of that returned table, not the original HTTP response. ETFirst's historical `getReturnTrendList.closePrice` is a fund NAV and is never used to confirm exchange closes.

`GET /api/live` checks process availability, `/api/ready` validates the database and current ETF/index snapshot, and `/api/freshness` reports the latest observed dates separately. `/api/health` retains its previous fields and adds `healthState`, `checks`, and `freshness`. `GET /api/provenance/{kind}/{symbol}/{trade_date}` exposes the local canonical-to-raw link when one is recorded; missing historical evidence is reported as unknown.

For a read-only storage and cleanup preview, run `python -m scripts.storage_audit`. The output groups current, rollback, backup, raw-evidence and temporary files; it never deletes data.

Store the Wind credential in Windows Credential Vault (the prompt does not echo input):

```powershell
python -m scripts.wind_credentials set
python -m scripts.wind_credentials check
```

The local API reads this credential from Windows Credential Vault. It is never written to the repository, SQLite, logs or API responses. `GET /api/wind/status` reports whether a credential is configured without returning its value. For one-session overrides, `WIND_MCP_AUTH` or `WIND_MCP_TOKEN` can still be set in the server process environment.

After checking the account's actual tool schema, call a tool by explicitly supplying its name, JSON arguments, date/close output fields and a reviewed local-to-Wind code mapping. `arguments-json` supports `${wind_code}`, `${local_code}`, `${start}`, and `${end}` substitutions:

```powershell
python -m scripts.validate_wind --tool "<discovered tool name>" --arguments-json '{"<actual code parameter>":"${wind_code}","<actual start parameter>":"${start}","<actual end parameter>":"${end}"}' --codes H00300 --wind-codes-json '{"H00300":"<verified Wind index code>"}' --start 20260101 --end 20261030 --date-field "<actual date field>" --close-field "<actual close field>"
```

The placeholders in the example must be replaced with names/values from `--list-tools` and a verified code/return-index definition. The tool response must contain a JSON object with a row list (default field `rows`); set `--rows-field` if the actual result uses another field. Do not assume price-return and total-return indices are interchangeable.


## Nikkei 225 five-year anchor

The temporary Nikkei series is stored separately in `data/etf_market.db` in the `nikkei225_anchor_prices` table because Tokyo trading dates must not be merged into the mainland-China index calendar. The baseline CSV is imported idempotently the first time the normal data refresh runs. Later refreshes query an overlapping tail from Wind MCP and upsert by trade date; raw MCP responses are retained under `data/raw/market/`.

Configure `WIND_MCP_TOKEN` (bearer token) or `WIND_MCP_AUTH` (full Authorization header) for the server process, then use the dashboard's “刷新全部数据” action or run `python -m scripts.update_data`. A Wind failure does not block the existing ETF/CSI snapshot. The Chinese-name source mapping and total-return status remain marked as unverified.
