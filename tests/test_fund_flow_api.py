import io

import pytest
from fastapi.testclient import TestClient

import scripts.fund_flow.api as fund_flow_api
from server import app
from scripts.fund_flow.db import init_fund_flow_schema, open_fund_flow_connection, seed_default_fund_master


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(fund_flow_api, "DATABASE_PATH", tmp_path / "flow.db")
    fund_flow_api._previews.clear()
    return TestClient(app)


def test_fund_flow_health_is_available(client):
    response = client.get("/api/fund-flow/health")
    assert response.status_code == 200
    assert {"earliestTradeDate", "historyComplete", "latestTradeDate", "qualityState", "dataExists"}.issubset(response.json())


def test_overview_returns_etf_names_for_selected_preset(client):
    response = client.get("/api/fund-flow/overview", params={"preset": "core_four"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["names"]["510300.SH"] == "华泰柏瑞沪深300ETF"
    assert payload["names"]["159919.SZ"] == "嘉实沪深300ETF"


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


def test_periodic_series_marks_intra_period_missing_code_incomplete(client, tmp_path, monkeypatch):
    db_path = fund_flow_api.DATABASE_PATH
    init_fund_flow_schema(db_path)
    seed_default_fund_master(db_path)
    with open_fund_flow_connection(db_path) as connection:
        for code, day in [("510300.SH", "2024-01-02"), ("510300.SH", "2024-01-03"), ("510310.SH", "2024-01-02")]:
            connection.execute("INSERT INTO fund_flow_etf_daily_metrics (etf_code,trade_date,shares_adj_wan,nav_adj,delta_shares_wan,net_flow_yi,cum_flow_yi,intensity_pct,calc_version,status) VALUES (?,?,?,?,?,?,?,?,?,?)", (code, day, 100, 4, 1, 0.004, 0.004, 1, "test", "PASS"))
    response = client.get("/api/fund-flow/series", params={"codes": "510300.SH,510310.SH", "start": "2024-01-01", "end": "2024-01-05", "frequency": "weekly"})
    assert response.status_code == 200
    assert response.json()["rows"][0]["status"] == "INCOMPLETE"
    assert response.json()["rows"][0]["missing_codes"] == ["510310.SH"]
