import json

import pytest
from fastapi.testclient import TestClient

import server
from scripts.snapshot import read_dataset, read_manifest, resolve_file
from scripts.storage import activate_snapshot, init_reliability_schema, publish_snapshot, record_legacy_observations


@pytest.mark.parametrize("relative", ["releases\\v1/etf_prices.json", "releases/v1/etf_prices.json", "releases\\v1\\etf_prices.json"])
def test_manifest_separators_resolve_identically(tmp_path, relative):
    target = tmp_path / "releases" / "v1" / "etf_prices.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"snapshot_id": "v1", "records": [1]}), encoding="utf-8")
    assert resolve_file(tmp_path, relative) == target


@pytest.mark.parametrize("relative", ["../outside", "releases/../../outside", "C:\\outside", "/absolute", "\\\\server\\share", "releases//file"])
def test_manifest_rejects_unsafe_paths(tmp_path, relative):
    with pytest.raises(ValueError):
        resolve_file(tmp_path, relative)


def test_missing_corrupt_and_wrong_dataset_are_not_healthy(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(server, "DATA_ROOT", data)
    monkeypatch.setattr(server, "DATABASE_PATH", tmp_path / "missing.db")
    manifest = {"snapshot_id": "v1", "status": "published", "files": {"etf": "etf_prices.json", "index": "index_prices.json"}}
    (data / "current_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert TestClient(server.app).get("/api/ready").status_code == 503
    (data / "etf_prices.json").write_text(json.dumps({"snapshot_id": "v1", "records": [1], "strategies": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="wrong dataset"):
        read_dataset(data, read_manifest(data), "etf")


def test_new_manifest_serializes_posix_paths(tmp_path):
    manifest = publish_snapshot(tmp_path, "v1", {"snapshot_id": "v1", "records": [1]}, {"snapshot_id": "v1", "records": [1]})
    assert manifest["files"] == {"etf": "releases/v1/etf_prices.json", "index": "releases/v1/index_prices.json"}


def test_staged_release_preserves_previous_pointer_until_activation(tmp_path):
    old = publish_snapshot(tmp_path, "old", {"snapshot_id": "old", "records": [1]}, {"snapshot_id": "old", "records": [1]})
    candidate = publish_snapshot(tmp_path, "new", {"snapshot_id": "new", "records": [2]}, {"snapshot_id": "new", "records": [2]}, activate=False)
    assert read_manifest(tmp_path)["snapshot_id"] == old["snapshot_id"]
    (tmp_path / candidate["files"]["index"]).write_text("corrupt", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        activate_snapshot(tmp_path, candidate)
    assert read_manifest(tmp_path)["snapshot_id"] == "old"


def test_readiness_detects_corrupt_index_snapshot(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    publish_snapshot(root, "v1", {"snapshot_id": "v1", "records": [1]},
                     {"snapshot_id": "v1", "records": [1], "strategyMetrics": {"core": [1]}})
    monkeypatch.setattr(server, "DATA_ROOT", root)
    database = root / "etf_market.db"
    init_reliability_schema(database)
    monkeypatch.setattr(server, "DATABASE_PATH", database)
    client = TestClient(server.app)
    assert client.get("/api/ready").status_code == 200
    (root / "releases" / "v1" / "index_prices.json").write_text("{}", encoding="utf-8")
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["healthState"] == "UNHEALTHY"


def test_legacy_rows_do_not_create_fake_raw_evidence(tmp_path):
    database = tmp_path / "market.db"
    record_legacy_observations(database, [{"tradeDate": "20200101", "productCode": "510330", "closePrice": 1.0}], [])
    assert not database.exists()
