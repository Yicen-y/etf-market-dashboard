from server import app, health


def test_server_exposes_health_endpoint():
    routes = {route.path for route in app.routes}
    assert "/api/health" in routes
    assert "/api/update" in routes
    assert "/data" in routes


def test_health_contract_includes_refresh_summary():
    response = health()
    assert "summary" in response
