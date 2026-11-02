# Unified Rotation Toolbar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every rotation dashboard use the same compact horizontal benchmark and refresh toolbar already used by prism dashboards.

**Architecture:** Keep the existing `web/index.html` control markup and JavaScript event bindings unchanged. Promote the prism-only CSS selectors to the rotation page's default control-panel selectors, while preserving the existing `850px` vertical responsive fallback.

**Tech Stack:** Static HTML, CSS, vanilla JavaScript, FastAPI local server, ECharts.

## Global Constraints

- Do not change benchmark-date resolution, refresh behavior, strategy guide behavior, chart data, or financial calculations.
- Do not change the dividend dashboard or CSI 300 ETF fund-flow dashboard.
- Desktop layout is horizontal; viewport widths at or below `850px` use a full-width vertical layout.

---

### Task 1: Unify the rotation toolbar layout and verify it visually

**Files:**
- Modify: `web/styles.css:61-66`
- Test: existing Python suite and rendered `/web/` dashboard

**Interfaces:**
- Consumes: existing `.hero`, `.control-panel`, `.hint`, `.refresh-button`, and `.guide-button` elements from `web/index.html`.
- Produces: one CSS layout shared by ordinary and prism rotation dashboards; no JavaScript interface changes.

- [ ] **Step 1: Capture the current desktop layout as the failing visual baseline**

Open `/web/`, select `300红利与300成长轮动`, and verify that the control panel is a tall right-side card rather than one compact horizontal row. Record the viewport width and screenshot outside the repository.

- [ ] **Step 2: Promote the prism-only desktop selectors**

Replace the prism-only rules with page-wide rotation rules:

```css
.hero { align-items:center; }
.control-panel {
  min-width:0;
  flex:0 1 620px;
  display:grid;
  grid-template-columns:max-content minmax(145px,1fr) minmax(170px,1.35fr) auto auto;
  align-items:center;
  gap:8px 10px;
  padding:10px 12px;
}
.control-panel label { margin:0; }
.control-panel .hint { margin:0; white-space:nowrap; }
.control-panel .refresh-button,
.control-panel .guide-button { width:auto; margin:0; padding:8px 10px; white-space:nowrap; }
```

- [ ] **Step 3: Preserve the narrow-screen vertical fallback**

Use the existing breakpoint without prism-specific selectors:

```css
@media (max-width:850px) {
  .hero { align-items:stretch; }
  .control-panel { display:block; min-width:260px; }
  .control-panel label { margin-bottom:7px; }
  .control-panel .hint { margin-top:8px; white-space:normal; }
  .control-panel .refresh-button,
  .control-panel .guide-button { width:100%; margin-top:10px; }
}
```

- [ ] **Step 4: Run static and regression checks**

Run:

```powershell
node --check web/app.js
python -m pytest -q
git diff --check -- web/styles.css
```

Expected: JavaScript check exits 0, all tests pass, and the CSS diff has no whitespace errors.

- [ ] **Step 5: Verify desktop and narrow-screen rendering**

At desktop width, verify `300红利与300成长轮动` and `成长100R与价值100R轮动三棱镜` both display the same single-row toolbar. At a width below `850px`, verify the controls stack vertically without clipping or horizontal overflow. Exercise benchmark-date input and open/close the strategy guide to confirm unchanged interaction behavior.

- [ ] **Step 6: Commit the implementation**

```powershell
git add web/styles.css
git commit -m "style: unify rotation dashboard toolbar"
```
