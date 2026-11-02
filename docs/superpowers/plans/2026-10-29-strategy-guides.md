# Strategy Guides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strategy-guide modal that explains every dashboard, renders the approved formulas as mathematics, and documents the prism strategy's five use cases.

**Architecture:** Keep guide content in a static JSON file so local hosting and GitHub Pages use the same source. Add one reusable modal to the existing HTML, render strategy-specific labels from the active dashboard, and call MathJax after injecting guide content.

**Tech Stack:** Static HTML/CSS/JavaScript, ECharts, MathJax 3, JSON, pytest, Node syntax checks.

## Global Constraints

- Preserve existing charts, benchmark-date behavior, refresh behavior, and strategy switching.
- Use LaTeX rendered by MathJax for every displayed formula; do not present formulas as code blocks.
- Use the five approved prism use cases and do not convert historical examples into automatic trade signals.
- Keep all guide content static and safe for GitHub Pages; no API key or backend request is added.

---

### Task 1: Add the structured guide content

**Files:**
- Create: `web/strategy-guides.json`
- Test: `tests/test_strategy_guides.py`

**Interfaces:**
- Produces `guides.etf` and `guides.prism` objects consumed by `web/app.js`.
- Each guide contains `title`, `intro`, `sections`, and `formula` strings using `\\(` / `\\)` for inline and `\\[` / `\\]` for display math.

- [ ] Add the ETF guide with the three ETF codes, cumulative-return formulas, difference, 50:50 formula, and calculation limitations.
- [ ] Add the prism guide with the three indicator descriptions, all five use cases, RSI auxiliary interpretation, formulas, and risk statement.
- [ ] Add a JSON contract test that parses the file, checks both guide types, checks the five use-case headings, and checks for LaTeX delimiters.
- [ ] Run `conda run -n QuaTra python -m pytest tests/test_strategy_guides.py -q`; expect all guide-contract tests to pass.

### Task 2: Add the guide modal and MathJax loader

**Files:**
- Modify: `web/index.html`
- Modify: `web/styles.css`

**Interfaces:**
- Adds `#strategy-guide-button`, `#strategy-guide-modal`, `#strategy-guide-title`, and `#strategy-guide-content`.
- MathJax exposes `window.MathJax.typesetPromise` for post-injection rendering.

- [ ] Add the “策略说明” button beside the data-refresh button.
- [ ] Add the modal markup with a close button, title, scrollable content area, and accessible dialog attributes.
- [ ] Load a fixed MathJax 3 `tex-svg` build with inline and display delimiters configured for `\\(...\\)` and `\\[...\\]`.
- [ ] Style the modal, formula blocks, tables, use-case labels, overlay, keyboard focus, and mobile layout without changing chart layout.
- [ ] Run `node --check web/app.js` after the JavaScript integration is complete and inspect the modal CSS selectors with `rg`.

### Task 3: Integrate active-strategy guides

**Files:**
- Modify: `web/app.js`
- Modify: `web/index.html`

**Interfaces:**
- Add `GUIDES_URL` alongside the existing data URLs.
- Add `renderStrategyGuide()` that takes the active strategy id and current `indexDataset` labels, returns guide HTML, and calls `MathJax.typesetPromise([guideContent])` when available.
- Add `openStrategyGuide()` and `closeStrategyGuide()` handlers.

- [ ] Fetch `strategy-guides.json` during `init()` using the same static-path logic as the existing data files.
- [ ] Resolve `dividend-growth` to the ETF guide and every prism strategy, including `prism`, to the prism guide.
- [ ] Replace generic A/B placeholders with `indexLabel(strategy.a)` and `indexLabel(strategy.b)` for configured prism strategies.
- [ ] Render formulas from JSON as MathJax source, then typeset after the modal becomes visible.
- [ ] Wire button click, backdrop click, close button, and Escape key without interfering with chart click handlers.
- [ ] Bump the app cache-buster in `web/index.html`.

### Task 4: Validate the complete user flow

**Files:**
- Modify: `tests/test_server.py` only if a static asset route contract is needed.

- [ ] Run `node --check web/app.js`.
- [ ] Run `conda run -n QuaTra python -m pytest -q`; expect all existing tests and guide-contract tests to pass.
- [ ] Start `python -m uvicorn server:app --host 127.0.0.1 --port 8000` and verify `/web/strategy-guides.json` returns HTTP 200.
- [ ] Verify the ETF strategy opens ETF-specific content and the prism strategies open the five-use-case content.
- [ ] Verify formulas are rendered after opening the modal, switching strategy labels does not alter formulas, and closing the modal restores the chart view.
- [ ] Verify the benchmark date, refresh button, and chart rendering still work after opening and closing the guide.
- [ ] Commit with `git add web tests && git commit -m "feat: add strategy guide modal"` after validation.
