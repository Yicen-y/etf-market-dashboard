import json
import sqlite3

import pytest

from scripts.import_wind_alla import SCHEMA
from scripts.wind_alla_incremental import incremental_update, verify_calendar


def _database(tmp_path):
    path = tmp_path / "market.db"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute(
            "INSERT INTO wind_index_daily_prices VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("881001.WI", "2026-11-16", "5508.75", "5436.62", "5508.75", "5410.55",
             "1494156780400", "98688349800", "2026-11-16T00:00:00+08:00", "old-batch"),
        )
    return path


def _response(old_close="5436.62", include_next=False):
    names = ["TIME", "OPEN", "MATCH", "HIGH", "LOW", "TURNOVER", "VOLUME"]
    data = {"data": {"columns": [{"name": name} for name in names], "rows": [
        ["2026-11-16T00:00:00+08:00", "5508.75", old_close, "5508.75", "5410.55", "1494156780400", "98688349800"],
        ["2026-11-17T00:00:00+08:00", "5404.52", "5402.30", "5467.01", "5367.02", "1467516841800", "98707169400"],
    ]}}
    if include_next:
        data["data"]["rows"].append(
            ["2026-11-18T00:00:00+08:00", "5400.00", "5410.00", "5420.00", "5390.00", "100", "100"]
        )
    return json.dumps({"cli_meta": {"server_type": "index_data", "tool_name": "get_index_kline"},
                       "content": [{"text": json.dumps(data)}], "isError": False}).encode()


def test_calendar_mark_pass_and_gap(tmp_path):
    path = _database(tmp_path)
    with sqlite3.connect(path) as db:
        passed = verify_calendar(db, {"2026-11-16"}, "2026-11-16")
        assert passed["status"] == "PASS"
        assert db.execute("SELECT verification_status FROM wind_index_daily_prices").fetchone()[0] == "PASS"
        failed = verify_calendar(db, {"2026-11-16", "2026-11-17"}, "2026-11-17")
        assert failed["status"] == "FAIL"
        assert failed["missing_dates"] == ["2026-11-17"]


def test_incremental_idempotent_and_revision_blocked(tmp_path):
    path = _database(tmp_path)
    calendar = {"2026-11-16", "2026-11-17"}
    result = incremental_update(path, calendar, "2026-11-17", raw_response=_response())
    assert result["status"] == "PASS" and result["inserted_rows"] == 1
    again = incremental_update(path, calendar, "2026-11-17", raw_response=_response())
    assert again["status"] == "UNCHANGED" and again["inserted_rows"] == 0
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM wind_index_daily_prices").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM wind_index_calendar_checks").fetchone()[0] == 1
    with pytest.raises(ValueError, match="historical revision"):
        incremental_update(path, calendar | {"2026-11-18"}, "2026-11-18", raw_response=_response("5436.63", True))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM wind_index_daily_prices").fetchone()[0] == 2


def test_incremental_rejects_missing_or_nontrading_date(tmp_path):
    path = _database(tmp_path)
    raw = json.loads(_response())
    payload = json.loads(raw["content"][0]["text"])
    payload["data"]["rows"].pop()
    raw["content"][0]["text"] = json.dumps(payload)
    with pytest.raises(ValueError, match="Missing Wind trading dates"):
        incremental_update(path, {"2026-11-16", "2026-11-17"}, "2026-11-17",
                           raw_response=json.dumps(raw).encode())
    payload["data"]["rows"].append(
        ["2026-11-14T00:00:00+08:00", "1", "1", "1", "1", "1", "1"]
    )
    raw["content"][0]["text"] = json.dumps(payload)
    with pytest.raises(ValueError, match="Invalid or duplicate Wind trading date"):
        incremental_update(path, {"2026-11-16", "2026-11-17"}, "2026-11-17",
                           raw_response=json.dumps(raw).encode())
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM wind_index_daily_prices").fetchone()[0] == 1
