import json
import sqlite3

from scripts.data_center_detail import build_detail


def test_flow_dividend_and_bond_statuses_use_actual_evidence(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        db.executescript("""
          CREATE TABLE fund_flow_etf_daily_metrics(etf_code TEXT,trade_date TEXT,status TEXT);
          CREATE TABLE fund_flow_etf_daily_clean(etf_code TEXT,trade_date TEXT,validation_status TEXT,source_id TEXT);
          CREATE TABLE fund_flow_data_sources(source_id TEXT,retrieved_at TEXT,error_message TEXT);
          CREATE TABLE dividend_events(security_id TEXT,ex_date TEXT,state TEXT,current_revision_id TEXT);
          CREATE TABLE dividend_revisions(revision_id TEXT,source_document_id INTEGER);
          CREATE TABLE source_documents(id INTEGER,publisher TEXT,verification_level TEXT,published_at TEXT,source_id TEXT);
        """)
        db.execute("INSERT INTO fund_flow_etf_daily_metrics VALUES ('510300.SH','2026-11-12','PASS')")
        db.execute("INSERT INTO fund_flow_etf_daily_clean VALUES ('510300.SH','2026-11-12','PASS','akshare:sse:20261112')")
        db.execute("INSERT INTO fund_flow_data_sources VALUES ('akshare:sse:20261112','2026-11-13T18:00:00+08:00',NULL)")
        db.execute("INSERT INTO dividend_events VALUES ('STOCK:600519','2026-06-26','PAID','r1')")
        db.execute("INSERT INTO dividend_revisions VALUES ('r1',NULL)")
    research = tmp_path / "research"
    research.mkdir()
    (research / "bond_value_hs300.json").write_text(json.dumps({
        "status":"READY","updatedAt":"2026-11-09","rows":[{"tradeDate":"20261109"}],
        "sources":{"index":"Wind MCP / 000300.SH"}}),encoding="utf-8")
    detail = build_detail(tmp_path,database,"snapshot","20261113")
    by_id = {item["id"]:item for item in detail["series"]}
    flow = by_id["flow:510300.SH"]
    assert (flow["operational_status"],flow["quality_status"]) == ("STALE","PASS")
    assert flow["actual_source"] == "akshare:sse:20261112"
    assert flow["last_collected_at"] == "2026-11-13T18:00:00+08:00"
    assert by_id["dividend:STOCK:600519"]["operational_status"] == "UNKNOWN"
    assert by_id["bond_value:hs300"]["operational_status"] == "STALE"
    assert detail["series_summary"]["normal"] < detail["series_summary"]["total"]


def test_trailing_source_failure_remains_visible_until_missing_date_arrives(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as db:
        db.executescript("""
          CREATE TABLE index_prices(trade_date TEXT,index_code TEXT,close_value REAL,source TEXT);
          CREATE TABLE quality_issues(issue_id INTEGER PRIMARY KEY,kind TEXT,symbol TEXT,
            trade_date TEXT,issue_code TEXT,detected_at TEXT,resolution_status TEXT);
          INSERT INTO index_prices VALUES ('20261111','H00300',6137.8,'AkShare');
          INSERT INTO quality_issues VALUES (1,'index','H00300','20261112',
            'SOURCE_TRAILING_UNAVAILABLE','2026-11-16T08:00:00+08:00','open');
        """)
    issue = next(row for row in build_detail(tmp_path,database,"old","20261113")["series"]
                 if row["id"] == "index:H00300")
    assert issue["operational_status"] == "FETCH_FAILED"
    assert issue["fetch_error"]["trade_date"] == "20261112"
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO index_prices VALUES ('20261112','H00300',6140.0,'AkShare')")
    resolved = next(row for row in build_detail(tmp_path,database,"old","20261113")["series"]
                    if row["id"] == "index:H00300")
    assert resolved["operational_status"] == "STALE"
