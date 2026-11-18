import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from scripts.industry_rotation import catalog, prism


def database(tmp_path: Path) -> Path:
    path = tmp_path / "market.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE industry_total_return_indices(index_code TEXT,name TEXT,rotation_category TEXT,return_type TEXT);
        CREATE TABLE industry_total_return_prices(index_code TEXT,trade_date TEXT,close_value REAL);
        CREATE TABLE index_prices(trade_date TEXT,index_code TEXT,close_value REAL);
        CREATE TABLE wind_index_daily_prices(wind_code TEXT,trade_date TEXT,close_value TEXT,verification_status TEXT);
        INSERT INTO industry_total_return_indices VALUES('H20596','煤炭','周期','total_return');
        INSERT INTO industry_total_return_prices VALUES('H20596','20260102',1000);
        INSERT INTO industry_total_return_prices VALUES('H20596','20260106',1100);
        INSERT INTO index_prices VALUES('20121231','H00922',3000);
        INSERT INTO index_prices VALUES('20260102','H00922',4000);
        INSERT INTO index_prices VALUES('20260105','H00922',4200);
        INSERT INTO index_prices VALUES('20260106','H00922',4400);
        INSERT INTO wind_index_daily_prices VALUES('881001.WI','2026-01-02','2000','PASS');
        INSERT INTO wind_index_daily_prices VALUES('881001.WI','2026-01-05','2100','PASS');
        INSERT INTO wind_index_daily_prices VALUES('881001.WI','2026-01-06','2200','PASS');
        """)
    return path


def test_prism_uses_aligned_raw_levels_and_keeps_missing_industry_day(tmp_path):
    path = database(tmp_path)
    assert catalog(path) == [
        {"code": "H20596", "name": "煤炭", "category": "周期"},
        {"code": "H00922", "name": "中证红利全收益", "category": "红利"},
    ]
    result = prism("H20596", path)
    assert result["benchmarkCode"] == "881001.WI"
    assert result["rows"][0]["ratio"] == pytest.approx(0.5)
    assert result["rows"][1]["ratio"] is None
    assert result["rows"][2]["ratio"] == pytest.approx(0.5)
    with pytest.raises(ValueError, match="unknown"):
        prism("NOT_IN_CATALOG", path)


def test_dividend_prism_starts_with_wind_history_even_when_dividend_is_older(tmp_path):
    result = prism("H00922", database(tmp_path))
    assert result["firstTradeDate"] == "20260102"
    assert result["latestTradeDate"] == "20260106"
    assert len(result["rows"]) == 3
    assert result["rows"][0]["values"]["H00922"] == 4000
    assert result["rows"][0]["ratio"] == pytest.approx(2)


def test_api_exposes_industry_prism_and_rejects_unknown_code(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATABASE_PATH", database(tmp_path))
    client = TestClient(server.app)
    assert client.get("/api/industry-rotation/catalog").json()["industries"][0]["code"] == "H20596"
    assert client.get("/api/industry-rotation/prism?code=H20596").status_code == 200
    assert client.get("/api/industry-rotation/prism?code=H00922").status_code == 200
    assert client.get("/api/industry-rotation/prism?code=bad").status_code == 404
