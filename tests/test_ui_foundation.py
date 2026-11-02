from pathlib import Path


WEB = Path("web")


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_all_pages_load_shared_theme_components_and_navigation():
    for page in ("index.html", "fund-flow.html", "dividend.html"):
        html = read(page)
        assert 'href="theme.css' in html
        assert 'href="ui-components.css' in html
        assert 'src="navigation.js' in html
        assert "data-dashboard-navigation" in html


def test_theme_contains_required_design_tokens():
    css = read("theme.css")
    required = {
        "--bg: #f5f7fb",
        "--surface: #ffffff",
        "--text-primary: #172033",
        "--text-secondary: #64748b",
        "--border: #e2e8f0",
        "--primary: #2c6bed",
        "--primary-bg: #edf3ff",
        "--positive: #c9362b",
        "--negative: #16834a",
        "--page-max-width: 1600px",
        "--sidebar-width: 232px",
        "--radius-card: 12px",
        "--control-height: 36px",
    }
    normalized = css.lower()
    assert required.issubset({line.strip().rstrip(";") for line in normalized.splitlines()})
    assert "font-variant-numeric: tabular-nums" in normalized


def test_navigation_has_all_business_entries_and_accessible_toggles():
    script = read("navigation.js")
    for strategy in (
        "dividend-growth",
        "prism",
        "dividend-hs300",
        "growth-value-300",
        "csi2000-hs300",
        "nonferrous-chemical",
        "banks-exbank-financial",
        "dividend-growth-300",
        "dividend-a-share",
    ):
        assert strategy in script
    assert "ETF股息率" in script
    assert "股票股息率" in script
    assert "沪深300 ETF资金流向" in script
    assert "aria-expanded" in script


def test_dividend_page_has_no_embedded_theme_styles():
    html = read("dividend.html")
    assert "<style" not in html
    assert 'href="dividend.css' in html


def test_shared_status_contract_distinguishes_business_states():
    css = read("ui-components.css")
    for state in ("normal", "stale", "incomplete", "invalid", "building", "loading", "error"):
        assert f'.ui-status[data-state="{state}"]' in css
