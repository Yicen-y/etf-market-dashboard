from pathlib import Path


def test_dashboard_navigation_is_grouped():
    html = (Path("web") / "index.html").read_text(encoding="utf-8")
    assert "投资分析看板" in html
    assert 'data-sidebar-toggle="rotation-items"' in html
    assert 'data-sidebar-toggle="dividend-items"' in html
    assert "沪深300 ETF资金流向" in html
    assert "styles.css?v=20261101-4" in html
    assert "app.js?v=20261101-8" in html
    assert 'href="/web/dividend.html?type=ETF"' in html
    assert 'href="/web/dividend.html?type=STOCK"' in html


def test_dashboard_navigation_supports_collapsing_sections():
    script = (Path("web") / "app.js").read_text(encoding="utf-8")
    assert 'document.querySelectorAll("[data-sidebar-toggle]")' in script
    assert "target.hidden=expanded" in script
