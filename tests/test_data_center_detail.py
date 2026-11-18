import json
import sqlite3

from scripts.data_center_detail import build_detail, read_index_detail
from scripts.index_convergence import SCHEMA as CONVERGED_SCHEMA
from scripts.index_verification import migrate


def test_one_failed_index_keeps_other_series_normal(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE index_prices(index_code TEXT,trade_date TEXT,close_value REAL,source TEXT)")
        db.executemany("INSERT INTO index_prices VALUES (?,?,?,?)",[
            ("H00300","20261111",6000,"PROVENANCE_UNKNOWN"),
            ("H00821","20261111",5000,"PROVENANCE_UNKNOWN")])
        migrate(db)
        db.execute("INSERT INTO index_verification_runs VALUES ('run','verify-daily','now','{}','COMPLETED',NULL)")
        db.execute("INSERT INTO index_reference_batches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("batch","run","H00300","AkShare","CSI","{}","2026-11-11T00:00:00Z",None,None,"{}",None,None,"UNAVAILABLE"))
        db.execute("INSERT INTO index_reference_failures VALUES (?,?,?,?)",
                   ("batch","signature","2026-11-12T00:00:00Z",json.dumps({"endpoint":"CSI index-perf","http_status":403})))
        db.executescript(CONVERGED_SCHEMA)
        db.execute("""INSERT INTO index_converged_status VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   ("H00300","20261111",6000,"PROVENANCE_UNKNOWN",None,"NO_REFERENCE",None,None,None,
                    "NO_REFERENCE",None,"NO_REFERENCE","NO_REFERENCE","NO_USABLE_RESPONSE","NO_EXCEPTION",
                    "NO_REFERENCE","{}","now"))
    result = build_detail(tmp_path,database,"old-snapshot","20261111")
    by_code = {row["code"]:row for row in result["series"] if row["type"] == "index"}
    assert by_code["H00300"]["operational_status"] == "FETCH_FAILED"
    assert by_code["H00300"]["fetch_error"]["error_type"] == "HTTP_403"
    assert by_code["H00300"]["last_valid_date"] == "20261111"
    assert by_code["H00300"]["previous_release_available"]
    assert by_code["H00821"]["operational_status"] == "UNKNOWN"  # no reference projection in fixture
    assert result["series_summary"]["fetch_failed"] == 1
    detail = read_index_detail(database,"H00300",status="NO_REFERENCE")
    assert len(detail["rows"]) == 1
    assert detail["rows"][0]["trade_date"] == "20261111"
