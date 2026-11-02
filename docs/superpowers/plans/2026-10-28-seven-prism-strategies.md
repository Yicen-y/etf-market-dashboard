# Seven Prism Strategies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the seven configured A/B index rotation dashboards to the existing A股ETF看板 while preserving independent benchmark dates, incremental updates, and the existing two dashboards.

**Architecture:** Generalize index data from the current two-index prism implementation into a strategy registry. Each strategy references two raw total-return index series and renders the same four-chart prism layout. The backend stores all series in SQLite and emits one JSON snapshot consumed by the static frontend.

**Tech Stack:** Python, FastAPI, SQLite, AkShare/ETFirst adapters, vanilla JavaScript, ECharts, pytest.

## Global Constraints

- Use the index codes supplied by the user.
- Use raw index points; do not normalize A and B independently before calculating the ratio.
- Each dashboard keeps its own benchmark date in localStorage.
- Update data incrementally from the latest stored trading date.
- Keep Chinese market colors: red for gains and green for losses.
- ETFirst is attempted first; AkShare is the fallback when the ETFirst history endpoint is unavailable.

### Task 1: Validate index data contracts

**Files:** Create `tests/test_strategy_registry.py`; modify `scripts/config.py`, `scripts/fetch_data.py`.

- [ ] Add the seven strategy definitions and all eleven unique index codes.
- [ ] Add a probe test that validates every configured code has a non-empty date/value response from the selected adapter or is explicitly marked as an unavailable source.
- [ ] Run the probe and record the actual usable source and earliest date for every code.
- [ ] Commit the registry and data-source findings.

### Task 2: Generalize SQLite and JSON index storage

**Files:** Modify `scripts/storage.py`, `scripts/update_data.py`, `data/index_prices.json`; test `tests/test_update_data.py`.

- [ ] Preserve `index_prices(trade_date,index_code,close_value,source,updated_at)` as the canonical table.
- [ ] Fetch only the day after the latest stored date per index code.
- [ ] Validate positive values, unique `(tradeDate,indexCode)` pairs, and complete strategy pairs before writing snapshots.
- [ ] Emit all configured index records and metadata in `data/index_prices.json`.

### Task 3: Generalize prism calculation

**Files:** Modify `scripts/prism_metrics.py`; test `tests/test_prism_metrics.py`.

- [ ] Expose a reusable `calculate_prism_metrics(rows, growth_code, value_code)` interface.
- [ ] Calculate raw A/B ratio, 242-day mean, symmetric mean ± 2 sample standard deviations, 40-day return spread, 242-day spread mean, RSI14, and RSI14 242-day mean.
- [ ] Keep indicators null until their full lookback windows exist.
- [ ] Add tests for symmetry, code-independent pairing, and insufficient history.

### Task 4: Convert frontend to a strategy registry

**Files:** Modify `web/index.html`, `web/app.js`, `web/styles.css`.

- [ ] Render seven new sidebar entries from the registry while retaining the existing two dashboards.
- [ ] Load the selected strategy's A/B series and render the same four vertical charts.
- [ ] Use an independent localStorage key per strategy.
- [ ] Keep data refresh, loading/error states, chart resize, tooltips, and Chinese colors working for every strategy.
- [ ] Hide the raw data tables as currently requested.

### Task 5: Verification and local handoff

- [ ] Run `python -m pytest -q` and `node --check web/app.js`.
- [ ] Run the local FastAPI service and verify `/api/health`, dashboard switching, date persistence, and refresh behavior.
- [ ] Update cache-busting versions and commit the complete feature.
