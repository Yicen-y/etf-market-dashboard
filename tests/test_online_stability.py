"""Offline regressions for repeat updates and retained source evidence."""
import sqlite3
import json
import hashlib

import pytest

from scripts.storage import (commit_market_release, init_reliability_schema,
                             publish_snapshot, record_canonical_observations,
                             record_release_manifest, upsert_market_records_atomic)
from scripts import index_verification as verification
from scripts.fetch_data import FetchResult
from scripts.config import INDEXES


def test_identical_market_overlap_keeps_original_timestamp_and_source(tmp_path):
    database = tmp_path / "market.db"
    etf = [{"tradeDate": "20261116", "productCode": "510330", "closePrice": 4.35}]
    index = [{"tradeDate": "20261116", "indexCode": "H00300", "closeValue": 5993.46}]
    upsert_market_records_atomic(database, etf, index, "first",
                                 {("20261116", "510330"): "AkShare"},
                                 {("20261116", "H00300"): "CSI official HTTP"})
    upsert_market_records_atomic(database, etf, index, "second",
                                 {("20261116", "510330"): "Other same-value route"},
                                 {("20261116", "H00300"): "Other same-value route"})
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT close_price,source,updated_at FROM etf_prices").fetchone() == (
            4.35, "AkShare", "first")
        assert connection.execute("SELECT close_value,source,updated_at FROM index_prices").fetchone() == (
            5993.46, "CSI official HTTP", "first")


def test_identical_canonical_recheck_keeps_original_selected_raw_link(tmp_path):
    database = tmp_path / "market.db"
    init_reliability_schema(database)
    original = {"symbol": "H00300", "kind": "index", "trade_date": "20261116",
                "normalized_value": 5993.46, "normalized_unit": "index_point",
                "selected_raw_id": 1, "selection_reason": "first", "quality_status": "PASS", "batch_id": "first"}
    record_canonical_observations(database, [original])
    record_canonical_observations(database, [{**original, "selected_raw_id": 2,
                                              "selection_reason": "recheck", "batch_id": "second"}])
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT selected_raw_id,batch_id FROM canonical_observations").fetchone() == (
            1, "first")


def test_h00922_official_close_is_not_legacy_recheck_candidate(tmp_path):
    from scripts.update_data import legacy_h00922_recheck_dates

    database = tmp_path / "market.db"
    init_reliability_schema(database)
    with sqlite3.connect(database) as connection:
        connection.executemany("INSERT INTO index_prices VALUES (?,?,?,?,?)", [
            ("20261113", "H00922", 12000.0, "PROVENANCE_UNKNOWN", "first"),
            ("20261116", "H00922", 12100.0, "CSI official HTTP", "second"),
            ("20261117", "H00922", 12200.0, "CSI official HTTP", "third"),
        ])
        payload = b'{"indexCode":"H00922","tradeDate":"20261116","close":12100.0}'
        digest = hashlib.sha256(payload).hexdigest()
        connection.execute("""INSERT INTO raw_observations
            (symbol,kind,trade_date,value_raw,provider,upstream_publisher,fetched_at,raw_sha256,fetch_batch_id)
            VALUES ('H00922','index','20261116','12100.0','CSI official HTTP','CSI','2026-11-17T00:00:00Z',?, 'batch')""",
            (digest,))
    archive = tmp_path / "raw" / "market" / "batch"
    archive.mkdir(parents=True)
    raw_file = archive / f"index-H00922-20261116-20261116-{digest[:16]}.bin"
    raw_file.write_bytes(payload)
    assert legacy_h00922_recheck_dates(database) == ["20261113", "20261117"]
    raw_file.unlink()
    assert legacy_h00922_recheck_dates(database) == ["20261113", "20261116", "20261117"]


def test_h00922_recheck_works_before_reliability_schema_migration(tmp_path):
    from scripts.storage import init_database
    from scripts.update_data import legacy_h00922_recheck_dates

    database = tmp_path / "legacy.db"
    init_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO index_prices VALUES (?,?,?,?,?)",
                           ("20261113", "H00922", 12000.0, "PROVENANCE_UNKNOWN", "first"))
    assert legacy_h00922_recheck_dates(database) == ["20261113"]


def test_changed_price_records_revision_and_keeps_both_raw_ids(tmp_path):
    database = tmp_path / "market.db"
    initial = {"tradeDate": "20261116", "productCode": "510330", "closePrice": 4.35}

    def commit(batch, value, source, fail_at=None):
        record = {**initial, "closePrice": value}
        commit_market_release(
            database, raw_rows=[{"symbol": "510330", "kind": "etf", "trade_date": "20261116",
                                 "value_raw": str(value), "provider": source,
                                 "upstream_publisher": "Eastmoney", "raw_sha256": batch,
                                 "fetch_batch_id": batch}], quality_rows=[], etf_rows=[record], index_rows=[],
            updated_at=batch, etf_sources={("20261116", "510330"): source}, index_sources={},
            delete_index_keys=[], canonical_rows=[{"symbol": "510330", "kind": "etf",
                "trade_date": "20261116", "normalized_value": value,
                "normalized_unit": "元/份", "selection_reason": "validated candidate",
                "quality_status": "PASS", "batch_id": batch}], canonical_delete_keys=[],
            manifest={"snapshot_id": batch, "fetch_batch_id": batch,
                      "created_at": "2026-11-17T00:00:00Z"}, fail_at=fail_at)

    commit("first", 4.35, "AkShare")
    commit("second", 4.36, "Authorized issuer")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT old_value,new_value,old_source,new_source,old_raw_id,new_raw_id "
                                  "FROM market_price_revisions").fetchone() == (
            4.35, 4.36, "AkShare", "Authorized issuer", 1, 2)
        assert connection.execute("SELECT value_raw,provider FROM raw_observations ORDER BY raw_record_id").fetchall() == [
            ("4.35", "AkShare"), ("4.36", "Authorized issuer")]
    with pytest.raises(sqlite3.OperationalError, match="simulated"):
        commit("interrupted", 4.37, "Authorized issuer", fail_at="sqlite")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT close_price,source FROM etf_prices").fetchone() == (
            4.36, "Authorized issuer")
        assert connection.execute("SELECT COUNT(*) FROM market_price_revisions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM release_manifest").fetchone()[0] == 2


@pytest.mark.parametrize("status", [403, 429])
def test_issuer_http_failure_retains_bounded_diagnostic_without_retry(monkeypatch, status):
    class Response:
        ok = False
        status_code = status
        content = b"access unavailable"
        headers = {"content-type": "text/html"}

    requests = []
    def request(url, params):
        requests.append((url, params))
        return Response()

    monkeypatch.setattr(verification, "_reference_get", request)
    with pytest.raises(verification.ReferenceHTTPError) as caught:
        verification._fetch("H00300", "20261116", "20261116")
    diagnostic = caught.value.diagnostic
    assert len(requests) == 1
    assert diagnostic["http_status"] == status
    assert diagnostic["attempts"] == 1
    assert diagnostic["requested_at"]
    assert diagnostic["endpoint"] == "CSI index-perf"
    assert diagnostic["request_params"] == requests[0][1]
    assert "access unavailable" not in str(diagnostic)


def test_official_price_index_name_cannot_validate_total_return_identity(tmp_path, monkeypatch):
    database = tmp_path / "market.db"
    init_reliability_schema(database)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO index_prices VALUES (?,?,?,?,?)",
                           ("20261116", "H00300", 5993.46, "PROVENANCE_UNKNOWN", "first"))
    fetched = FetchResult(rows=[{"tradeDate": "20261116", "indexCode": "H00300",
                                 "closeValue": 5993.46, "indexNameEnAll": "CSI 300 Price Index"}],
                          provider="CSI official HTTP", upstream="CSI", request={"indexCode": "H00300"},
                          raw_bytes=b'{"indexNameEnAll":"CSI 300 Price Index"}',
                          source_url="https://www.csindex.com.cn/csindex-home/perf/index-perf")
    monkeypatch.setattr(verification, "_fetch", lambda *_args: fetched)
    assert verification.verify(database, tmp_path, ["H00300"], "verify-code") == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT status FROM index_verification_results").fetchone()[0] == "IDENTITY_CONFLICT"


def test_daily_failure_report_keeps_http_status_without_sensitive_body(tmp_path, monkeypatch):
    from scripts import daily_verified

    database = tmp_path / "market.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE index_prices(index_code TEXT,trade_date TEXT)")
        connection.executemany("INSERT INTO index_prices VALUES (?,?)",
                               [(code, "20261113") for code in INDEXES])
    monkeypatch.setattr(daily_verified, "report", lambda *_args: None)
    def verify(_database, _root, codes, _mode, **_kwargs):
        if codes == ["H00300"]:
            raise verification.ReferenceHTTPError(403, "a" * 64, "text/html",
                                                  request_params={"indexCode": "H00300"})
        return 0
    result = daily_verified.run_daily(database=database, data_root=tmp_path,
                                      through="20261116", publish=False, verifier=verify)
    status = result["indexes"]["H00300"]
    assert status["status"] == "REFERENCE_ERROR"
    assert status["diagnostic"]["http_status"] == 403
    saved = (tmp_path / "verification" / "daily" / "20261116.json").read_text(encoding="utf-8")
    assert '"http_status": 403' in saved
    assert "access unavailable" not in saved


def test_data_center_detects_prepared_price_change_behind_old_snapshot(tmp_path):
    from scripts.data_center import build_data_center

    root = tmp_path / "data"
    root.mkdir()
    database = root / "etf_market.db"
    etf_row = {"tradeDate": "20261116", "productCode": "510330", "closePrice": 4.35}
    index_row = {"tradeDate": "20261116", "indexCode": "H00300", "closeValue": 5993.46}
    init_reliability_schema(database)
    upsert_market_records_atomic(database, [etf_row], [index_row], "first")
    manifest = publish_snapshot(root, "old", {"snapshot_id": "old", "records": [], "flatRecords": [etf_row]},
                                {"snapshot_id": "old", "latestTradeDate": "20261113",
                                 "records": [], "flatRecords": [index_row]})
    record_release_manifest(database, manifest)
    center = build_data_center(root, database)
    assert center["snapshot_database_consistency"] == "MATCH"
    index = next(item for item in center["datasets"] if item["id"] == "index_prices")
    assert index["latest_trade_date"] == "20261116"
    assert index["metric_latest_trade_date"] == "20261113"
    upsert_market_records_atomic(database, [{**etf_row, "closePrice": 4.36}], [], "second")
    assert build_data_center(root, database)["snapshot_database_consistency"] == "MISMATCH"


def test_data_center_shows_latest_reference_failure_without_hiding_published_data(tmp_path):
    from scripts.data_center import build_data_center

    root = tmp_path / "data"
    root.mkdir()
    database = root / "etf_market.db"
    index_row = {"tradeDate": "20261116", "indexCode": "H00300", "closeValue": 5993.46}
    init_reliability_schema(database)
    upsert_market_records_atomic(database, [], [index_row], "first")
    manifest = publish_snapshot(root, "old", {"snapshot_id": "old", "records": [], "flatRecords": []},
                                {"snapshot_id": "old", "records": [], "flatRecords": [index_row]})
    record_release_manifest(database, manifest)
    folder = root / "verification" / "daily"
    folder.mkdir(parents=True)
    (folder / "20261116.json").write_text(json.dumps({
        "run_date": "2026-11-17", "through": "20261116", "indexes": {"H00300": {
            "status": "REFERENCE_ERROR", "error_type": "ReferenceHTTPError",
            "diagnostic": {"http_status": 403, "endpoint": "CSI index-perf",
                           "requested_at": "2026-11-17T07:42:18+00:00", "attempts": 1}
        }}}, ensure_ascii=False), encoding="utf-8")
    center = build_data_center(root, database)
    item = next(row for row in center["series"] if row["id"] == "index:H00300")
    assert item["acquisition_status"] == "FAILED"
    assert item["fetch_error"]["http_status"] == 403
    assert item["published_date"] == "20261116"
    assert item["release_status"] == "PUBLISHED"
    assert center["series_summary"]["dimensions"]["acquisition_status"]["FAILED"] == 1
    with sqlite3.connect(database) as connection:
        connection.execute("""INSERT INTO raw_observations
            (symbol,kind,trade_date,value_raw,provider,upstream_publisher,fetched_at,raw_sha256,fetch_batch_id)
            VALUES ('H00300','index','20261116','5993.46','CSI official HTTP','CSI',
                    '2026-11-17T08:00:00+00:00','hash','later')""")
    later = build_data_center(root, database)
    recovered = next(row for row in later["series"] if row["id"] == "index:H00300")
    assert recovered["acquisition_status"] == "SUCCEEDED"


@pytest.mark.parametrize("scenario,expected", [
    ("empty", "NO_REFERENCE"),
    ("wrong_code", "NO_REFERENCE"),
    ("price_index", "IDENTITY_CONFLICT"),
    ("point_conflict", "MISMATCH"),
])
def test_unusable_or_conflicting_reference_does_not_change_published_price(
    tmp_path, monkeypatch, scenario, expected
):
    database = tmp_path / "market.db"
    init_reliability_schema(database)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO index_prices VALUES (?,?,?,?,?)",
                           ("20261116", "H00300", 5993.46, "original", "first"))
    (tmp_path / "current_manifest.json").write_text('{"snapshot_id":"original"}', encoding="utf-8")
    before_manifest = (tmp_path / "current_manifest.json").read_bytes()

    class Response:
        ok = True
        status_code = 200
        headers = {"content-type": "application/json"}

        def __init__(self):
            code = "H00918" if scenario == "wrong_code" else "H00300"
            name = "CSI 300 Price Index" if scenario == "price_index" else "CSI 300 Total Return Index (CNY)"
            data = [] if scenario == "empty" else [{"tradeDate": "20261116", "indexCode": code,
                                                     "indexNameEnAll": name,
                                                     "close": 5994.46 if scenario == "point_conflict" else 5993.46}]
            self.content = json.dumps({"success": True, "code": "200", "data": data}).encode()

        def json(self):
            return json.loads(self.content)

    monkeypatch.setattr(verification, "_reference_get", lambda *_args: Response())
    verification.verify(database, tmp_path, ["H00300"], "verify-code")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT status FROM index_verification_results").fetchone()[0] == expected
        assert connection.execute("SELECT close_value,source,updated_at FROM index_prices").fetchone() == (
            5993.46, "original", "first")
    assert (tmp_path / "current_manifest.json").read_bytes() == before_manifest


def test_no_reference_source_cannot_authorize_new_close(tmp_path, monkeypatch):
    database = tmp_path / "market.db"
    init_reliability_schema(database)
    old = {"tradeDate": "20261113", "indexCode": "H00300", "closeValue": 5990.0}
    upsert_market_records_atomic(database, [], [old], "first")
    manifest = publish_snapshot(tmp_path, "old", {"snapshot_id": "old", "records": [], "flatRecords": []},
                                {"snapshot_id": "old", "records": [], "flatRecords": [old]})
    record_release_manifest(database, manifest)
    before = (tmp_path / "current_manifest.json").read_bytes()
    monkeypatch.setattr(verification, "_fetch", lambda *_args: (_ for _ in ()).throw(
        verification.ReferenceHTTPError(403, "0" * 64, "text/html")))
    verification.verify(database, tmp_path, ["H00300"], "verify-daily", start_date="20261113")
    candidate = {"tradeDate": "20261116", "indexCode": "H00300", "closeValue": 5993.46}
    rejected = verification.gate_index_candidates(database, [candidate])
    assert rejected and rejected[0][:2] == ("H00300", "20261116")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*),MAX(trade_date) FROM index_prices").fetchone() == (1, "20261113")
    assert (tmp_path / "current_manifest.json").read_bytes() == before

