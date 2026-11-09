from server import app, health


def test_server_exposes_health_endpoint():
    routes = {route.path for route in app.routes}
    assert "/api/health" in routes
    assert "/api/update" in routes
    assert "/data" not in routes
    assert "/api/snapshot" in routes
    assert "/api/snapshot/data/{dataset_name}" in routes


def test_static_data_not_exposed():
    routes = {route.path for route in app.routes}
    assert "/data/{path:path}" not in routes
    assert "/api/wind/status" in routes


def test_static_database_and_raw_files_are_not_http_resources():
    from fastapi.testclient import TestClient
    client = TestClient(app)
    assert client.get("/data/etf_market.db").status_code == 404
    assert client.get("/data/raw/dividend/evidence_manifest.json").status_code == 404


def test_health_contract_includes_refresh_summary():
    response = health()
    assert "summary" in response
    assert "snapshot_id" in response
