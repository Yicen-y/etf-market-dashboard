import json

from fastapi.testclient import TestClient

import server
from scripts.index_view import project_index_view


def sample():
    records = [
        {"tradeDate": day, "values": {"480080": value, "480081": 2, "H00821": 3, "H00918": 4, "H00300": 5},
         "ratio": value / 2, "rsi14": 50}
        for day, value in (("20260101", 1), ("20260102", 2), ("20260103", 3))
    ]
    return {"snapshot_id": "v1", "records": records, "flatRecords": [1, 2],
            "latestTradeDate": "20260103", "indexes": {code: {"name": code} for code in records[0]["values"]},
            "strategies": [{"id": "dividend-hs300", "a": "H00821", "b": "H00300"}],
            "strategyMetrics": {"dividend-hs300": [{"tradeDate": day, "ratio": i} for i, day in enumerate(("20260101", "20260102", "20260103"))]},
            "strategyInputStatus": {"dividend-hs300": {"effectiveDate": "20260103"}},
            "tradingCalendar": {"dates": [row["tradeDate"] for row in records]}}


def test_projection_preserves_full_history_and_precomputed_values():
    original = sample()
    prism = project_index_view(original, strategy="prism")
    assert len(prism["records"]) == len(original["records"])
    assert prism["records"][0]["ratio"] == original["records"][0]["ratio"]
    assert set(prism["records"][0]["values"]) == {"480080", "480081"}
    assert "flatRecords" not in prism
    strategy = project_index_view(original, strategy="dividend-hs300", start="20260102", end="20260103")
    assert strategy["records"] == [{"tradeDate": row["tradeDate"], "values": {"H00821": 3, "H00300": 5}}
                                    for row in original["records"][1:]]
    assert strategy["strategyMetrics"]["dividend-hs300"] == original["strategyMetrics"]["dividend-hs300"][1:]
    assert len(original["records"]) == 3


def test_api_filtering_and_legacy_endpoint(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    payload = sample()
    (root / "index.json").write_text(json.dumps(payload), encoding="utf-8")
    (root / "etf.json").write_text(json.dumps({"snapshot_id": "v1", "records": []}), encoding="utf-8")
    (root / "current_manifest.json").write_text(json.dumps({"snapshot_id": "v1", "files": {"index": "index.json", "etf": "etf.json"}}), encoding="utf-8")
    monkeypatch.setattr(server, "DATA_ROOT", root)
    client = TestClient(server.app)
    assert client.get("/api/snapshot/data/index_prices.json").json() == payload
    response = client.get("/api/snapshot/index-view?strategy=dividend-hs300&start=20260102&end=20260103&snapshot_id=v1")
    assert response.status_code == 200
    assert len(response.json()["records"]) == 2
    assert len(response.json()["strategyMetrics"]["dividend-hs300"]) == 2
    codes = client.get("/api/snapshot/index-view?codes=H00300,H00821&end=20260102")
    assert codes.status_code == 200
    assert set(codes.json()["records"][0]["values"]) == {"H00300", "H00821"}
    assert client.get("/api/snapshot/index-view?strategy=bad").status_code == 422
    assert client.get("/api/snapshot/index-view?strategy=prism&snapshot_id=old").status_code == 409
    assert client.get("/api/snapshot/index-view?strategy=prism&start=20260103&end=20260101").status_code == 422
