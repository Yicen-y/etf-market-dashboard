import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from scripts.storage import activate_snapshot, commit_market_release, init_reliability_schema, market_fingerprint, publish_snapshot, record_release_manifest, upsert_market_records_atomic
from scripts.storage import recover_prepared_release
from scripts.snapshot import read_dataset, read_manifest
import pytest


def _payload(snapshot_id, value):
    return {"snapshot_id": snapshot_id, "records": [{"tradeDate": "20260105", "closePrice": value}],
            "flatRecords": [{"tradeDate": "20260105", "productCode": "510330", "closePrice": value}]}


def _index(snapshot_id, value):
    return {"snapshot_id": snapshot_id, "records": [{"tradeDate": "20260105"}],
            "flatRecords": [{"tradeDate": "20260105", "indexCode": "H00300", "closeValue": value}]}


def test_recovery_promotes_only_database_matched_prepared_release(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    database = root / "market.db"
    init_reliability_schema(database)
    old = publish_snapshot(root, "old", _payload("old", 1.0), _index("old", 100.0))
    new = publish_snapshot(root, "new", _payload("new", 2.0), _index("new", 200.0), activate=False)
    record_release_manifest(database, {**new, "status": "prepared"})
    assert recover_prepared_release(root, database)["state"] == "BLOCKED"
    assert read_manifest(root)["snapshot_id"] == old["snapshot_id"]
    upsert_market_records_atomic(database, _payload("new", 2.0)["flatRecords"],
                                 _index("new", 200.0)["flatRecords"], "now")
    assert recover_prepared_release(root, database)["state"] == "RECOVERED"
    assert read_manifest(root)["snapshot_id"] == "new"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT status FROM release_manifest WHERE snapshot_id='new'").fetchone()[0] == "published"


def test_corrupt_prepared_release_never_replaces_current(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    database = root / "market.db"
    init_reliability_schema(database)
    publish_snapshot(root, "old", _payload("old", 1.0), _index("old", 100.0))
    new = publish_snapshot(root, "new", _payload("new", 2.0), _index("new", 200.0), activate=False)
    record_release_manifest(database, {**new, "status": "prepared"})
    (root / new["files"]["etf"]).write_text("{}", encoding="utf-8")
    assert recover_prepared_release(root, database)["state"] == "BLOCKED"
    assert read_manifest(root)["snapshot_id"] == "old"


@pytest.mark.parametrize("failure", ["json", "manifest"])
def test_staging_failure_never_switches_current_pointer(tmp_path, failure):
    root = tmp_path / "data"
    root.mkdir()
    publish_snapshot(root, "old", _payload("old", 1), _index("old", 100))
    with pytest.raises(RuntimeError, match="simulated"):
        publish_snapshot(root, "new", _payload("new", 2), _index("new", 200), fail_at=failure)
    manifest = read_manifest(root)
    assert manifest["snapshot_id"] == "old"
    assert read_dataset(root, manifest, "etf")["snapshot_id"] == "old"


def test_unmodified_database_aborts_staged_release(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    database = root / "market.db"
    init_reliability_schema(database)
    upsert_market_records_atomic(database, _payload("old", 1.0)["flatRecords"],
                                 _index("old", 100.0)["flatRecords"], "old")
    publish_snapshot(root, "old", _payload("old", 1.0), _index("old", 100.0))
    digest = market_fingerprint(database)
    candidate = publish_snapshot(root, "new", _payload("new", 2.0), _index("new", 200.0),
                                 activate=False, prepublish_fingerprint=digest)
    record_release_manifest(database, {**candidate, "status": "prepared"})
    assert recover_prepared_release(root, database)["state"] == "ABORTED"
    assert read_manifest(root)["snapshot_id"] == "old"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT status FROM release_manifest WHERE snapshot_id='new'").fetchone()[0] == "aborted"


def test_release_sqlite_failure_rolls_back_prices_raw_links_and_marker(tmp_path):
    database = tmp_path / "market.db"
    init_reliability_schema(database)
    with pytest.raises(sqlite3.OperationalError, match="simulated"):
        commit_market_release(database, raw_rows=[{
            "symbol": "510330", "kind": "etf", "trade_date": "20260105", "value_raw": "2.0",
            "provider": "AkShare", "upstream_publisher": "Eastmoney", "raw_sha256": "hash",
            "fetch_batch_id": "b1"}], quality_rows=[],
            etf_rows=_payload("new", 2.0)["flatRecords"], index_rows=[], updated_at="now",
            etf_sources={}, index_sources={}, delete_index_keys=[], canonical_rows=[],
            canonical_delete_keys=[], manifest={"snapshot_id": "new", "fetch_batch_id": "b1"}, fail_at="sqlite")
    with sqlite3.connect(database) as connection:
        for table in ("etf_prices", "raw_observations", "canonical_observations", "release_manifest"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_release_sqlite_commit_links_raw_and_prepared_marker(tmp_path):
    database = tmp_path / "market.db"
    commit_market_release(database, raw_rows=[{
        "symbol": "510330", "kind": "etf", "trade_date": "20260105", "value_raw": "2.0",
        "provider": "AkShare", "upstream_publisher": "Eastmoney", "raw_sha256": "hash",
        "fetch_batch_id": "b1"}], quality_rows=[],
        etf_rows=_payload("new", 2.0)["flatRecords"], index_rows=[], updated_at="now",
        etf_sources={}, index_sources={}, delete_index_keys=[],
        canonical_rows=[{"symbol": "510330", "kind": "etf", "trade_date": "20260105",
                         "normalized_value": 2.0, "normalized_unit": "元/份",
                         "selection_reason": "primary", "quality_status": "PASS", "batch_id": "b1"}],
        canonical_delete_keys=[], manifest={"snapshot_id": "new", "fetch_batch_id": "b1", "created_at": "2026-01-05T00:00:00Z"})
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT selected_raw_id FROM canonical_observations").fetchone()[0] == 1
        assert connection.execute("SELECT status,published_at FROM release_manifest").fetchone() == ("prepared", None)


def test_pointer_failure_keeps_old_release_then_recovers(tmp_path, monkeypatch):
    from scripts import storage
    root = tmp_path / "data"
    root.mkdir()
    database = root / "market.db"
    init_reliability_schema(database)
    publish_snapshot(root, "old", _payload("old", 1), _index("old", 100))
    new = publish_snapshot(root, "new", _payload("new", 2), _index("new", 200), activate=False)
    upsert_market_records_atomic(database, _payload("new", 2)["flatRecords"], _index("new", 200)["flatRecords"], "new")
    record_release_manifest(database, {**new, "status": "prepared"})
    original = storage.os.replace
    def fail_pointer(source, target):
        if str(target).endswith("current_manifest.json"):
            raise OSError("simulated pointer failure")
        return original(source, target)
    monkeypatch.setattr(storage.os, "replace", fail_pointer)
    with pytest.raises(OSError, match="pointer failure"):
        activate_snapshot(root, new)
    assert read_manifest(root)["snapshot_id"] == "old"
    monkeypatch.setattr(storage.os, "replace", original)
    assert recover_prepared_release(root, database)["state"] == "RECOVERED"
    assert read_manifest(root)["snapshot_id"] == "new"


def test_concurrent_readers_never_mix_versions_during_pointer_swap(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    publish_snapshot(root, "old", _payload("old", 1), _index("old", 100))
    candidate = publish_snapshot(root, "new", _payload("new", 2), _index("new", 200), activate=False)

    def reader():
        observed = []
        for _ in range(50):
            manifest = read_manifest(root)
            etf = read_dataset(root, manifest, "etf")
            index = read_dataset(root, manifest, "index")
            observed.append((manifest["snapshot_id"], etf["snapshot_id"], index["snapshot_id"]))
        return observed

    with ThreadPoolExecutor(max_workers=5) as pool:
        readers = [pool.submit(reader) for _ in range(4)]
        activate_snapshot(root, candidate)
        observed = [row for future in readers for row in future.result()]
    assert observed
    assert all(len(set(row)) == 1 for row in observed)


def test_windows_reader_lock_retries_pointer_swap(tmp_path, monkeypatch):
    import os
    from scripts import storage
    root = tmp_path / "data"
    root.mkdir()
    publish_snapshot(root, "old", _payload("old", 1), _index("old", 100))
    candidate = publish_snapshot(root, "new", _payload("new", 2), _index("new", 200), activate=False)
    attempts = {"count": 0}

    def transient_lock(source, target):
        if str(target).endswith("current_manifest.json") and attempts["count"] < 2:
            attempts["count"] += 1
            raise PermissionError("simulated Windows reader handle")
        return os.replace(source, target)

    monkeypatch.setattr(storage, "os", SimpleNamespace(name="nt", replace=transient_lock))
    activate_snapshot(root, candidate)
    assert attempts["count"] == 2
    assert read_manifest(root)["snapshot_id"] == "new"
