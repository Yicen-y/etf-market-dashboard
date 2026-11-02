# Wind MCP Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local Wind Alice Streamable HTTP MCP client and read-only historical index comparison workflow for all configured rotation strategy legs.

**Architecture:** Keep Wind verification as an independent source adapter. A small MCP transport client handles protocol/session details; a validator normalizes tool output and compares it against SQLite and the published JSON without mutating market data; a CLI discovers tools and runs explicitly configured queries. Credentials come only from environment variables.

**Tech Stack:** Python, `requests`, SQLite, pytest, local mock HTTP server.

## Global Constraints

- Official endpoint: `https://mcp.wind.com.cn/vserver_wind_tools/mcp/`.
- Transport: Streamable HTTP; authentication is the `Authorization` header from the Wind Alice one-click configuration.
- Wind is a validation source; ETFirst/AKShare remain the routine incremental sources.
- Do not fabricate Wind tool names, argument schemas, Wind instrument mappings, or index values.
- Do not interpolate or forward-fill missing observations.
- The default command is read-only and never updates canonical prices or published JSON.
- Never write Authorization values, MCP session identifiers, or secrets to logs, reports, SQLite, or Git.
- No test may call the real Wind service or consume Wind account quota.

---

## File Structure

- Create `scripts/wind_mcp_client.py`: MCP HTTP protocol, session lifecycle, tool discovery and invocation.
- Create `scripts/wind_validator.py`: response normalization, local data loading, comparison and report serialization.
- Create `scripts/validate_wind.py`: CLI for listing tools and running configured comparisons.
- Create `scripts/wind_config.py`: endpoint, environment variable names, local index-to-Wind mapping and query selection; unmapped instruments remain explicit.
- Create `tests/test_wind_mcp_client.py`: protocol behavior against a mock server.
- Create `tests/test_wind_validator.py`: normalization, date alignment and discrepancy classifications.
- Create `tests/test_validate_wind_cli.py`: CLI validation and secret-safe reports.
- Modify `requirements.txt` only if `requests` is not a declared direct dependency.
- Add `reports/wind/.gitkeep` only if reports directory is needed; add report outputs to `.gitignore`.
- Create `docs/superpowers/specs/2026-11-02-wind-mcp-validation-design.md` (approved design).

## Task 1: MCP transport and discovery

**Files:** `scripts/wind_mcp_client.py`, `tests/test_wind_mcp_client.py`

**Interfaces:**
- `WindMcpClient(endpoint: str, authorization: str, timeout: float = 30.0)`
- `initialize() -> dict`
- `list_tools() -> list[dict]`
- `call_tool(name: str, arguments: dict) -> dict`
- `close() -> None`

- [ ] Write mock-server tests for initialize JSON-RPC request, protocol headers, session ID capture, and initialized notification.
- [ ] Write mock-server tests for paginated or single `tools/list`, `tools/call` JSON response, SSE `text/event-stream` response, MCP error object, HTTP auth failure, timeout, and missing session.
- [ ] Run `pytest tests/test_wind_mcp_client.py -q`; confirm tests fail before implementation.
- [ ] Implement JSON-RPC request IDs, `MCP-Protocol-Version`, `Accept: application/json, text/event-stream`, optional `Mcp-Session-Id`, JSON response parsing, and SSE event extraction.
- [ ] Load Authorization from constructor input only; redact it in raised errors and ensure request/response diagnostics exclude headers and session IDs.
- [ ] Run `pytest tests/test_wind_mcp_client.py -q`; all protocol cases pass.

## Task 2: Explicit Wind query and symbol mapping configuration

**Files:** `scripts/wind_config.py`, `tests/test_wind_validator.py`

**Interfaces:**
- `load_wind_config(environ: Mapping[str, str]) -> WindConfig`
- `WindIndexMapping(local_code: str, wind_code: str | None, name: str, index_type: str | None)`
- `WindConfig(endpoint: str, authorization: str | None, mappings: dict[str, WindIndexMapping], query_tool: str | None, query_arguments: dict)`

- [ ] Test the official endpoint default and environment override.
- [ ] Test that missing `WIND_MCP_AUTH` is a clear configuration error for querying but tool-list mode can report that auth is required without displaying any secret.
- [ ] Test all index codes from `scripts.config.INDEXES` appear in the mapping table and unmapped/ambiguous entries remain `None` rather than guessed.
- [ ] Test index types distinguish price-return and total-return series where known; unknown type is reported as `UNVERIFIED_TYPE`.
- [ ] Implement config loading for `WIND_MCP_URL`, `WIND_MCP_AUTH`, selected tool name/arguments, and a reviewed mapping table.
- [ ] Run targeted tests.

## Task 3: Normalize Wind results and compare against local facts

**Files:** `scripts/wind_validator.py`, `tests/test_wind_validator.py`

**Interfaces:**
- `normalize_wind_rows(payload: dict, mapping: WindIndexMapping) -> list[dict]` where each row is `{indexCode, tradeDate, closeValue}`.
- `load_local_index_rows(database_path: Path, start_date: str, end_date: str) -> dict[tuple[str, str], float]`.
- `compare_index_rows(local_rows: Mapping, wind_rows: Sequence, *, abs_tolerance: float = 0.0, rel_tolerance: float = 0.0) -> list[dict]`.
- statuses: `MATCH`, `LOCAL_MISSING`, `WIND_MISSING`, `VALUE_MISMATCH`, `INVALID_RESPONSE`, `UNMAPPED`, `UNVERIFIED_TYPE`.

- [ ] Test accepted explicit date/close field mappings and reject missing, malformed, duplicate, non-finite, non-positive, or ambiguous rows.
- [ ] Test exact date-key joins and confirm missing rows remain missing without interpolation or forward fill.
- [ ] Test each discrepancy status, zero tolerance, configured nonzero tolerance, and close values at different precision.
- [ ] Test that the comparison cannot mutate the database or published JSON.
- [ ] Implement local DB read-only query and validator comparison records including local/Wind values, absolute/relative delta, source metadata, and verification status.
- [ ] Run targeted tests.

## Task 4: CLI, report output, and credential safety

**Files:** `scripts/validate_wind.py`, `tests/test_validate_wind_cli.py`, `.gitignore`, `README.md`

- [ ] Test `--list-tools` output includes tool names/descriptions/input schemas and never credentials or session IDs.
- [ ] Test query mode refuses to guess a tool or output schema when no explicit validated configuration is supplied.
- [ ] Test report JSON/CSV contains endpoint hostname, selected tool, date range, index mapping, request timestamp, row totals and discrepancies, but no Authorization, raw session ID, or token.
- [ ] Test report filenames and generated directory are ignored by Git.
- [ ] Implement CLI options: `--list-tools`, `--tool`, `--arguments-json`, `--codes`, `--start`, `--end`, `--format json|csv`, and `--output-dir`.
- [ ] Implement report-only execution and nonzero exit status when discrepancies or unverified mappings are present; do not add a write/repair command in this scope.
- [ ] Add README instructions to set `$env:WIND_MCP_AUTH` in PowerShell, run tool discovery, then run a first one-index smoke test using the schema returned by the user's authorized Wind service.
- [ ] Run CLI tests.

## Task 5: Local verification and handoff

**Files:** all files from Tasks 1-4.

- [ ] Run `pytest tests/test_wind_mcp_client.py tests/test_wind_validator.py tests/test_validate_wind_cli.py -q`.
- [ ] Run `python -m scripts.validate_wind --list-tools` only when `WIND_MCP_AUTH` is present; otherwise verify its safe missing-auth guidance without contacting Wind.
- [ ] Run `python -m scripts.validate_wind --help` and confirm all documented flags match.
- [ ] Review `git diff --check` and `git status --short`; preserve all pre-existing user modifications and do not stage or commit unrelated files.
- [ ] Report actual mock test results and whether a live Wind smoke test ran. Never describe a mock test as Wind validation.

## Execution Notes

After `tools/list` succeeds, inspect the actual authorized Wind tool schema and configure the historical index-point query plus output-field mapping. If the user's current entitlement does not expose the needed history tool, the implementation should report that limitation and still retain tool discovery and the mock-verified comparison pipeline. A real comparison cannot be claimed until Wind returns actual rows for mapped instruments.
