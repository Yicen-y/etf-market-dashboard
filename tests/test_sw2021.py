import json
import sqlite3
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from scripts import sw2021 as sw


def frame(close=100.0, *, code="801050"):
    return pd.DataFrame([
        {"代码": code, "日期": date(2024, 1, 2), "开盘": 99.0,
         "最高": max(101.0, close), "最低": 98.0, "收盘": close,
         "成交量": 1.2, "成交额": 3.4},
        {"代码": code, "日期": date(2024, 1, 3), "开盘": 101.0,
         "最高": 103.0, "最低": 100.0, "收盘": 102.0,
         "成交量": 1.3, "成交额": 3.5},
    ])


class Provider:
    __version__ = "fixture"

    def __init__(self, response=None):
        self.response = response if response is not None else frame()
        self.calls = []

    def index_hist_sw(self, *, symbol, period):
        self.calls.append((symbol, period))
        return self.response.copy()


def wind_payload(values=(("2024-01-02", "100.00"), ("2024-01-03", "102.00"))):
    return json.dumps({"content": [{"text": json.dumps({"data": {
        "columns": [{"name": "TIME"}, {"name": "MATCH"}],
        "rows": [[day + "T00:00:00.000+08:00", value] for day, value in values]},
        "error": None})}]}).encode()


def collect(db, provider=None):
    return sw.collect_code("801050", db, start=date(2024, 1, 2),
                           end=date(2024, 1, 3), provider=provider or Provider(), attempts=1)


def add_wind(db, tmp_path, values=None, *, end=date(2024, 1, 3)):
    file = tmp_path / "wind.json"
    file.write_bytes(wind_payload(values or (("2024-01-02", "100.00"), ("2024-01-03", "102.00"))))
    return sw.import_wind("801050", "801050.SI", file, db,
                          start=date(2024, 1, 2), end=end)


def test_fixed_31_code_name_mapping():
    assert len(sw.INDUSTRIES) == 31
    assert len(set(sw.INDUSTRIES)) == 31
    assert sw.INDUSTRIES["801050"] == "有色金属"
    assert sw.INDUSTRIES["801980"] == "美容护理"
    assert all(len(code) == 6 and code.isdigit() for code in sw.INDUSTRIES)


def test_parse_akshare_fields_filter_sort_and_duplicate_rejection():
    data = frame().iloc[::-1]
    data.loc[2] = {"代码": "801050", "日期": date(2018, 12, 28),
                   "开盘": 1, "最高": 1, "最低": 1, "收盘": 1,
                   "成交量": 1, "成交额": 1}
    rows = sw.parse_akshare(data, "801050", date(2024, 1, 2), date(2024, 1, 3))
    assert [row["trade_date"] for row in rows] == ["2024-01-02", "2024-01-03"]
    assert rows[0]["close"] == 100.0
    with pytest.raises(ValueError, match="fields missing"):
        sw.parse_akshare(frame().drop(columns="收盘"), "801050", date(2024, 1, 2), date(2024, 1, 3))
    with pytest.raises(ValueError, match="duplicate date"):
        sw.parse_akshare(pd.concat([frame(), frame()]), "801050", date(2024, 1, 2), date(2024, 1, 3))


@pytest.mark.parametrize("change,expected", [({"close": 0}, "FAILED"),
    ({"high": 90}, "FAILED"), ({"volume": -1}, "FAILED"),
    ({"close": 140, "high": 141}, "REVIEW")])
def test_local_qc_rejects_invalid_prices_and_flags_jumps(change, expected):
    row = {"open": 99, "high": 101, "low": 98, "close": 100,
           "volume": 1.2, "amount": 3.4, **change}
    assert sw.qc_status(row, previous_close=100)[0] == expected


def test_empty_response_retries_and_fails():
    provider = Provider(pd.DataFrame())
    with pytest.raises(RuntimeError, match="after 2 attempts"):
        sw.fetch_akshare("801050", provider, attempts=2, delay=0)
    assert len(provider.calls) == 2


def test_collection_idempotence_revision_trace_and_existing_data_unchanged(tmp_path):
    db = tmp_path / "market.db"
    sw.migrate(db)
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO index_prices VALUES ('2024-01-02','H00300',1234,'EXISTING','now')")
    first = collect(db)
    second = collect(db)
    assert first["inserted"] == 2 and second["inserted"] == 0
    assert second["revised"] == 0
    changed = Provider(frame(close=100.5))
    third = collect(db, changed)
    assert third["revised"] == 1
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM sw2021_daily").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM sw2021_daily_revisions").fetchone()[0] == 1
        assert con.execute("SELECT close_value FROM index_prices WHERE index_code='H00300'").fetchone()[0] == 1234
        assert con.execute("SELECT COUNT(*) FROM raw_observations WHERE kind='sw2021_index'").fetchone()[0] == 3


def test_one_code_failure_does_not_stop_other_code(tmp_path):
    class Partial(Provider):
        def index_hist_sw(self, *, symbol, period):
            if symbol == "801040":
                raise OSError("source unavailable")
            return frame(code=symbol)
    result = sw.collect_many(["801040", "801050"], tmp_path / "market.db",
                             start=date(2024, 1, 2), end=date(2024, 1, 3),
                             provider=Partial(), rate_delay=0)
    assert [x["status"] for x in result] == ["FAILED", "COMPLETED"]


def test_wind_parser_actual_envelope_and_errors():
    rows = sw.parse_wind_snapshot(wind_payload(), "801050", date(2024, 1, 2), date(2024, 1, 3))
    assert rows == [("2024-01-02", 100.0), ("2024-01-03", 102.0)]
    with pytest.raises(ValueError, match="Wind MCP error"):
        sw.parse_wind_snapshot(b'{"ok":false,"code":"AUTH_ERROR","message":"denied"}', "801050", date(2024, 1, 2), date(2024, 1, 3))
    with pytest.raises(ValueError, match="empty history"):
        sw.parse_wind_snapshot(wind_payload(()), "801050", date(2024, 1, 2), date(2024, 1, 3))


def test_wind_verification_conflicts_missing_and_resume(tmp_path):
    db = tmp_path / "market.db"
    collect(db)
    first = add_wind(db, tmp_path)
    second = add_wind(db, tmp_path)
    assert first["batch_id"] == second["batch_id"]
    assert sw.verify_code("801050", db)["status_counts"] == {"VERIFIED": 2}
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM sw2021_approved_daily").fetchone()[0] == 2
    add_wind(db, tmp_path, (("2024-01-02", "101"), ("2024-01-03", "102")))
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT status FROM sw2021_verification WHERE trade_date='2024-01-02'").fetchone()[0] == "STALE"
    assert sw.verify_code("801050", db, threshold=Decimal("0.0001"))["status_counts"] == {"CONFLICT": 1, "VERIFIED": 1}
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM sw2021_approved_daily").fetchone()[0] == 1


def test_wind_missing_date_and_unavailable_code(tmp_path):
    db = tmp_path / "market.db"
    collect(db)
    assert sw.verify_code("801050", db)["status"] == "WIND_UNAVAILABLE"
    add_wind(db, tmp_path, (("2024-01-02", "100"),))
    assert sw.verify_code("801050", db)["status_counts"] == {"VERIFIED": 1, "WIND_MISSING": 1}


def test_ak_revision_blocks_release_until_reverified(tmp_path):
    db = tmp_path / "market.db"
    collect(db)
    add_wind(db, tmp_path)
    sw.verify_code("801050", db)
    collect(db, Provider(frame(close=100.5)))
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM sw2021_approved_daily").fetchone()[0] == 1
    assert sw.verify_code("801050", db)["status_counts"] == {"CONFLICT": 1, "VERIFIED": 1}


def test_calendar_missing_day_and_report(tmp_path):
    db = tmp_path / "market.db"
    collect(db)
    with sqlite3.connect(db) as con:
        con.executemany("INSERT INTO sw2021_trade_calendar VALUES (?,'fixture')",
                        [("2024-01-02",), ("2024-01-03",), ("2024-01-04",)])
    report = sw.build_report(db, start=date(2024, 1, 2), end=date(2024, 1, 4))
    item = next(x for x in report["industries"] if x["code"] == "801050")
    assert item["missing_trading_days"] == 1
    assert item["max_consecutive_missing"] == 1
    assert item["verification_status"] == "WIND_UNAVAILABLE"


def test_bad_akshare_row_is_quarantined_with_raw_issue(tmp_path):
    db = tmp_path / "market.db"
    bad = frame()
    bad.loc[0, "收盘"] = 0
    result = collect(db, Provider(bad))
    assert result["status"] == "PARTIAL" and result["qc_failed"] == 1
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM sw2021_daily").fetchone()[0] == 1
        issue = con.execute("SELECT issue_code,raw_record_id FROM quality_issues WHERE kind='sw2021_index'").fetchone()
        assert issue[0] == "INVALID_PRICE" and issue[1] is not None
    collect(db, Provider(frame()))
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT resolution_status FROM quality_issues WHERE kind='sw2021_index'").fetchone()[0] == "resolved"


def test_wind_import_failure_is_logged_and_recoverable(tmp_path):
    db = tmp_path / "market.db"
    file = tmp_path / "wind.json"
    file.write_text('{"ok":false,"code":"AUTH_ERROR","message":"denied"}', encoding="utf-8")
    with pytest.raises(ValueError, match="AUTH_ERROR"):
        sw.import_wind("801050", "801050.SI", file, db,
                       start=date(2024, 1, 2), end=date(2024, 1, 3))
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT status FROM sw2021_wind_batches").fetchone()[0] == "FAILED"
    file.write_bytes(wind_payload())
    assert sw.import_wind("801050", "801050.SI", file, db,
                          start=date(2024, 1, 2), end=date(2024, 1, 3))["rows"] == 2
    with pytest.raises(ValueError, match="mapping"):
        sw.import_wind("801050", "801040.SI", file, db,
                       start=date(2024, 1, 2), end=date(2024, 1, 3))


def test_wind_only_date_is_recorded_and_not_released(tmp_path):
    db = tmp_path / "market.db"
    collect(db)
    add_wind(db, tmp_path, (("2024-01-02", "100"), ("2024-01-03", "102"),
                            ("2024-01-04", "103")), end=date(2024, 1, 4))
    result = sw.verify_code("801050", db)
    assert result["status_counts"] == {"VERIFIED": 2, "AK_MISSING": 1}
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM sw2021_approved_daily").fetchone()[0] == 2


def test_new_industry_prelaunch_wind_history_is_marked_backfill(tmp_path):
    db = tmp_path / "market.db"
    file = tmp_path / "wind.json"
    file.write_bytes(wind_payload((("2020-01-02", "100"),)))
    sw.import_wind("801960", "801960.SI", file, db,
                   start=date(2020, 1, 2), end=date(2020, 1, 2))
    assert sw.verify_code("801960", db)["status_counts"] == {"HISTORICAL_BACKFILL_ONLY": 1}


def test_wind_revision_preserves_prior_close_and_stales_result(tmp_path):
    db = tmp_path / "market.db"
    collect(db)
    add_wind(db, tmp_path)
    sw.verify_code("801050", db)
    add_wind(db, tmp_path, (("2024-01-02", "100.2"), ("2024-01-03", "102")))
    with sqlite3.connect(db) as con:
        revision = con.execute("SELECT old_close,new_close FROM sw2021_wind_revisions").fetchone()
        assert revision == (100.0, 100.2)
        assert con.execute("SELECT status FROM sw2021_verification WHERE trade_date='2024-01-02'").fetchone()[0] == "STALE"


def test_report_files_are_structured_and_human_readable(tmp_path):
    db = tmp_path / "market.db"
    collect(db)
    add_wind(db, tmp_path)
    sw.verify_code("801050", db)
    with sqlite3.connect(db) as con:
        con.executemany("INSERT INTO sw2021_trade_calendar VALUES (?,'fixture')",
                        [("2024-01-02",), ("2024-01-03",)])
    report = sw.build_report(db, start=date(2024, 1, 2), end=date(2024, 1, 3))
    md, data, exceptions = sw.write_report(report, tmp_path / "report")
    assert "申万2021版31行业数据验收" in md.read_text(encoding="utf-8")
    assert json.loads(data.read_text(encoding="utf-8"))["totals"]["wind_common_rows"] == 2
    assert exceptions.exists()
