import io

import pytest
from fastapi.testclient import TestClient

import scripts.fund_flow.api as fund_flow_api
from server import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(fund_flow_api, "DATABASE_PATH", tmp_path / "flow.db")
    fund_flow_api._previews.clear()
    return TestClient(app)


def test_fund_flow_health_is_available(client):
    response = client.get("/api/fund-flow/health")
    assert response.status_code == 200
    assert {"latestTradeDate", "qualityState", "dataExists"}.issubset(response.json())


def test_import_preview_does_not_write(client):
    content = b"trade_date,ts_code,total_share_wan,nav,share_scope,share_date_basis\n2099-01-04,510300.SH,100000,4,on_exchange,post_close\n"
    response = client.post("/api/fund-flow/import/preview", files={"file": ("demo.csv", content, "text/csv")})
    assert response.status_code == 200
    assert response.json()["committed"] is False
    assert response.json()["rowCount"] == 1
    assert response.json()["sourceId"]


def test_import_commit_materializes_metrics(client):
    content = b"trade_date,ts_code,total_share_wan,nav,share_scope,share_date_basis\n2099-01-04,510300.SH,100000,4,on_exchange,post_close\n2099-01-05,510300.SH,100100,4,on_exchange,post_close\n"
    preview = client.post("/api/fund-flow/import/preview", files={"file": ("demo.csv", content, "text/csv")}).json()
    response = client.post("/api/fund-flow/import/commit", params={"source_id": preview["sourceId"]})
    assert response.status_code == 200
    assert response.json()["metricCount"] == 2
