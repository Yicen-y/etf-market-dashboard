from pathlib import Path

from fastapi.testclient import TestClient

from server import app


def test_fund_flow_page_has_three_p0_chart_containers():
    html = (Path("web") / "fund-flow.html").read_text(encoding="utf-8")
    assert "shares-chart" in html
    assert "cumulative-flow-chart" in html
    assert "daily-flow-chart" in html
    assert "估算净申赎" in html
    assert "data-dashboard-navigation" in html
    assert 'src="navigation.js' in html
    navigation = (Path("web") / "navigation.js").read_text(encoding="utf-8")
    assert 'data-sidebar-toggle="rotation-items"' in navigation
    assert 'data-sidebar-toggle="dividend-items"' in navigation
    assert "fund-flow-link" in navigation
    assert "universe" in html
    assert "刷新全部数据" in html
    assert "返回ETF看板" not in html
    assert "fund-flow.js?v=" in html
    assert "A股ETF看板 · P0" not in html


def test_daily_flow_uses_zero_axis_bars_with_signed_flow_values():
    html = (Path("web") / "fund-flow.html").read_text(encoding="utf-8")
    script = (Path("web") / "fund-flow.js").read_text(encoding="utf-8")
    assert 'renderChart("daily", rows, "net_flow_yi", " 亿元", names, "bar")' in script
    assert 'type: chartType' in script
    assert "正值为申购/净流入，负值为赎回/净流出" in html


def test_workflow_uses_explicitly_simulated_sample():
    sample = Path("data/samples/fund_flow_demo.csv").read_text(encoding="utf-8")
    assert "SIMULATED ONLY" in sample


def test_server_has_fund_flow_routes():
    paths = {route.path for route in app.routes}
    assert "/api/fund-flow/health" in paths
    assert "/api/fund-flow/sync" in paths
