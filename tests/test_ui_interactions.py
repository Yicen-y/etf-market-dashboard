from pathlib import Path


WEB = Path("web")


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_trade_tables_are_collapsed_with_accessible_controls():
    html = read("index.html")
    for toggle, region in (("toggle-main-table", "main-table-region"), ("toggle-prism-table", "prism-table-region")):
        assert f'id="{toggle}"' in html
        assert f'aria-controls="{region}"' in html
        assert f'id="{region}"' in html
    assert html.count('aria-expanded="false"') >= 2


def test_strategy_switch_updates_url_without_losing_local_preferences():
    script = read("app.js")
    assert "history.replaceState" in script
    assert "?strategy=" in script
    assert "localStorage.setItem(PRISM_TIME_RANGE_KEY" in script
    assert "saveBenchmark(window.activeDashboard)" in script


def test_main_and_fund_flow_charts_support_non_recalculating_zoom():
    app = read("app.js")
    flow = read("fund-flow.js")
    assert 'type:"inside",filterMode:"none"' in app
    assert 'type: "inside", filterMode: "none"' in flow


def test_prism_observation_state_distinguishes_locking():
    html = read("index.html")
    script = read("app.js")
    assert "当前观察日" in html
    assert "未锁定" in html
    assert "已锁定" in script
    assert 'event.key==="Escape"' in script


def test_dividend_sort_label_matches_code_sort_implementation():
    html = read("dividend.html")
    script = read("dividend.js")
    assert "按TTM排序" not in html
    assert "按代码" in html
    assert "localeCompare" in script
