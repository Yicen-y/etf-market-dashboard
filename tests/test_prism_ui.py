from pathlib import Path


def test_prism_has_shared_time_controls_and_snapshot_region():
    html = (Path("web") / "index.html").read_text(encoding="utf-8")
    for range_key in ("6m", "1y", "3y", "5y", "all"):
        assert f'data-prism-range="{range_key}"' in html
    assert 'id="prism-time-toolbar"' in html
    assert 'id="prism-snapshot"' in html
    assert 'id="prism-unlock"' in html


def test_prism_interaction_uses_shared_zoom_and_exact_date_events():
    script = (Path("web") / "app.js").read_text(encoding="utf-8")
    assert 'const PRISM_TIME_RANGE_KEY="prism-dashboard-time-range"' in script
    assert 'type:"dataZoom",start:safeStart,end:safeEnd' in script
    assert 'chart.on("updateAxisPointer",prismHandleAxisPointer)' in script
    assert 'prismIndexFromPixel(chart,event)??prismInteraction.hoverIndex' in script
    assert 'event.key==="Escape"' in script
    assert 'new Date(`${keyToIso(latest)}T00:00:00Z`)' in script


def test_all_prism_strategies_share_interactions_and_rsi_baseline():
    script = (Path("web") / "app.js").read_text(encoding="utf-8")
    assert "const PRISM_STRATEGY_IDS=new Set" in script
    assert "function isPrismDashboard()" in script
    assert "prismInteraction.labels" in script
    assert 'line("RSI 50基准线"' in script


def test_all_rotation_dashboards_share_compact_responsive_control_panel():
    styles = (Path("web") / "styles.css").read_text(encoding="utf-8")
    assert ".control-panel { box-sizing:border-box; min-width:0;" in styles
    assert "grid-template-columns:max-content minmax(0,1fr)" in styles
    assert "@media (max-width:850px)" in styles
    assert ".control-panel { display:block; flex:0 0 auto; width:100%; min-width:0; }" in styles
    assert ".prism-active .control-panel" not in styles

    html = (Path("web") / "index.html").read_text(encoding="utf-8")
    assert 'href="styles.css?v=' in html


def test_market_data_uses_one_pinned_snapshot():
    script = (Path("web") / "app.js").read_text(encoding="utf-8")
    assert 'fetchJson("/api/snapshot")' in script
    assert "activeSnapshotId=manifest.snapshot_id" in script
    assert "async function ensureDashboardData(strategy)" in script
    assert "await ensureDashboardData(window.activeDashboard)" in script
    assert "await ensureDashboardData(window.activeDashboard);render()" in script
    assert "[dataset,indexDataset]=await Promise.all([fetchJson(pinnedUrl(DATA_URL)),fetchJson(pinnedUrl(INDEX_DATA_URL))])" not in script


def test_initial_etf_load_does_not_download_full_index_snapshot():
    script = (Path("web") / "app.js").read_text(encoding="utf-8")
    init = script.split("async function init()", 1)[1].split("const benchmark=", 1)[0]
    assert "await ensureDashboardData(window.activeDashboard)" in init
    assert "Promise.all([fetchJson(pinnedUrl(DATA_URL)),fetchJson(pinnedUrl(INDEX_DATA_URL))])" not in init
    assert "dashboardNeedsIndex(strategy)" in script
    html = (Path("web") / "index.html").read_text(encoding="utf-8")
    assert 'src="app.js?v=' in html


def test_prism_chart_legend_is_above_compact_time_axis():
    script = (Path("web") / "app.js").read_text(encoding="utf-8")
    assert 'legend:{top:2,bottom:null,type:"scroll"' in script
    assert 'grid:{top:38,bottom:key==="rsi"?50:20}' in script
