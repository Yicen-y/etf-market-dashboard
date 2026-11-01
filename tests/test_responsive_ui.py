from pathlib import Path


WEB = Path("web")


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_mobile_navigation_has_real_accessible_toggle():
    script = read("navigation.js")
    css = read("ui-components.css")
    assert "mobile-nav-toggle" in script
    assert "dashboard-nav-content" in script
    assert "aria-expanded" in script
    assert ".strategy-sidebar.mobile-nav-open .dashboard-nav-content" in css


def test_required_breakpoints_and_single_column_mobile_cards_exist():
    common = read("ui-components.css")
    styles = read("styles.css")
    flow = read("fund-flow.css")
    assert "@media (max-width: 900px)" in common
    compact_styles = styles.replace(" ", "")
    assert "@media(max-width:480px)" in compact_styles
    assert ".kpis{grid-template-columns:1fr}" in compact_styles
    assert "grid-template-columns:1fr" in flow.replace(" ", "")
    assert "overflow-x: clip" in read("theme.css")


def test_charts_resize_when_containers_change():
    assert "ResizeObserver" in read("app.js")
    assert "ResizeObserver" in read("fund-flow.js")


def test_modal_controls_and_navigation_controls_have_accessible_names():
    html = read("index.html")
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-label="关闭策略说明"' in html
    assert 'aria-controls="main-table-region"' in html
    assert 'aria-controls="prism-table-region"' in html
