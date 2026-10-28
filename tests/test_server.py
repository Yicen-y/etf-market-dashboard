from server import app


def test_server_exposes_health_endpoint():
    routes = {route.path for route in app.routes}
    assert "/api/health" in routes
    assert "/api/update" in routes
