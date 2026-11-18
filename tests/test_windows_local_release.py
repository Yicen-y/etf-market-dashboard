"""Local rollback restores a sealed backup without deleting newer releases."""

import json
import shutil

import pytest

from scripts.snapshot import read_manifest
from scripts.storage import init_reliability_schema, publish_snapshot
from scripts.windows_local_release import inspect, prepare, rollback


def _payload(snapshot_id, kind):
    base = {"snapshot_id": snapshot_id, "records": [{"tradeDate": "20261113"}]}
    if kind == "etf":
        base["flatRecords"] = [{"productCode": "510330", "tradeDate": "20261113", "closePrice": 1.0}]
    else:
        base["flatRecords"] = [{"indexCode": "H00300", "tradeDate": "20261113", "closeValue": 1000.0}]
    return base


def test_windows_backup_and_rollback_keep_newer_immutable_release(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    init_reliability_schema(root / "etf_market.db")
    publish_snapshot(root, "old", _payload("old", "etf"), _payload("old", "index"))
    backup = tmp_path / "sealed-backup"
    baseline = prepare(root, backup)
    assert baseline["snapshot_id"] == "old"
    publish_snapshot(root, "new", _payload("new", "etf"), _payload("new", "index"))
    new_file = root / "releases" / "new" / "index_prices.json"
    assert new_file.exists()
    with pytest.raises(ValueError, match="active snapshot changed"):
        rollback(root, backup, "unexpected")
    assert read_manifest(root)["snapshot_id"] == "new"
    assert rollback(root, backup, "new") == baseline
    assert read_manifest(root)["snapshot_id"] == "old"
    assert new_file.exists()
    assert inspect(root) == baseline


def test_windows_rollback_refuses_sqlite_sidecar(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    init_reliability_schema(root / "etf_market.db")
    publish_snapshot(root, "old", _payload("old", "etf"), _payload("old", "index"))
    backup = tmp_path / "sealed-backup"
    prepare(root, backup)
    publish_snapshot(root, "new", _payload("new", "etf"), _payload("new", "index"))
    (root / "etf_market.db-wal").write_bytes(b"active")
    with pytest.raises(RuntimeError, match="SQLite sidecar"):
        rollback(root, backup, "new")
    assert read_manifest(root)["snapshot_id"] == "new"


def test_rollback_accepts_older_inventory_with_legacy_mirrors(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    init_reliability_schema(root / "etf_market.db")
    old = publish_snapshot(root, "old", _payload("old", "etf"), _payload("old", "index"))
    for key, name in (("etf", "etf_prices.json"), ("index", "index_prices.json")):
        shutil.copyfile(root / old["files"][key], root / name)
    backup = tmp_path / "older-backup"
    prepare(root, backup)
    for name in ("etf_prices.json", "index_prices.json"):
        shutil.copyfile(root / name, backup / name)
    historical_inventory = inspect(backup, include_legacy=True)
    (backup / "backup_inventory.json").write_text(json.dumps(historical_inventory), encoding="utf-8")
    publish_snapshot(root, "new", _payload("new", "etf"), _payload("new", "index"))
    assert rollback(root, backup, "new") == historical_inventory
    assert read_manifest(root)["snapshot_id"] == "old"
