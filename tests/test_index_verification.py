import hashlib
import json
import sqlite3

import pytest

from scripts import index_verification as v


def row(day, value, **extra):
    return {"tradeDate": day, "closeValue": value, **extra}


def test_exact_match_and_precision_boundary():
    result = v.reconcile([row("20260105", 100.00), row("20260106", 101.00)],
                         [row("20260105", 100.00), row("20260106", 101.00)], identity="MATCH")
    assert [x["status"] for x in result] == ["MATCH", "MATCH"]
    assert v.reconcile([row("20260105", 100)], [row("20260105", 100.01)], identity="MATCH")[0]["status"] == "MISMATCH"


def test_parsed_provider_data_does_not_prove_upstream_http_origin():
    result = v.reconcile([row("20260105",100)],[row("20260105",100)],identity="MATCH")
    assert v.require_original_response(result,"AkShare")[0]["status"] == "SOURCE_EVIDENCE_INCOMPLETE"
    result = v.reconcile([row("20260105",100)],[row("20260105",100)],identity="MATCH")
    assert v.require_original_response(result,"CSI official HTTP")[0]["status"] == "MATCH"


def test_missing_duplicate_calendar_and_identity():
    local = [row("20260105", 100), row("20260107", 102)]
    reference = [row("20260105", 100), row("20260106", 101), row("20260107", 102)]
    result = v.reconcile(local, reference, identity="MATCH", calendar={"20260105", "20260106", "20260107"})
    assert result[1]["status"] == "MISSING_LOCAL"
    assert v.reconcile(local[:1]*2,reference[:1],identity="MATCH")[0]["status"] == "DUPLICATE_DATE"
    assert v.reconcile([row("20260104",100)],[row("20260104",100)],identity="MATCH",calendar=set())[0]["status"] == "CALENDAR_EXCEPTION"
    expected = v.expected_identity("H00300")
    assert v.identity_status(expected,{"code":"H00300","return_type":"price","currency":"CNY","publisher":"CSI"}) == "IDENTITY_CONFLICT"


def test_same_upstream_not_independent_and_unavailable():
    assert v.identity_status(v.expected_identity("H00300"), {}) == "NO_REFERENCE"
    assert v.independent_upstreams([{"provider":"AkShare","upstream":"CSI"},
                                    {"provider":"ETFirst","upstream":"CSI"}]) == 1
    assert v.reconcile([row("20260105",100)],[],identity="NO_REFERENCE")[0]["status"] == "NO_REFERENCE"


def test_revision_and_h20180_repair():
    assert v.reconcile([row("20130628", 4100)],[row("20130628", 4101)],identity="MATCH")[0]["status"] == "MISMATCH"
    repaired = v.reconcile([row("20130628", 4100)],
                           [row("20130628",4100,dataStatus="RECOVERED_FROM_NEXT_DAY_ABSOLUTE_CHANGE")],identity="MATCH")
    assert repaired[0]["status"] == "DERIVED_REFERENCE"


def test_h20915_native_calendar():
    assert v._calendar(None,"H20915") is None
    assert v.reconcile([row("20261107",12514.56)],[row("20261107",12514.56)],identity="MATCH",calendar=None)[0]["status"] == "MATCH"


def test_idempotent_and_failure_atomicity(tmp_path, monkeypatch):
    dbpath = tmp_path / "market.db"
    with sqlite3.connect(dbpath) as db:
        db.execute("CREATE TABLE index_prices(trade_date TEXT,index_code TEXT,close_value REAL,source TEXT,updated_at TEXT,PRIMARY KEY(trade_date,index_code))")
        db.execute("INSERT INTO index_prices VALUES ('20260105','H00300',100,'PROVENANCE_UNKNOWN','now')")
    class Fetched:
        rows = [row("20260105",100)]
        provider = "AkShare"
        upstream = "CSI"
        source_url = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
        raw_bytes = b'[{"date":"20260105","close":100}]'
    monkeypatch.setattr(v,"_fetch",lambda *args: Fetched())
    for _ in range(2):
        v.verify(dbpath,tmp_path,["H00300"],"verify-code",batch_size=1)
    with sqlite3.connect(dbpath) as db:
        assert db.execute("SELECT COUNT(*) FROM index_reference_batches").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM index_verification_results").fetchone()[0] == 1
        assert db.execute("SELECT close_value,source FROM index_prices").fetchone() == (100,"PROVENANCE_UNKNOWN")
        db.execute("CREATE TRIGGER fail_reference BEFORE INSERT ON index_reference_observations BEGIN SELECT RAISE(ABORT,'forced'); END")
    with pytest.raises(sqlite3.DatabaseError):
        v.verify(dbpath,tmp_path,["H00300"],"verify-code",batch_size=1)
    with sqlite3.connect(dbpath) as db:
        assert db.execute("SELECT COUNT(*) FROM index_reference_observations").fetchone()[0] == 1
        assert db.execute("SELECT close_value FROM index_prices").fetchone()[0] == 100


def test_snapshot_unchanged(tmp_path, monkeypatch):
    (tmp_path/"index_prices.json").write_bytes(b"published")
    (tmp_path/"current_manifest.json").write_bytes(b"manifest")
    before=hashlib.sha256((tmp_path/"index_prices.json").read_bytes()).hexdigest()
    manifest_before=hashlib.sha256((tmp_path/"current_manifest.json").read_bytes()).hexdigest()
    dbpath=tmp_path/"market.db"
    with sqlite3.connect(dbpath) as db:
        db.execute("CREATE TABLE index_prices(trade_date TEXT,index_code TEXT,close_value REAL,source TEXT,updated_at TEXT,PRIMARY KEY(trade_date,index_code))")
        db.execute("INSERT INTO index_prices VALUES ('20260105','H00300',1,'PROVENANCE_UNKNOWN','now')")
    class Fetched:
        rows=[row("20260105",1)]
        provider="CSI official HTTP"
        upstream="CSI"
        source_url="https://www.csindex.com.cn/csindex-home/perf/index-perf"
        request={"indexCode":"H00300","startDate":"20260105","endDate":"20260106"}
        raw_bytes=b'[{"close":1}]'
    monkeypatch.setattr(v,"_fetch",lambda *args:Fetched())
    v.verify(dbpath,tmp_path,["H00300"],"verify-code")
    assert hashlib.sha256((tmp_path/"index_prices.json").read_bytes()).hexdigest()==before
    assert hashlib.sha256((tmp_path/"current_manifest.json").read_bytes()).hexdigest()==manifest_before
    with sqlite3.connect(dbpath) as db:
        assert db.execute("SELECT close_value,source FROM index_prices").fetchone()==(1,"PROVENANCE_UNKNOWN")


def test_official_http_raw_response_and_403(monkeypatch):
    class Response:
        status_code = 200
        ok = True
        headers = {"content-type":"application/json"}
        content = b'{"success":true,"code":"200","data":[{"tradeDate":"20261110","indexCode":"H00300","indexNameEnAll":"CSI 300 Total Return Index","close":5000.0,"tradingVol":1}]}'
        def json(self): return json.loads(self.content)
    monkeypatch.setattr("requests.get",lambda *args,**kwargs:Response())
    result = v._fetch("H00300","20261110","20261110")
    assert result.provider == "CSI official HTTP"
    assert result.raw_bytes == Response.content
    assert result.rows[0]["closeValue"] == 5000
    Response.status_code = 403; Response.ok = False; Response.content = b"blocked"
    with pytest.raises(v.ReferenceHTTPError) as exc:
        v._fetch("H00300","20261110","20261110")
    assert exc.value.diagnostic["http_status"] == 403
    assert "blocked" not in str(exc.value)


def test_reference_transport_retries_once_without_retrying_http_403(monkeypatch):
    import requests
    monkeypatch.setenv("INDEX_REFERENCE_RETRIES","1")
    monkeypatch.setattr("time.sleep",lambda *_:None)
    calls = []
    def timeout_then_success(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise requests.Timeout("signed secret URL")
        return object()
    monkeypatch.setattr(requests,"get",timeout_then_success)
    assert v._reference_get("https://example.invalid",{}) is not None
    assert len(calls) == 2
    monkeypatch.setattr(requests,"get",lambda *_a, **_k: (_ for _ in ()).throw(requests.Timeout("signed secret URL")))
    with pytest.raises(v.ReferenceTransportError) as exc:
        v._reference_get("https://example.invalid",{})
    assert exc.value.diagnostic == {"error_type":"Timeout","attempts":2}
    assert "secret" not in str(exc.value)


def test_cni_https_raw_response_and_four_decimal_precision(monkeypatch):
    class Response:
        status_code = 200
        ok = True
        headers = {"content-type": "application/json"}
        content = b'{"code":200,"data":{"data":[["2026-11-10",1,2,3,4,123.4567]]}}'
        def json(self): return json.loads(self.content)
    calls = []
    monkeypatch.setattr("requests.get",lambda url,**kwargs: (calls.append((url,kwargs)),Response())[1])
    result = v._fetch("480080","20261110","20261110")
    assert result.provider == "CNI official HTTPS"
    assert result.raw_bytes == Response.content
    assert result.request == {"indexCode":"480080","startDate":"2026-11-10","endDate":"2026-11-10","frequency":"day"}
    assert calls[0][0].startswith("https://hq.cnindex.com.cn/")
    assert result.rows == [{"tradeDate":"20261110","indexCode":"480080","closeValue":123.4567}]
    assert v.reconcile([row("20261110",123.4567)],result.rows,identity="MATCH",decimals=4)[0]["status"] == "MATCH"
    assert v.reconcile([row("20261110",123.4568)],result.rows,identity="MATCH",decimals=4)[0]["status"] == "MISMATCH"
    Response.status_code = 403; Response.ok = False; Response.content = b"blocked"
    with pytest.raises(v.ReferenceHTTPError) as exc:
        v._fetch("480080","20261110","20261110")
    assert exc.value.diagnostic["endpoint"] == "CNI daily-history"


def test_gate_requires_hashed_reference_and_exact_close(tmp_path):
    dbpath = tmp_path / "market.db"
    raw = tmp_path / "evidence.json"
    raw.write_bytes(b"official response")
    sha=hashlib.sha256(raw.read_bytes()).hexdigest()
    with sqlite3.connect(dbpath) as db:
        v.migrate(db)
        db.execute("INSERT INTO index_verification_runs VALUES ('run','verify-daily','now','{}','COMPLETED',NULL)")
        db.execute("INSERT INTO index_reference_batches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("batch","run","H00300","CSI official HTTP","CSI","{}","now",sha,str(raw),
                    json.dumps({"observed":{"code":"H00300","return_type":"total_return","currency":"CNY","publisher":"CSI","base_date":"20041231"}}),"20261110","20261110","FETCHED"))
        db.execute("INSERT INTO index_reference_observations VALUES ('batch','20261110',0,5000,NULL)")
    good={"indexCode":"H00300","tradeDate":"20261110","closeValue":5000}
    assert v.gate_index_candidates(dbpath,[good]) == []
    assert v.gate_index_candidates(dbpath,[{**good,"closeValue":5000.01}]) == [("H00300","20261110","MISMATCH")]
    assert v.gate_index_candidates(dbpath,[{**good,"tradeDate":"20261111"}]) == [("H00300","20261111","NO_REFERENCE")]
    with sqlite3.connect(dbpath) as db:
        db.execute("UPDATE index_reference_batches SET provider='AkShare' WHERE batch_id='batch'")
    assert v.gate_index_candidates(dbpath,[good]) == [("H00300","20261110","SOURCE_EVIDENCE_INCOMPLETE")]
    with sqlite3.connect(dbpath) as db:
        db.execute("UPDATE index_reference_batches SET provider='CSI official HTTP' WHERE batch_id='batch'")
    raw.write_bytes(b"tampered")
    assert v.gate_index_candidates(dbpath,[good]) == [("H00300","20261110","REFERENCE_EVIDENCE_MISSING")]
