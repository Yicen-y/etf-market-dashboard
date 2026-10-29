from pathlib import Path

from fastapi.testclient import TestClient

from server import app


def test_fund_flow_page_has_three_p0_chart_containers():
    html = (Path("web") / "fund-flow.html").read_text(encoding="utf-8")
    assert "shares-chart" in html
    assert "cumulative-flow-chart" in html
    assert "daily-flow-chart" in html
    assert "估算净申赎" in html


def test_workflow_uses_explicitly_simulated_sample():
    sample = Path("data/samples/fund_flow_demo.csv").read_text(encoding="utf-8")
    assert "SIMULATED ONLY" in sample


def test_server_has_fund_flow_routes():
    paths = {route.path for route in app.routes}
    assert "/api/fund-flow/health" in paths
    assert "/api/fund-flow/sync" in paths
