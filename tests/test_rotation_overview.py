from scripts.rotation_overview import summarize_etf, summarize_strategy


def test_events_use_adjacent_reference_days_and_moving_thresholds():
    dates = [f"2026110{i}" for i in range(1, 7)]
    rows = [
        dict(tradeDate=dates[0], ratio=1, ratioMa242=1, ratioUpper242=2),
        dict(tradeDate=dates[1], ratio=2, ratioMa242=1, ratioUpper242=2),
        dict(tradeDate=dates[2], ratio=2, ratioMa242=1, ratioUpper242=1.9),
        dict(tradeDate=dates[4], ratio=0.5, ratioMa242=1, ratioUpper242=2),
        dict(tradeDate=dates[5], ratio=0.4, ratioMa242=1, ratioUpper242=2),
    ]
    result = summarize_strategy({"id": "example"}, rows, dates)
    assert [(event["date"], event["label"]) for event in result["events"]] == [
        (dates[2], "突破上轨"), (dates[1], "上穿比值均线"),
    ]
    mean = next(state for state in result["states"] if state["threshold"] == "ratioMa242")
    assert mean["days"] == 2
    assert result["rsi"] is None


def test_stale_group_keeps_recent_events_but_has_no_current_signal():
    dates = ["20261104", "20261105", "20261106"]
    rows = [dict(tradeDate=day, ratio=1, rsi14=rsi) for day, rsi in zip(dates, [51, 49])]
    result = summarize_strategy({"id": "example"}, rows, dates)
    assert result["data_date"] == dates[1]
    assert result["rsi"] is None
    assert result["events"][0]["label"] == "RSI下穿50"


def test_etf_uses_previous_session_as_base_and_preserves_missing_close():
    rows = [
        dict(tradeDate="20251230", prices={"512530": 2, "562310": 4, "510330": 5}),
        dict(tradeDate="20260105", prices={"512530": 3, "562310": 3}),
    ]
    result = summarize_etf({"records": rows, "products": {
        code: {"name": code} for code in ("512530", "562310", "510330")
    }}, "20260105")
    assert result["base_date"] == "20251230"
    assert result["portfolio"] == 0.125
    assert result["spread"] == 0.75
    assert result["returns"]["510330"]["value"] is None


def test_api_uses_one_snapshot_and_invalidates_cache(tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    import server

    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(server, "ROOT", tmp_path)
    client = TestClient(server.app)
    assert client.get("/", follow_redirects=False).headers["location"] == "/web/overview.html"
    configs = [{"id": f"s{i}", "name": f"S{i}"} for i in range(8)]
    for version, day in (("first", "20261105"), ("second", "20261106")):
        index = dict(snapshot_id=version, tradingCalendar={"dates": [day]}, strategies=configs, records=[])
        etf = dict(snapshot_id=version, products={}, records=[])
        (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
        (root / "etf.json").write_text(json.dumps(etf), encoding="utf-8")
        (root / "current_manifest.json").write_text(json.dumps({
            "snapshot_id": version, "files": {"index": "index.json", "etf": "etf.json"},
        }), encoding="utf-8")
        response = client.get("/api/rotation/overview")
        assert response.status_code == 200
        assert len(response.content) < 100_000
        result = response.json()
        assert len(result["groups"]) == 9
        assert result["snapshot_id"] == version
        assert result["observation_date"] == day
        assert all("records" not in group for group in result["groups"])
    server._rotation_overview.cache_clear()
