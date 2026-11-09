from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.dividend import research_api


def _client(monkeypatch, records):
    monkeypatch.setattr(research_api, "_index_rows", lambda: ({"snapshot_id": "test-snapshot"}, {"flatRecords": records}))
    app = FastAPI()
    app.include_router(research_api.router)
    return TestClient(app)


def test_regression_endpoint_returns_source_status_and_requested_mode(monkeypatch):
    records = [
        {"indexCode": "H00922", "tradeDate": f"201{i}0101", "closeValue": float(100 + i)}
        for i in range(0, 6)
    ]
    client = _client(monkeypatch, records)
    response = client.get("/api/research/dividend-regression?mode=expanding_point_in_time&fit_start=20100101&warmup=3")
    assert response.status_code == 200
    body = response.json()
    assert body["snapshotId"] == "test-snapshot"
    assert body["mode"] == "expanding_point_in_time"
    assert body["qualityStatus"] == "UNVERIFIED_SOURCE"
    assert body["rows"][0]["z"] is None


def test_regression_source_status_requires_matching_akshare_points(monkeypatch, tmp_path):
    import sqlite3
    from scripts.storage import init_database

    db = tmp_path / "index.sqlite"
    init_database(db)
    monkeypatch.setattr(research_api, "DATABASE_PATH", db)
    records = [
        {"indexCode": "H00922", "tradeDate": f"2020010{i}", "closeValue": float(100 + i * i)}
        for i in range(1, 5)
    ]
    with sqlite3.connect(db) as connection:
        connection.executemany(
            "INSERT INTO index_prices VALUES (?,?,?,?,?)",
            [(r["tradeDate"], "H00922", r["closeValue"], "AkShare", "now") for r in records],
        )
    client = _client(monkeypatch, records)
    url = "/api/research/dividend-regression?fit_start=20200101"
    verified = client.get(url).json()
    assert verified["qualityStatus"] == "AKSHARE_SOURCED"
    assert verified["sourceProvider"] == "AkShare"
    assert verified["sampleCount"] == 4
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE index_prices SET close_value=999 WHERE trade_date='20200102'")
    assert client.get(url).json()["qualityStatus"] == "UNVERIFIED_SOURCE"


def test_ah_endpoint_explicitly_reports_missing_series(monkeypatch, tmp_path):
    monkeypatch.setattr(research_api, "DATABASE_PATH", tmp_path / "empty.sqlite")
    client = _client(monkeypatch, [])
    response = client.get("/api/research/dividend-ah")
    assert response.status_code == 200
    assert response.json()["qualityStatus"] == "MISSING_SERIES"
    assert response.json()["rows"] == []


def test_ah_backtest_exposes_four_theoretical_comparisons_and_cost_parameter(monkeypatch):
    from datetime import date, timedelta
    records = []
    for i in range(46):
        day = (date(2024, 1, 1) + timedelta(days=i)).strftime("%Y%m%d")
        records.extend([
            {"indexCode": "H00922", "tradeDate": day, "closeValue": 100 + i * 2},
            {"indexCode": "H20915", "tradeDate": day, "closeValue": 100 + i},
        ])
    client = _client(monkeypatch, records)
    response = client.get("/api/research/dividend-ah-backtest?cost_bps=10")
    assert response.status_code == 200
    body = response.json()
    assert body["costBps"] == 10
    assert body["assetMode"] == "theoretical_index"
    assert len(body["summary"]) == 4
    switch = next(row for row in body["summary"] if row["strategy"] == "d40_momentum_switch")
    assert switch["firstExecutionDate"] == (date(2024, 1, 1) + timedelta(days=41)).strftime("%Y%m%d")
    assert body["qualityStatus"] == "UNVERIFIED_SOURCE"


def test_official_yield_endpoint_never_substitutes_index_return_spread(monkeypatch, tmp_path):
    monkeypatch.setattr(research_api, "DATABASE_PATH", tmp_path / "empty.sqlite")
    client = _client(monkeypatch, [])
    response = client.get("/api/research/dividend-yield")
    assert response.status_code == 200
    assert response.json()["qualityStatus"] == "MISSING_OFFICIAL"
    assert response.json()["rows"] == []


def test_dividend_yield_endpoint_aligns_exact_dates_and_reports_pp(tmp_path, monkeypatch):
    from scripts.dividend import research_api
    from scripts.dividend.research_store import record_research_series

    db = tmp_path / "research.sqlite"
    csi_meta = {"provider": "AkShare", "upstream": "CSI", "unit": "%", "sourceUrl": "csi"}
    bond_meta = {"provider": "AkShare", "upstream": "ChinaBond/CCDC", "unit": "%", "sourceUrl": "ccdc"}
    days = [f"202601{n:02d}" for n in range(1, 32)]
    record_research_series(db, "CSI_DIV_YIELD2_000922", [{"tradeDate": day, "value": 4.0} for day in days], csi_meta, "csi-hash", "raw/csi")
    record_research_series(db, "CCDC_CN10Y", [{"tradeDate": day, "value": 2.0} for day in days if day != "20260120"], bond_meta, "bond-hash", "raw/bond")
    monkeypatch.setattr(research_api, "DATABASE_PATH", db)
    client = _client(monkeypatch, [])
    response = client.get("/api/research/dividend-yield?start=20260119&end=20260121")
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert rows[0]["spreadPp"] == 2.0
    assert rows[1]["spreadPp"] is None
    assert rows[1]["qualityStatus"] == "MISSING_OFFICIAL"
    assert response.json()["coverage"]["pairedCount"] == 2


def test_research_refresh_reports_partial_source_failure(monkeypatch):
    from scripts.dividend import research_api
    monkeypatch.setattr(research_api, "sync_research_sources", lambda *args: {
        "status": "PARTIAL", "sources": {"CSI_DIV_YIELD2_000922": {"status": "FAILED"}, "CCDC_CN10Y": {"status": "READY"}}})
    client = _client(monkeypatch, [])
    response = client.post("/api/research/refresh?start=20261104&end=20261104")
    assert response.status_code == 207
    assert response.json()["status"] == "PARTIAL"


def test_regression_rejects_missing_index_history(monkeypatch):
    client = _client(monkeypatch, [])
    response = client.get("/api/research/dividend-regression")
    assert response.status_code == 424
    assert response.json()["detail"]["code"] == "INSUFFICIENT_INDEX_HISTORY"


def test_research_api_rejects_snapshot_with_hash_mismatch(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    release = data_dir / "release"
    release.mkdir(parents=True)
    (release / "index_prices.json").write_text('{"flatRecords": []}', encoding="utf-8")
    (data_dir / "current_manifest.json").write_text(
        '{"snapshot_id":"broken","files":{"index":"release/index_prices.json"},'
        '"sha256":{"index":"not-the-content-hash"}}', encoding="utf-8"
    )
    monkeypatch.setattr(research_api, "ROOT", tmp_path)
    app = FastAPI()
    app.include_router(research_api.router)
    response = TestClient(app).get("/api/research/dividend-ah")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "INDEX_SNAPSHOT_UNAVAILABLE"
