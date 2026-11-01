from pathlib import Path


WEB = Path("web")


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_chart_theme_is_loaded_before_chart_scripts():
    for page, script in (("index.html", "app.js"), ("fund-flow.html", "fund-flow.js")):
        html = read(page)
        assert 'src="chart-theme.js' in html
        assert html.index("chart-theme.js") < html.index(script)


def test_chart_theme_defines_distinct_units_and_stable_security_colors():
    script = read("chart-theme.js")
    assert "formatPercent" in script
    assert "formatPercentagePoints" in script
    assert "formatRsi" in script
    assert "formatMoneyYi" in script
    assert "securityColor" in script
    for code in ("510300", "510310", "510330", "159919"):
        assert code in script


def test_main_composite_chart_keeps_four_lines_and_one_difference_bar():
    script = read("app.js")
    render = script[script.index("function renderETF") : script.index("function renderPrism")]
    assert render.count('type:"bar"') == 1
    assert render.count("line(") == 4
    assert "formatPercentagePoints" in render
    assert "红利−成长差值" in render


def test_chart_lines_never_connect_missing_values():
    script = read("app.js")
    assert "connectNulls:false" in script
    flow = read("fund-flow.js")
    assert "connectNulls: false" in flow


def test_fund_flow_uses_adjusted_share_label_and_code_stable_color():
    html = read("fund-flow.html")
    script = read("fund-flow.js")
    assert "调整后ETF份额（万份）" in html
    assert "securityColor(code)" in script
