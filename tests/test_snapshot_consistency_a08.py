"""A08: one manifest pins both immutable datasets across publication."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import server
import scripts.storage as storage
from scripts.snapshot import read_dataset, read_manifest


def payload(version, kind, value):
    result = {"snapshot_id": version, "records": [{"tradeDate": "20260105", "values": {"H00300": value}}]}
    if kind == "index":
        result.update(indexes={"H00300": {"name": "沪深300"}}, strategies=[],
                      strategyMetrics={}, tradingCalendar={"dates": ["20260105"]})
    else:
        result["records"] = [{"tradeDate": "20260105", "prices": {"510330": value}}]
        result["products"] = {"510330": {"name": "ETF"}}
    return result


def staged(root, version, value, activate=True):
    return storage.publish_snapshot(root, version, payload(version, "etf", value),
                                    payload(version, "index", value), activate=activate)


def test_normal_publish_keeps_one_boundary_and_legacy_files_untouched(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    (root / "etf_prices.json").write_text(json.dumps(payload("legacy", "etf", 0)), encoding="utf-8")
    (root / "index_prices.json").write_text(json.dumps(payload("legacy", "index", 0)), encoding="utf-8")
    before_legacy = [(root / name).read_bytes() for name in ("etf_prices.json", "index_prices.json")]
    staged(root, "old", 1)
    old = read_manifest(root)
    new = staged(root, "new", 2, activate=False)
    assert read_manifest(root) == old
    monkeypatch.setattr(server, "DATA_ROOT", root)
    assert TestClient(server.app).get("/api/snapshot/data/index_prices.json?snapshot_id=new").status_code == 409
    assert (read_dataset(root, old, "etf")["snapshot_id"], read_dataset(root, old, "index")["snapshot_id"]) == ("old", "old")
    storage.activate_snapshot(root, new)
    assert read_manifest(root)["snapshot_id"] == "new"
    assert [read_dataset(root, new, kind)["snapshot_id"] for kind in ("etf", "index")] == ["new", "new"]
    assert [(root / name).read_bytes() for name in ("etf_prices.json", "index_prices.json")] == before_legacy
    assert not list(root.glob("*.json.tmp"))

    client = TestClient(server.app)
    assert client.get("/api/snapshot").json()["snapshot_id"] == "new"
    for name in ("etf_prices.json", "index_prices.json"):
        for url in (f"/api/snapshot/data/{name}", f"/api/snapshot/data/{name}?snapshot_id=new"):
            response = client.get(url)
            assert response.status_code == 200
            assert response.json()["snapshot_id"] == "new"
        assert client.get(f"/api/snapshot/data/{name}?snapshot_id=old").status_code == 409
    for url in ("/api/snapshot/index-view?codes=H00300", "/api/snapshot/index-view?codes=H00300&snapshot_id=new"):
        response = client.get(url)
        assert response.status_code == 200
        assert response.json()["snapshot_id"] == "new"
    assert client.get("/api/snapshot/index-view?codes=H00300&snapshot_id=old").status_code == 409
    assert client.get("/api/snapshot/data/index_prices.json?snapshot_id=missing").status_code == 409
    assert client.get("/api/snapshot/data/index_prices.json?snapshot_id=..").status_code == 409


def test_pointer_failure_preserves_old_snapshot_and_pinned_reads(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    staged(root, "old", 1)
    new = staged(root, "new", 2, activate=False)
    original = storage._replace_with_reader_retry

    def fail_pointer(source, target):
        if target == root / "current_manifest.json":
            raise OSError("injected pointer interruption")
        return original(source, target)

    monkeypatch.setattr(storage, "_replace_with_reader_retry", fail_pointer)
    with pytest.raises(OSError, match="pointer interruption"):
        storage.activate_snapshot(root, new)
    assert read_manifest(root)["snapshot_id"] == "old"
    assert read_dataset(root, read_manifest(root), "index")["snapshot_id"] == "old"
    monkeypatch.setattr(storage, "_replace_with_reader_retry", original)
    storage.activate_snapshot(root, new)
    assert read_manifest(root)["snapshot_id"] == "new"


def test_read_pinned_manifest_during_switch_never_mixes_files(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    staged(root, "old", 1)
    new = staged(root, "new", 2, activate=False)
    pinned = read_manifest(root)
    with ThreadPoolExecutor(max_workers=2) as pool:
        switching = pool.submit(storage.activate_snapshot, root, new)
        pair = pool.submit(lambda: (read_dataset(root, pinned, "etf")["snapshot_id"],
                                    read_dataset(root, pinned, "index")["snapshot_id"]))
        switching.result()
        assert pair.result() == ("old", "old")
    latest = read_manifest(root)
    assert (read_dataset(root, latest, "etf")["snapshot_id"], read_dataset(root, latest, "index")["snapshot_id"]) == ("new", "new")
