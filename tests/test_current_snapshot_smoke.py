"""Core routes agree on a generated offline snapshot and temporary SQLite."""
import sqlite3

from fastapi.testclient import TestClient

import server
import scripts.anchor.api as anchor_api
from scripts.storage import init_reliability_schema, publish_snapshot
from scripts.jobs import claim_job, set_job


def test_fixture_snapshot_serves_core_business_endpoints(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    data_root.mkdir()
    database = data_root / "etf_market.db"
    init_reliability_schema(database)
    with sqlite3.connect(database) as connection:
        connection.execute("""INSERT INTO etf_prices(trade_date,product_code,close_price,updated_at)
                            VALUES ('20261112','510330',1.25,'fixture')""")
    day = "20261112"
    snapshot_id = "fixture-v2"
    configs = [{"id": f"s{i}", "name": f"S{i}"} for i in range(8)]
    etf = {"snapshot_id": snapshot_id, "latestTradeDate": day,
           "records": [{"tradeDate": day, "prices": {"510330": 1.25, "512530": 1.2, "562310": 1.3}}],
           "flatRecords": [{"tradeDate": day, "productCode": "510330", "closePrice": 1.25}],
           "products": {code: {"name": code} for code in ("510330", "512530", "562310")}}
    index = {"snapshot_id": snapshot_id, "latestTradeDate": day,
             "tradingCalendar": {"dates": [day]}, "strategies": configs,
             "records": [{"tradeDate": day, "ratio": 1.0}],
             "strategyMetrics": {item["id"]: [{"tradeDate": day, "ratio": 1.0}] for item in configs},
             "flatRecords": [{"tradeDate": day, "indexCode": code, "closeValue": value}
                             for code, value in (("H20903", 100.0), ("H00922", 110.0))]}
    publish_snapshot(data_root, snapshot_id, etf, index)
    monkeypatch.setattr(server, "DATA_ROOT", data_root)
    monkeypatch.setattr(server, "DATABASE_PATH", database)
    monkeypatch.setattr(anchor_api, "DATA_ROOT", data_root)
    monkeypatch.setattr(anchor_api, "DATABASE_PATH", database)
    client = TestClient(server.app)
    paths = ("/api/health", "/api/ready", "/api/snapshot", "/api/snapshot/data/etf_prices.json",
             "/api/snapshot/data/index_prices.json", "/api/rotation/overview", "/api/anchor/metrics")
    responses = {path: client.get(path) for path in paths}
    assert {path: response.status_code for path, response in responses.items()} == dict.fromkeys(paths, 200)
    assert all(responses[path].json()["snapshot_id"] == snapshot_id for path in paths[2:])
    sample = responses["/api/snapshot/data/etf_prices.json"].json()["flatRecords"][0]
    with sqlite3.connect(database) as connection:
        stored = connection.execute("SELECT close_price FROM etf_prices WHERE trade_date=? AND product_code=?",
                                    (sample["tradeDate"], sample["productCode"])).fetchone()[0]
    assert stored == sample["closePrice"]
    trace = client.get(f"/api/provenance/etf/{sample['productCode']}/{sample['tradeDate']}")
    assert trace.status_code == 200
    assert trace.json()["snapshot_id"] == snapshot_id
    job, _ = claim_job(data_root, "all_prices", day, "fixture")
    set_job(data_root, job["job_id"], state="FAILED", stage="STOPPED", error="TimeoutError")
    health = client.get("/api/health").json()
    assert health["healthState"] == "DEGRADED"
    assert health["dataExists"] is True
    assert health["lastJob"]["state"] == "FAILED"
