from pathlib import Path


WEB = Path("web")


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_soft_bento_theme_tokens_are_available():
    css = read("theme.css")
    for token in (
        "--surface-soft:",
        "--surface-raised:",
        "--primary-strong:",
        "--radius-control: 10px",
        "--radius-card: 16px",
        "--control-height: 44px",
        "--shadow-raised:",
    ):
        assert token in css


def test_navigation_exposes_product_and_group_hierarchy():
    script = read("navigation.js")
    assert "sidebar-kicker" in script
    assert "sidebar-group-label" in script
    assert "投资分析看板" in script
    assert "股息率监测" in script
    assert "沪深300 ETF资金流向" in script


def test_rotation_page_uses_bento_layout_hooks():
    html = read("index.html")
    for class_name in ("bento-hero", "bento-toolbar", "bento-grid", "bento-panel"):
        assert class_name in html


def test_mobile_drawer_and_touch_targets_are_supported():
    css = read("ui-components.css")
    assert "min-height: var(--control-height)" in css
    assert ".strategy-sidebar.mobile-nav-open::before" in css
    assert "@media (max-width: 900px)" in css

