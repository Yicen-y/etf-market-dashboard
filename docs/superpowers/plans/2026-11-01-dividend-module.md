# Dividend Module Incremental Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the dividend ETF/stock business inside the existing FastAPI dashboard without changing rotation, prism, or fund-flow behavior.

**Architecture:** Add a self-contained `scripts/dividend` domain with Decimal-only pure calculations, SQLite repositories/migrations, immutable raw evidence and revision tables, and FastAPI routes. Add small dividend page views mounted from the existing second-level placeholders; leave existing navigation and charts intact.

**Tech Stack:** Python 3.9-compatible standard library, FastAPI, sqlite3, Decimal, pytest, existing vanilla HTML/CSS/JS.

## Global Constraints

- Local single-user app; no accounts, cloud sync, order placement, or new top-level navigation.
- Unknown or incomplete source coverage returns `null` plus a reason; never display missing values as zero.
- All raw source records are immutable and hashable; economic events and announcement revisions are separate.
- Production calculations are pure and independent from HTTP, database, and provider response objects.
- Existing rotation, prism, and fund-flow APIs, calculations, charts, CSVs, and data remain unchanged.

### Task 1: R0 audit and protection

**Files:** `docs/dividend/R0_audit.md`, `docs/dividend/implementation_status.md`, `data/etf_market.db.r0-20261101-005710.bak`

- [x] Record real stack, routes, database tables, navigation placeholders, changed-worktree warning, backup path, and baseline `python -m pytest -q` result.
- [x] Record that navigation is already present but dividend placeholders have no route.

### Task 2: D0 domain and SQLite ledger

**Files:** create `scripts/dividend/domain.py`, `scripts/dividend/db.py`, `scripts/dividend/__init__.py`, `tests/dividend/test_domain.py`, `tests/dividend/test_db.py`.

- [ ] Test event normalization, deduplication, revision promotion, 10-unit conversion, Decimal calculations, coverage blocking, and corporate-action adjustment.
- [ ] Implement pure functions `calculate_ttm`, `calculate_annual_reference`, `calculate_forward_groups`, `normalize_cash_amount`, and `adjust_for_actions`.
- [ ] Implement additive SQLite schema for securities, watchlist, quotes, events, revisions, source documents, raw records, actions, and verification runs.

### Task 3: D0 reference calculator and fixtures

**Files:** create `tests/dividend/reference_calculator.py`, `tests/dividend/fixtures.py`, `tests/dividend/test_reference_calculator.py`, `reports/dividend/D0_acceptance.md`.

- [ ] Keep reference arithmetic independent from production functions.
- [ ] Include the fixed 510880 unit/date fixture and synthetic split property fixture; mark unavailable official 600519/real action documents as limitations unless fetched and verified.

### Task 4: D1 API and local fixtures

**Files:** create `scripts/dividend/api.py`, `scripts/dividend/service.py`, `data/dividend/seed.json`, modify `server.py`, add `tests/dividend/test_api.py`.

- [ ] Add type-filtered search, idempotent watchlist CRUD, detail yields/events, calendar, history, and explicit sync status endpoints.
- [ ] Seed only clearly labeled local evidence fixtures; no fake precise dividend yield is emitted when coverage is incomplete.

### Task 5: D1 ETF/stock pages

**Files:** create `web/dividend.html`, `web/dividend.js`, modify `web/index.html`, `web/app.js`, `web/styles.css`.

- [ ] Replace only the two existing dividend placeholder spans with links to the shared page using `?type=ETF|STOCK`.
- [ ] Keep search visible, isolate type, show default watchlist, details, source/quality status, and add/remove actions.

### Task 6: D2/D3 and regression gates

- [ ] Add sorting, batch refresh state, 90-day confirmed-date calendar, and 1Y/3Y/5Y TTM history after D0/D1 pass.
- [ ] After every phase run dividend tests and `python -m pytest -q`; record failures and limitations in status/acceptance reports.
