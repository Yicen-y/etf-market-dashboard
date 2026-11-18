import sqlite3
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.data_center import _official_mainland_reference_date, build_data_center


def test_data_center_keeps_snapshot_diagnostics_when_database_is_unreadable(tmp_path):
    result = build_data_center(tmp_path, tmp_path / "missing.db")
    assert result["database_error"] == "FileNotFoundError"
    assert len(result["datasets"]) == 5
    assert result["summary"]["failed"] >= 2
from scripts.storage import init_reliability_schema, publish_snapshot, record_quality_issues


def test_latest_mainland_reference_uses_three_csi_series_when_cni_is_older(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE index_reference_batches (batch_id TEXT, index_code TEXT, provider TEXT, status TEXT, raw_sha256 TEXT, raw_path TEXT)")
        connection.execute("CREATE TABLE index_reference_observations (batch_id TEXT, trade_date TEXT)")
        for code, day, provider in (("480080", "20261113", "CNI official HTTPS"),
                                    ("480081", "20261113", "CNI official HTTPS"),
                                    ("H00821", "20261116", "CSI official HTTP"),
                                    ("H00300", "20261116", "CSI official HTTP"),
                                    ("H00918", "20261116", "CSI official HTTP")):
            connection.execute("INSERT INTO index_reference_batches VALUES (?,?,?,?,?,?)",
                               (code, code, provider, "FETCHED", "hash", "archived.json"))
            connection.execute("INSERT INTO index_reference_observations VALUES (?,?)", (code, day))
    assert _official_mainland_reference_date(database) == "20261116"


def test_t13_t15_candidate_blocked_does_not_claim_published_or_verified(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    database = root / "etf_market.db"
    init_reliability_schema(database)
    publish_snapshot(root, "old", {"snapshot_id": "old", "records": [], "latestTradeDate": "20261111"},
                     {"snapshot_id": "old", "records": [], "latestTradeDate": "20261111"})
    record_quality_issues(database, [{"symbol": "512530", "kind": "etf", "trade_date": "20261112",
                                      "issue_code": "UNVERIFIED_FALLBACK_SOURCE", "severity": "BLOCKED", "batch_id": "candidate"}])
    report = build_data_center(root, database)
    etf = next(row for row in report["datasets"] if row["id"] == "etf_prices")
    assert etf["snapshot_id"] == "old"
    assert etf["latest_trade_date"] == "20261111"
    assert etf["publication_status"] == "PUBLISHED"
    assert etf["fetch_status"] == "CANDIDATE_BLOCKED"
    assert etf["source_verification"] == "UNKNOWN"
    assert report["recent_issues"][0]["trade_date"] == "20261112"


def test_t14_old_release_is_marked_stale_only_with_covered_calendar(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    database = root / "etf_market.db"
    init_reliability_schema(database)
    publish_snapshot(root, "old", {"snapshot_id": "old", "records": [], "latestTradeDate": "20261111"},
                     {"snapshot_id": "old", "records": [], "latestTradeDate": "20261111"})
    etf = next(row for row in build_data_center(root, database)["datasets"] if row["id"] == "etf_prices")
    assert etf["freshness_status"] == "UNKNOWN"
    (root / "market_calendar.json").write_text(json.dumps({
        "dates": ["20261111", "20261112"],
        "covered_through": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"),
        "source": "offline fixture"}), encoding="utf-8")
    etf = next(row for row in build_data_center(root, database)["datasets"] if row["id"] == "etf_prices")
    assert etf["freshness_status"] == "STALE"
    assert etf["using_previous_release"]
    assert etf["publication_status"] == "PUBLISHED"
    assert etf["expected_trade_date"] == "20261112"


def test_t09_known_non_trading_day_does_not_mark_current_release_failed(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    database = root / "market.db"
    init_reliability_schema(database)
    publish_snapshot(root, "current", {"snapshot_id": "current", "records": [], "latestTradeDate": "20261112"},
                     {"snapshot_id": "current", "records": [], "latestTradeDate": "20261112"})
    (root / "market_calendar.json").write_text(json.dumps({
        "dates": ["20261111", "20261112"],
        "covered_through": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"),
        "source": "offline fixture with later market holiday"}), encoding="utf-8")
    etf = next(row for row in build_data_center(root, database)["datasets"] if row["id"] == "etf_prices")
    assert etf["latest_trade_date"] == etf["expected_trade_date"] == "20261112"
    assert etf["freshness_status"] == "CURRENT"
    assert not etf["using_previous_release"]


def test_t03_data_center_marks_corrupt_snapshot_failed(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    database = root / "etf_market.db"
    init_reliability_schema(database)
    manifest = publish_snapshot(root, "v1", {"snapshot_id": "v1", "records": []},
                                {"snapshot_id": "v1", "records": []})
    (root / manifest["files"]["index"]).write_text("{}", encoding="utf-8")
    report = build_data_center(root, database)
    index = next(row for row in report["datasets"] if row["id"] == "index_prices")
    assert index["publication_status"] == "FAILED"
    assert report["summary"]["failed"] == 1
