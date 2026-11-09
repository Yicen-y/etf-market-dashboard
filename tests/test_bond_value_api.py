from fastapi.testclient import TestClient

import server


def test_bond_value_endpoint_returns_explicit_empty_state(monkeypatch):
    monkeypatch.setattr("scripts.bond_value.api.load_payload", lambda: {"status": "EMPTY", "rows": []})
    response = TestClient(server.app).get("/api/bond-value/hs300")
    assert response.status_code == 200
    assert response.json() == {"status": "EMPTY", "rows": []}


def test_bond_value_refresh_surfaces_provider_error(monkeypatch):
    def fail():
        raise RuntimeError("Wind权限不可用")

    monkeypatch.setattr("scripts.bond_value.api.refresh", fail)
    response = TestClient(server.app).post("/api/bond-value/refresh")
    assert response.status_code == 503
    assert "Wind权限不可用" in response.json()["detail"]
