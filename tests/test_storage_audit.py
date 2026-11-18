from scripts.storage_audit import inventory


def test_inventory_classifies_evidence_and_only_previews_temporary_files(tmp_path):
    (tmp_path / "current_manifest.json").write_text('{"snapshot_id":"v1","files":{"etf":"releases/v1/etf_prices.json","index":"releases/v1/index_prices.json"}}', encoding="utf-8")
    for name in ("releases/v1/etf_prices.json", "releases/v1/index_prices.json",
                 "releases/old/etf_prices.json", "raw/market/evidence.bin",
                 "backups/market.db", "stale.tmp"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"123")
    report = inventory(tmp_path)
    assert report["categories"]["current_release"]["files"] == 2
    assert report["categories"]["rollback_releases"]["files"] == 1
    assert report["categories"]["raw_evidence"]["files"] == 1
    assert report["cleanup_preview_only"] == [{"path": "stale.tmp", "bytes": 3}]
    assert (tmp_path / "stale.tmp").exists()
