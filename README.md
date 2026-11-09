# ETF Market Dashboard

Python + AkShare + ECharts dashboard for comparing the 300 dividend ETF, 300 growth ETF, and HS300 ETF.

## Local use

Install the CLI and dependencies:

```powershell
python -m pip install -r requirements.txt
python -m pip install https://www.nffund.com/wxfiles/miniapp/openu/static/assets/etfirst/0.4.2/etfirst-0.4.2.tar.gz
etfirst auth login --api-key <YOUR_KEY>
python -m scripts.update_data
```

Start the local FastAPI site from the repository root:

```powershell
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000/web/`.

## Update workflow

The GitHub workflow is retained only as a scheduled/test reference. GitHub Pages publication is disabled; the supported deployment target is the local FastAPI process above.

## Benchmark behavior

The default benchmark is 2025-12-31. The date picker accepts any date. If the selected date is not a trading day, the dashboard uses the latest trading date not after the selection and shows the actual date used.

## Data and security

The frontend reads a pinned snapshot through the local API. SQLite, raw evidence and backups are not statically exposed. Missing prices remain missing and are not converted to zero.

## Wind MCP history validation

The three ETF price histories (512530, 562310, 510330) are sourced exclusively from AkShare. Incremental ETF updates re-fetch the trailing seven calendar days so provider corrections replace recent stored values; daily close changes above 20% block publication for review. Index histories retain their existing ETFirst-first/AkShare-fallback process. Wind Alice can be used as an independent source to compare historical index points. The validator is read-only and writes discrepancy reports under `reports/wind/`; it does not repair SQLite or published JSON.

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
