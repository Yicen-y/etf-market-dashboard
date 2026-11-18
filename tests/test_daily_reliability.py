"""Offline samples for issuer calendar, partial release, and status dimensions."""
import hashlib
import json
import sqlite3

import pytest

from scripts.config import INDEXES
from scripts.daily_verified import _complete_day_cutoff, _daily_metrics, run_daily
from scripts.data_center_detail import _current_etf_checks, build_detail
from scripts.index_convergence import SCHEMA as CONVERGED_SCHEMA, _calendar_status
from scripts.index_verification import collect_cni_route_approvals, expected_identity, gate_index_candidates, migrate
from scripts.fetch_data import FetchResult
from scripts.storage import init_reliability_schema, record_observations, record_quality_issues, save_raw_payload
from scripts.update_data import assess_strategy_inputs, complete_metric_rows, extend_exchange_dates_from_issuer, index_refresh_end_date


def _reference(db, root, code, day, value, *, currency="CNY", valid_hash=True):
    content = f"official {code} {day} {value}".encode()
    archive = root / f"{code}-{day}.raw"
    archive.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest() if valid_hash else "0" * 64
    observed = dict(expected_identity(code), currency=currency)
    batch = f"{code}-{day}"
    db.execute("INSERT OR IGNORE INTO index_verification_runs VALUES ('run','verify-daily','now','{}','COMPLETED',NULL)")
    db.execute("INSERT INTO index_reference_batches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (batch,"run",code,"CNI official HTTPS" if code.startswith("48") else "CSI official HTTP",
                "CNI" if code.startswith("48") else "CSI","{}","2026-11-16T12:00:00Z",
                digest,str(archive),json.dumps({"expected":expected_identity(code),"observed":observed}),
                day,day,"FETCHED"))
    db.execute("INSERT INTO index_reference_observations VALUES (?,?,?,?,?)",(batch,day,0,value,None))


def test_lagging_exchange_calendar_requires_two_archived_weekday_issuer_codes(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        migrate(db)
        _reference(db,tmp_path,"H00300","20261116",5993.46)
        _reference(db,tmp_path,"H00821","20261116",16309.72,valid_hash=False)
        _reference(db,tmp_path,"H00918","20261114",5914.8)
        _reference(db,tmp_path,"H00919","20261114",10303.77)
    assert extend_exchange_dates_from_issuer(database,["20261113"],"20261116") == ["20261113"]
    with sqlite3.connect(database) as db:
        db.execute("UPDATE index_reference_batches SET raw_sha256=? WHERE batch_id='H00821-20261116'",
                   (hashlib.sha256((tmp_path / "H00821-20261116.raw").read_bytes()).hexdigest(),))
    assert extend_exchange_dates_from_issuer(database,["20261113"],"20261116") == ["20261113","20261116"]


def test_daily_cutoff_excludes_unfinished_local_trading_day():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    assert _complete_day_cutoff(datetime(2026,11,17,10,50,tzinfo=ZoneInfo("Asia/Shanghai"))) == "20261116"
    assert _complete_day_cutoff(datetime(2026,11,17,18,0,tzinfo=ZoneInfo("Asia/Shanghai"))) == "20261117"


def test_current_quality_can_pass_while_historical_anomaly_remains(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE index_prices(index_code TEXT,trade_date TEXT,close_value REAL,source TEXT)")
        db.execute("INSERT INTO index_prices VALUES ('H00300','20261116',5993.46,'CSI official HTTP')")
        migrate(db)
        _reference(db,tmp_path,"H00300","20261116",5993.46)
        db.executescript(CONVERGED_SCHEMA)
        db.execute("INSERT INTO index_converged_status VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("H00300","20130101",6000,"PROVENANCE_UNKNOWN",None,"NO_REFERENCE",None,None,None,
                    "NO_REFERENCE",None,"NO_REFERENCE","NO_REFERENCE","NO_USABLE_RESPONSE","NO_EXCEPTION",
                    "NO_REFERENCE","{}","now"))
    item = next(row for row in build_detail(tmp_path,database,None,"20261116")["series"]
                if row["id"] == "index:H00300")
    assert (item["acquisition_status"],item["freshness_status"],item["current_quality_status"],
            item["historical_quality_status"],item["release_status"]) == (
                "SUCCEEDED","CURRENT","PASS","ANOMALY","NOT_PUBLISHED")


def test_etf_current_quality_ignores_older_open_issue_with_recent_corroboration(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE quality_issues(kind TEXT,symbol TEXT,trade_date TEXT,resolution_status TEXT)")
        db.execute("CREATE TABLE raw_observations(kind TEXT,symbol TEXT,trade_date TEXT,raw_record_id INTEGER,provider_request_id TEXT)")
        db.execute("INSERT INTO quality_issues VALUES ('etf','512530','20261113','open')")
        db.execute("INSERT INTO raw_observations VALUES ('etf','512530','20261116',1,?)",
                   (json.dumps({"independent_verification":{"provider":"HTBR","raw_sha256":"a"*64,
                                                             "matched_dates":7}}),))
        tables = {"quality_issues", "raw_observations"}
        latest = {"512530":{"latest_date":"20261116"}}
        assert _current_etf_checks(db, tables, latest)["512530"] == "PASS"
        db.execute("INSERT INTO quality_issues VALUES ('etf','512530','20261116','open')")
        assert _current_etf_checks(db, tables, latest)["512530"] == "ANOMALY"


def test_series_outside_market_snapshot_do_not_claim_snapshot_publication(tmp_path):
    database = tmp_path / "market.db"
    sqlite3.connect(database).close()
    rows = build_detail(tmp_path, database, "snapshot-1", "20261116")["series"]
    assert next(row for row in rows if row["id"] == "bond_value:hs300")["release_status"] == "NOT_APPLICABLE"


def test_h20915_weekend_candidate_requires_native_calendar_review(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        migrate(db)
        _reference(db,tmp_path,"H20915","20261114",12452.26)
    assert gate_index_candidates(database,[{"indexCode":"H20915","tradeDate":"20261114",
                                            "closeValue":12452.26}]) == [
                                                ("H20915","20261114","CALENDAR_REVIEW")]
    assert _calendar_status("H20915","20261107","MATCH") == "CALENDAR_REVIEW"
    assert _calendar_status("H20915","20180618","CALENDAR_EXCEPTION") == "CALENDAR_EXCEPTION"


def test_daily_metrics_do_not_count_reference_coverage_as_publication(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        migrate(db)
        for code in ("480080","480081","H00300"):
            _reference(db,tmp_path,code,"20261116",1000,currency=None if code.startswith("48") else "CNY")
    dates = {code:"20261116" for code in ("480080","480081","H00300")}
    metrics = _daily_metrics(database,tmp_path,dates,"20261116")
    assert metrics["expected_index_count"] == len(INDEXES) - 1  # H20915 has its own unconfirmed calendar.
    assert metrics["latest_fetched_count"] == 3
    assert metrics["quality_gate_pass_count"] == 1
    assert metrics["published_count"] == 0
    assert metrics["indexes"]["480080"]["reason"] == "IDENTITY_UNCONFIRMED"
    assert metrics["indexes"]["H00821"]["reason"] == "REFERENCE_UNAVAILABLE"


def test_daily_metrics_checks_published_close_against_reference(tmp_path, monkeypatch):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        migrate(db)
        for code in ("480080", "480081", "H00300"):
            _reference(db, tmp_path, code, "20261116", 1000)
    import scripts.daily_verified as daily
    monkeypatch.setattr(daily, "read_manifest", lambda *_: {})
    monkeypatch.setattr(daily, "read_dataset", lambda *_: {"flatRecords": [
        {"indexCode": "H00300", "tradeDate": "20261116", "closeValue": 1000.02},
    ]})
    dates = {code: "20261116" for code in ("480080", "480081", "H00300")}
    metrics = _daily_metrics(database, tmp_path, dates, "20261116")
    assert metrics["indexes"]["H00300"]["latest_published"]
    assert not metrics["indexes"]["H00300"]["quality_gate_passed"]
    assert metrics["indexes"]["H00300"]["reason"] == "MISMATCH"


def test_other_channel_below_five_cents_passes_only_with_raw_evidence(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        migrate(db)
        _reference(db, tmp_path, "H00300", "20261116", 1000.0)
    raw = tmp_path / "akshare.raw"
    raw.write_bytes(b"independent channel response")
    candidate = {"indexCode": "H00300", "tradeDate": "20261116", "closeValue": 1000.04,
                 "candidate_provider": "AkShare", "candidate_raw_path": str(raw),
                 "candidate_raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                 "candidate_price_basis": "UNKNOWN"}
    assert gate_index_candidates(database, [candidate]) == []
    assert gate_index_candidates(database, [{**candidate, "closeValue": 1000.05}]) == [
        ("H00300", "20261116", "MISMATCH")]
    assert gate_index_candidates(database, [{**candidate, "candidate_raw_sha256": "0" * 64}]) == [
        ("H00300", "20261116", "SOURCE_EVIDENCE_INCOMPLETE")]
    assert gate_index_candidates(database, [{**candidate, "candidate_provider": "CSI official HTTP"}]) == [
        ("H00300", "20261116", "MISMATCH")]
    assert gate_index_candidates(database, [{**candidate, "candidate_price_basis": "PRICE_INDEX"}]) == [
        ("H00300", "20261116", "IDENTITY_CONFLICT")]


def test_published_alternate_point_rechecks_from_immutable_raw_archive(tmp_path, monkeypatch):
    database = tmp_path / "market.db"
    init_reliability_schema(database)
    with sqlite3.connect(database) as db:
        migrate(db)
        _reference(db, tmp_path, "H00300", "20261116", 1000.0)
        _reference(db, tmp_path, "480080", "20261116", 1000.0)
        _reference(db, tmp_path, "480081", "20261116", 1000.0)
        db.execute("INSERT INTO index_prices VALUES ('20261116','H00300',1000.04,'AkShare','now')")
    archive, digest = save_raw_payload(tmp_path, "fixture", "index-H00300", b"provider response")
    record_observations(database, [{"symbol":"H00300", "kind":"index", "trade_date":"20261116",
                                    "value_raw":"1000.04", "unit_raw":"index_point", "provider":"AkShare",
                                    "upstream_publisher":"CSI", "raw_sha256":digest,
                                    "fetch_batch_id":"fixture", "source_version":"UNKNOWN/v1"}])
    candidate = {"indexCode":"H00300", "tradeDate":"20261116", "closeValue":1000.04}
    assert gate_index_candidates(database, [candidate]) == []
    import scripts.daily_verified as daily
    monkeypatch.setattr(daily, "read_manifest", lambda *_: {})
    monkeypatch.setattr(daily, "read_dataset", lambda *_: {"flatRecords": [candidate]})
    reference_dates = {code:"20261116" for code in ("480080","480081","H00300")}
    daily_status = _daily_metrics(database, tmp_path, reference_dates, "20261116")["indexes"]["H00300"]
    assert daily_status["quality_gate_passed"] and daily_status["latest_published"]
    assert next(row for row in build_detail(tmp_path,database,None,"20261116")["series"]
                if row["id"] == "index:H00300")["current_quality_status"] == "PASS"
    archive.write_bytes(b"tampered")
    assert gate_index_candidates(database, [candidate]) == [("H00300","20261116","MISMATCH")]


def test_daily_metrics_do_not_reuse_prior_reference_as_new_fetch(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        migrate(db)
        for code in ("480080", "480081", "H00300"):
            _reference(db, tmp_path, code, "20261116", 1000)
    dates = {code: "20261116" for code in ("480080", "480081", "H00300")}
    attempts = {code: {"status": "CHECKED"} for code in dates}
    attempts["H00300"] = {"status": "REFERENCE_UNAVAILABLE"}
    metrics = _daily_metrics(database, tmp_path, dates, "20261116", attempts)
    assert metrics["latest_fetched_count"] == 2
    assert metrics["indexes"]["H00300"]["reason"] == "REFERENCE_UNAVAILABLE"
    assert metrics["indexes"]["H00300"]["attempt_status"] == "REFERENCE_UNAVAILABLE"


def test_cni_same_upstream_route_approval_preserves_currency_uncertainty(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        migrate(db)
        _reference(db,tmp_path,"480080","20261116",8187.6154,currency=None)
    candidate = [{"indexCode":"480080","tradeDate":"20261116","closeValue":8187.6154}]
    assert gate_index_candidates(database,candidate) == [("480080","20261116","IDENTITY_UNCONFIRMED")]
    raw = json.dumps([{"日期":"2026-11-16","收盘价":8187.6154}],ensure_ascii=False).encode()
    fetcher = lambda *_: FetchResult(rows=candidate,provider="AkShare",upstream="CNI",request={},raw_bytes=raw)
    assert collect_cni_route_approvals(database,tmp_path,"480080","20261116","20261116",fetcher=fetcher) == ["20261116"]
    assert gate_index_candidates(database,candidate) == []
    collect_cni_route_approvals(database,tmp_path,"480080","20261116","20261116",fetcher=fetcher)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM index_route_approvals").fetchone()[0] == 1
        assert json.loads(db.execute("SELECT identity_json FROM index_reference_batches WHERE index_code='480080'").fetchone()[0])["observed"]["currency"] is None
        path = db.execute("SELECT akshare_path FROM index_route_approvals").fetchone()[0]
    from pathlib import Path
    Path(path).write_bytes(b"changed")
    assert gate_index_candidates(database,candidate) == [("480080","20261116","IDENTITY_UNCONFIRMED")]


def test_cni_route_mismatch_does_not_approve(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        migrate(db)
        _reference(db,tmp_path,"480081","20261116",8218.8424,currency=None)
    candidate = [{"indexCode":"480081","tradeDate":"20261116","closeValue":8218.8924}]
    raw = json.dumps([{"日期":"2026-11-16","收盘价":8218.8924}],ensure_ascii=False).encode()
    fetcher = lambda *_: FetchResult(rows=candidate,provider="AkShare",upstream="CNI",request={},raw_bytes=raw)
    assert collect_cni_route_approvals(database,tmp_path,"480081","20261116","20261116",fetcher=fetcher) == []
    assert gate_index_candidates(database,candidate) == [("480081","20261116","IDENTITY_UNCONFIRMED")]


def test_cni_route_accepts_below_five_cents_with_distinct_saved_values(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        migrate(db)
        _reference(db,tmp_path,"480081","20261116",8218.8424,currency=None)
    candidate = {"indexCode":"480081","tradeDate":"20261116","closeValue":8218.8724}
    raw = json.dumps([{"日期":"2026-11-16","收盘价":8218.8724}],ensure_ascii=False).encode()
    fetcher = lambda *_: FetchResult(rows=[candidate],provider="AkShare",upstream="CNI",request={},raw_bytes=raw)
    assert collect_cni_route_approvals(database,tmp_path,"480081","20261116","20261116",fetcher=fetcher) == ["20261116"]
    with sqlite3.connect(database) as db:
        official, alternate, basis = db.execute(
            "SELECT official_close,akshare_close,approval_basis FROM index_route_approvals").fetchone()
    assert (official,alternate,basis) == (8218.8424,8218.8724,"USER_APPROVED_CHANNEL_POINT_DELTA_LT_0_05")
    archive = tmp_path / "akshare.raw"
    archive.write_bytes(raw)
    evidenced = {**candidate, "candidate_provider":"AkShare", "candidate_raw_path":str(archive),
                 "candidate_raw_sha256":hashlib.sha256(raw).hexdigest()}
    assert gate_index_candidates(database,[evidenced]) == []


def test_strategy_pair_uses_common_date_and_exposes_lag(tmp_path):
    strategy = [{"id":"pair","a":"H00821","b":"H00300"}]
    rows = [{"indexCode":"H00821","tradeDate":"20261116"},
            {"indexCode":"H00300","tradeDate":"20261113"}]
    result = assess_strategy_inputs(rows,{"pair":[{"tradeDate":"20261113"}]},strategy)
    assert result["pair"] == {"inputDates":{"H00821":"20261116","H00300":"20261113"},
                              "effectiveDate":"20261113","status":"LAGGING_INPUT"}
    with pytest.raises(ValueError, match="strategy dependency calendar mismatch"):
        assess_strategy_inputs(rows,{"pair":[{"tradeDate":"20261116"}]},strategy)


def test_strategy_metric_tail_requires_both_valid_index_points():
    rows = [{"tradeDate":"20261113","values":{"480080":10,"480081":20}},
            {"tradeDate":"20261116","values":{"480080":None,"480081":None}}]
    assert [row["tradeDate"] for row in complete_metric_rows(rows,"480080","480081")] == ["20261113"]


def test_lagging_etf_does_not_roll_back_existing_verified_index_tail():
    existing = [{"indexCode":"H00300","tradeDate":"20261116"}]
    assert index_refresh_end_date("20261113",existing,"20261116",True) == "20261116"
    assert index_refresh_end_date("20261113",existing,"20261116",False) == "20261113"


def test_repeated_blocked_candidate_does_not_multiply_open_issue(tmp_path):
    database = tmp_path / "market.db"
    init_reliability_schema(database)
    row = {"symbol":"480080","kind":"index","trade_date":"20261116",
           "issue_code":"REFERENCE_GATE_IDENTITY_UNCONFIRMED","batch_id":"first"}
    record_quality_issues(database,[row])
    record_quality_issues(database,[dict(row,batch_id="second")])
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM quality_issues").fetchone()[0] == 1


def test_daily_publisher_attempts_index_component_after_etf_lag(tmp_path,monkeypatch):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE index_prices(index_code TEXT,trade_date TEXT)")
        db.executemany("INSERT INTO index_prices VALUES (?,?)",[(code,"20261113") for code in INDEXES])
    import scripts.daily_verified as daily
    monkeypatch.setattr(daily,"report",lambda *_:None)
    monkeypatch.setattr(daily,"_reference_dates",lambda *_:{"H00821":"20261116"})
    monkeypatch.setattr(daily,"_daily_metrics",lambda *_: {"indexes":{
        "H00821":{"reference_date":"20261116","published_date":"20261113"}}})
    calls = []
    def publish(**kwargs):
        calls.append(kwargs)
        return {"snapshot_id":f"release-{len(calls)}","indexLatestTradeDate":"20261113" if len(calls)==1 else "20261116",
                "publicationStatus":"UNCHANGED" if len(calls)==1 else "PUBLISHED"}
    result = run_daily(database=database,data_root=tmp_path,through="20261116",publish=True,
                       verifier=lambda *_a,**_k:0,publisher=publish)
    assert calls == [{"require_reference_verification":True,"end_date":"20261116"},
                     {"require_reference_verification":True,"index_only":True,"end_date":"20261116"}]
    assert result["publication"]["status"] == "PUBLISHED"
