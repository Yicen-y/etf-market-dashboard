import sqlite3

from scripts import resolve_index_issues as resolution
from scripts.storage import init_reliability_schema


def test_only_evidenced_superseded_and_excluded_issues_close(tmp_path, monkeypatch):
    database = tmp_path / "market.db"
    init_reliability_schema(database)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO index_prices VALUES ('20261117','H00300',1000,'CSI official HTTP','old')")
        for code,day,kind in (("H00300","20261117","SOURCE_TRAILING_UNAVAILABLE"),
                              ("H00918","20261114","NON_TRADING_DATE_OBSERVATION"),
                              ("H20915","20261114","REFERENCE_GATE_CALENDAR_REVIEW")):
            db.execute("""INSERT INTO quality_issues(symbol,kind,trade_date,issue_code,severity,detected_at,batch_id)
                VALUES (?,'index',?,?,'WARNING','now','old')""",(code,day,kind))
    monkeypatch.setattr(resolution,"read_manifest",lambda *_:{"snapshot_id":"fixed"})
    monkeypatch.setattr(resolution,"read_dataset",lambda *_:{"flatRecords":[
        {"indexCode":"H00300","tradeDate":"20261117","closeValue":1000}]})
    monkeypatch.setattr(resolution,"gate_index_candidates",lambda *_: [])
    assert resolution.resolve(database,tmp_path) ["eligible"] == 2
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM quality_issues WHERE resolution_status='open'").fetchone()[0] == 3
    assert resolution.resolve(database,tmp_path,apply=True)["eligible"] == 2
    assert resolution.resolve(database,tmp_path,apply=True)["eligible"] == 0
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT resolution_status,COUNT(*) FROM quality_issues GROUP BY resolution_status ORDER BY resolution_status").fetchall() == [
            ("excluded",1),("open",1),("resolved",1)]
        assert db.execute("SELECT close_value,updated_at FROM index_prices").fetchone() == (1000,"old")


def test_missing_reference_does_not_close_trailing_issue(tmp_path, monkeypatch):
    database = tmp_path / "market.db"
    init_reliability_schema(database)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO index_prices VALUES ('20261117','H00300',1000,'CSI official HTTP','old')")
        db.execute("""INSERT INTO quality_issues(symbol,kind,trade_date,issue_code,severity,detected_at,batch_id)
            VALUES ('H00300','index','20261117','SOURCE_TRAILING_UNAVAILABLE','WARNING','now','old')""")
    monkeypatch.setattr(resolution,"read_manifest",lambda *_:{"snapshot_id":"fixed"})
    monkeypatch.setattr(resolution,"read_dataset",lambda *_:{"flatRecords":[
        {"indexCode":"H00300","tradeDate":"20261117","closeValue":1000}]})
    monkeypatch.setattr(resolution,"gate_index_candidates",lambda *_:[("H00300","20261117","NO_REFERENCE")])
    assert resolution.resolve(database,tmp_path,apply=True)["eligible"] == 0
