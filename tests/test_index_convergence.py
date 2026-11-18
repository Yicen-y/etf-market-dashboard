import json
import sqlite3

from scripts import index_convergence as convergence
from scripts.index_verification import migrate, expected_identity


def test_issuer_match_and_vendor_one_cent_disagreement_remain_separate(tmp_path, monkeypatch):
    database = tmp_path / "market.db"
    data_root = tmp_path / "data"
    (data_root / "verification").mkdir(parents=True)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE index_prices(index_code TEXT,trade_date TEXT,close_value REAL,source TEXT,PRIMARY KEY(index_code,trade_date))")
        db.execute("INSERT INTO index_prices VALUES ('H00300','20261110',6112.80,'PROVENANCE_UNKNOWN')")
        migrate(db)
        db.execute("INSERT INTO index_verification_runs VALUES ('run','verify-code','now','{}','COMPLETED',NULL)")
        identity = expected_identity("H00300")
        db.execute("INSERT INTO index_reference_batches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("batch","run","H00300","CSI official HTTP","CSI","{}","now","hash","raw.json",
                    json.dumps({"observed":identity}),"20261110","20261110","FETCHED"))
        db.execute("INSERT INTO index_verification_results VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   ("run","H00300","20261110","MATCH",6112.80,6112.80,0,0,0,"","batch"))
    monkeypatch.setattr(convergence,"official_report",lambda *_: {"anomalies":[]})
    monkeypatch.setattr(convergence,"_htbr_points",lambda *_: {("H00300","20261110"):("now",6112.81,"vendor-hash")})
    monkeypatch.setattr(convergence,"_strategy_impact",lambda *_: {"status":"FIXTURE","strategies":{}})
    for _ in range(2):
        result = convergence.build_convergence(database,data_root)
    assert result["unique_local_days"] == 1
    assert result["indexes"]["H00300"]["issuer_numeric_match"] == 1
    assert result["indexes"]["H00300"]["precision_differences"] == 1
    with sqlite3.connect(database) as db:
        rows = db.execute("SELECT original_source,numeric_status,quality_status FROM index_converged_status").fetchall()
        assert rows == [("PROVENANCE_UNKNOWN","MATCH","PASS")]
        assert db.execute("SELECT close_value,source FROM index_prices").fetchone() == (6112.8,"PROVENANCE_UNKNOWN")


def test_precision_comparison_never_absorbs_one_cent(tmp_path):
    assert convergence._numeric(100.0,100.0,2) == "MATCH"
    assert convergence._numeric(100.0,100.01,2) == "ONE_CENT_DIFFERENCE"
    assert convergence._numeric(100.0,None,2) == "NO_REFERENCE"
    assert convergence._numeric(100.0,0,2) == "INVALID_REFERENCE"
