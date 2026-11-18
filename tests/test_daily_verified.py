import json
import sqlite3

from scripts.config import INDEXES
from scripts import daily_verified
from scripts.update_data import retain_unadjudicated_history


def _database(tmp_path):
    database = tmp_path / "market.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE index_prices (index_code TEXT, trade_date TEXT)")
        connection.executemany("INSERT INTO index_prices VALUES (?,?)",
                               [(code, day) for code in INDEXES for day in
                                ("20261110", "20261111", "20261112")])
    return database


def test_daily_isolates_reference_failure_and_preserves_previous_data(tmp_path, monkeypatch):
    database = _database(tmp_path)
    before = database.read_bytes()
    monkeypatch.setattr(daily_verified, "report", lambda *_: None)
    calls = []

    def verify(_db, _root, codes, mode, **kwargs):
        calls.append((codes[0], mode, kwargs["start_date"], kwargs["end_date"]))
        return 1 if codes[0] == "H00918" else 0

    def withhold(**kwargs):
        assert kwargs["require_reference_verification"] is True
        raise ValueError("reference verification gate blocked 1 index candidates")

    result = daily_verified.run_daily(database=database, data_root=tmp_path,
                                      overlap_days=2, through="20261113",
                                      verifier=verify, publisher=withhold)
    assert len(calls) == len(INDEXES)
    assert all(start == "20261111" for _, _, start, _ in calls)
    assert result["indexes"]["H00918"]["status"] == "REFERENCE_UNAVAILABLE"
    assert result["indexes"]["H00300"]["status"] == "CHECKED"
    assert result["publication"]["reason"] == "REFERENCE_GATE_BLOCKED"
    assert database.read_bytes() == before
    saved = json.loads((tmp_path / "verification/daily/20261113.json").read_text(encoding="utf-8"))
    assert saved == result


def test_daily_repeated_run_replaces_one_diagnostic_and_is_recoverable(tmp_path, monkeypatch):
    database = _database(tmp_path)
    monkeypatch.setattr(daily_verified, "report", lambda *_: None)
    def unavailable(*_args, **_kwargs):
        raise TimeoutError("secret endpoint")
    first = daily_verified.run_daily(database=database,data_root=tmp_path,through="20261113",
                                     verifier=unavailable,publish=False)
    assert first["indexes"]["H00300"]["error_type"] == "TimeoutError"
    assert "secret" not in (tmp_path / "verification/daily/20261113.json").read_text(encoding="utf-8")
    second = daily_verified.run_daily(database=database,data_root=tmp_path,through="20261113",
                                      verifier=lambda *_a, **_k: 0,publish=False)
    assert second["indexes"]["H00300"]["status"] == "CHECKED"
    assert len(list((tmp_path / "verification/daily").glob("*.json"))) == 1


def test_unadjudicated_weekend_stays_in_flat_history():
    old = [{"indexCode":"H20915","tradeDate":"20261107","closeValue":2000.0},
           {"indexCode":"H20915","tradeDate":"20261109","closeValue":2000.0}]
    selected = [old[1]]
    assert retain_unadjudicated_history(old, selected) == old


def test_daily_does_not_call_an_empty_window_checked(tmp_path, monkeypatch):
    database = _database(tmp_path)
    monkeypatch.setattr(daily_verified,"report",lambda *_:None)
    result = daily_verified.run_daily(database=database,data_root=tmp_path,
                                      overlap_days=2,through="20200101",publish=False,
                                      verifier=lambda *_a,**_k: (_ for _ in ()).throw(AssertionError("no request")))
    assert all(item["status"] == "NO_WINDOW" for item in result["indexes"].values())
