from pathlib import Path


def test_dividend_navigation_uses_clickable_links_and_fresh_app_bundle():
    script = (Path("web") / "navigation.js").read_text(encoding="utf-8")
    assert 'href="./dividend.html?type=ETF"' in script
    assert 'href="./dividend.html?type=STOCK"' in script


def test_dividend_pages_keep_the_shared_sidebar_and_direct_entries():
    html = (Path("web") / "dividend.html").read_text(encoding="utf-8")
    flow = (Path("web") / "fund-flow.html").read_text(encoding="utf-8")
    assert "dashboard-layout" in html
    assert "data-dashboard-navigation" in html
    assert 'data-active-section="dividend"' in html
    assert "data-dashboard-navigation" in flow
    assert 'data-active-section="fund-flow"' in flow
