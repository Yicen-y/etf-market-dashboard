from scripts.etf_corroboration import compare_closes
from scripts.source_approvals import approved, record_approval
from scripts import etf_reference_verification as verification
from scripts.storage import init_database
from scripts.data_center_detail import build_detail
import sqlite3


def test_independent_close_match_and_conflict():
    candidate = [{"tradeDate": f"2026110{day}", "closePrice": 1 + day / 100} for day in range(1, 6)]
    reference = {row["tradeDate"]: row["closePrice"] for row in candidate}
    assert compare_closes(candidate, reference) == []
    reference["20261105"] = 1.1
    assert compare_closes(candidate, reference) == ["INDEPENDENT_PRICE_CONFLICT:20261105"]
    del reference["20261105"]
    assert compare_closes(candidate, reference) == ["MISSING_INDEPENDENT_QUOTE"]


def test_manual_approval_is_bound_to_exact_raw_digest(tmp_path):
    digest = "a" * 64
    record_approval(tmp_path, "512530", digest, "review-20261114")
    assert approved(tmp_path, "512530", digest) == "review-20261114"
    assert approved(tmp_path, "512530", "b" * 64) is None


def test_reference_verification_is_repeatable_and_requires_intact_raw(tmp_path, monkeypatch):
    database = tmp_path / "market.db"
    init_database(database)
    days = [f"202611{day:02d}" for day in range(9, 16)]
    rows = [{"productCode":"512530","tradeDate":day,"closePrice":1 + i / 1000}
            for i,day in enumerate(days)]
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO etf_prices VALUES (?,?,?,?,?)",(days[-1],"512530",rows[-1]["closePrice"],"AkShare","old"))
    monkeypatch.setattr(verification,"read_manifest",lambda *_:{})
    monkeypatch.setattr(verification,"read_dataset",lambda *_:{"flatRecords":rows})
    fetcher = lambda *_: ({row["tradeDate"]:row["closePrice"] for row in rows},b"fixed HTBR response")
    for _ in range(2):
        assert verification.verify_codes(database,tmp_path,("512530",),fetcher=fetcher)["512530"]["status"] == "PASS"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM etf_reference_checks").fetchone()[0] == 7
        assert verification.verified_close(db,"512530",days[-1],rows[-1]["closePrice"])
        assert not verification.verified_close(db,"512530",days[-1],9.0)
        path = db.execute("SELECT raw_path FROM etf_reference_checks LIMIT 1").fetchone()[0]
        assert db.execute("SELECT close_price,updated_at FROM etf_prices").fetchone() == (rows[-1]["closePrice"],"old")
    series = next(row for row in build_detail(tmp_path,database,None,days[-1])["series"]
                  if row["id"] == "etf:512530")
    assert (series["current_quality_status"],series["source_evidence_level"],series["last_reference_provider"]) == (
        "PASS","HTBR_RAW_MATCH_7D","HTBR")
    from pathlib import Path
    Path(path).write_bytes(b"tampered")
    with sqlite3.connect(database) as db:
        assert not verification.verified_close(db,"512530",days[-1],rows[-1]["closePrice"])
    series = next(row for row in build_detail(tmp_path,database,None,days[-1])["series"]
                  if row["id"] == "etf:512530")
    assert series["current_quality_status"] == "UNVERIFIED"


def test_reference_conflict_does_not_pass(tmp_path, monkeypatch):
    database = tmp_path / "market.db"
    init_database(database)
    rows = [{"productCode":"512530","tradeDate":f"202611{day:02d}","closePrice":1.0}
            for day in range(9,16)]
    monkeypatch.setattr(verification,"read_manifest",lambda *_:{})
    monkeypatch.setattr(verification,"read_dataset",lambda *_:{"flatRecords":rows})
    quotes = {row["tradeDate"]:1.0 for row in rows}
    quotes["20261112"] = 1.01
    result = verification.verify_codes(database,tmp_path,("512530",),fetcher=lambda *_:(quotes,b"raw"))
    assert result["512530"]["status"] == "MISMATCH"
    with sqlite3.connect(database) as db:
        assert not verification.verified_close(db,"512530","20261115",1.0)
