from pathlib import Path


def test_dividend_navigation_uses_clickable_links_and_fresh_app_bundle():
    html = (Path('web') / 'index.html').read_text(encoding='utf-8')
    assert 'data-sidebar-toggle="dividend-items"' in html
    assert 'href="/web/dividend.html?type=ETF"' in html
    assert 'href="/web/dividend.html?type=STOCK"' in html


def test_dividend_pages_keep_the_shared_sidebar_and_direct_entries():
    html = (Path("web") / "dividend.html").read_text(encoding="utf-8")
    flow = (Path("web") / "fund-flow.html").read_text(encoding="utf-8")
    assert "fund-flow-layout" in html
    assert 'data-sidebar-toggle="dividend-items"' in html
    assert 'data-type="ETF"' in html and 'data-type="STOCK"' in html
    assert 'href="/web/dividend.html?type=ETF"' in flow
    assert 'href="/web/dividend.html?type=STOCK"' in flow
