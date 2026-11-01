from pathlib import Path


def test_dashboard_navigation_is_grouped():
    html = (Path("web") / "index.html").read_text(encoding="utf-8")
    assert "data-dashboard-navigation" in html
    assert 'src="navigation.js' in html
    assert 'src="app.js' in html


def test_dashboard_navigation_supports_collapsing_sections():
    script = (Path("web") / "navigation.js").read_text(encoding="utf-8")
    assert 'document.querySelectorAll("[data-sidebar-toggle]")' in script
    assert "target.hidden = expanded" in script
