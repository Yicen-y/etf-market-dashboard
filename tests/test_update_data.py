from pathlib import Path

from scripts.fetch_data import FetchResult
from scripts.update_data import align_index_records_to_reference_calendar, index_fetch_ranges, is_empty_trailing_fetch, is_index_date_valid_for_calendar, latest_common_product_date, merge_index_records, merge_records, next_fetch_start, normalize_exchange_trading_dates, records_to_calendar, reference_trading_dates, same_published_market, should_fetch_range
from scripts.validate_data import validate_records


def test_etfirst_fetch_resolves_unified_credential_when_no_explicit_key(monkeypatch):
    import json
    import scripts.fetch_data as fetch_data

    observed = {}

    def run(command, **kwargs):
        observed["command"] = command
        return type("Completed", (), {
            "returncode": 0,
            "stdout": json.dumps({"results": {"getReturnTrendList": {
                "512530": [{"tradeDate": "20260105", "closePrice": "1.23"}]
            }}}).encode(),
            "stderr": b"",
        })()

    monkeypatch.setattr(fetch_data, "get_credential", lambda provider: "configured-etfirst-key")
    monkeypatch.setattr(fetch_data.subprocess, "run", run)
    result = fetch_data.fetch_product_history_etfirst("512530", "20260105", "20260105")

    assert result.rows[0]["closePrice"] == 1.23
    assert observed["command"][-2:] == ["--api-key", "configured-etfirst-key"]
    assert "configured-etfirst-key" not in str(result.request)


def test_etfirst_fetch_keeps_explicit_api_key_compatibility(monkeypatch):
    import json
    import scripts.fetch_data as fetch_data

    observed = {}

    def run(command, **kwargs):
        observed["command"] = command
        return type("Completed", (), {
            "returncode": 0,
            "stdout": json.dumps({"results": {"getReturnTrendList": {
                "512530": []
            }}}).encode(),
            "stderr": b"",
        })()

    monkeypatch.setattr(fetch_data, "get_credential", lambda provider: "stored-key")
    monkeypatch.setattr(fetch_data.subprocess, "run", run)
    fetch_data.fetch_product_history_etfirst("512530", "20260105", "20260105", api_key="explicit-key")

    assert observed["command"][-2:] == ["--api-key", "explicit-key"]


def test_merge_rejects_conflicting_observation_instead_of_silent_overwrite():
    import pytest
    old = [{"tradeDate": "20260105", "productCode": "512530", "closePrice": 1.5}]
    new = [{"tradeDate": "20260105", "productCode": "512530", "closePrice": 1.6}]
    with pytest.raises(ValueError, match="conflicting observation"):
        merge_records(old, new)


def test_merge_keeps_identical_observation_idempotent():
    old = [{"tradeDate": "20260105", "productCode": "512530", "closePrice": 1.5}]
    assert merge_records(old, old)[0]["closePrice"] == 1.5


def test_same_published_market_ignores_refresh_timestamp_but_detects_price_change(tmp_path):
    from scripts.storage import publish_snapshot
    etf = {"snapshot_id": "old", "updatedAt": "old", "providerSummary": {"AkShare": 1},
           "records": [{"tradeDate": "20260105", "prices": {"510330": 1.5}}]}
    index = {"snapshot_id": "old", "updatedAt": "old", "providerSummary": {"AkShare": 1},
             "records": [{"tradeDate": "20260105", "values": {"H00300": 100.0}}]}
    publish_snapshot(tmp_path, "old", etf, index)
    repeated_etf = {**etf, "snapshot_id": "candidate", "updatedAt": "new", "providerSummary": {"AkShare": 2}}
    repeated_index = {**index, "snapshot_id": "candidate", "updatedAt": "new"}
    assert same_published_market(tmp_path, repeated_etf, repeated_index) == "old"
    changed = {**repeated_etf, "records": [{"tradeDate": "20260105", "prices": {"510330": 1.6}}]}
    assert same_published_market(tmp_path, changed, repeated_index) is None


def test_same_published_market_ignores_optional_issuer_fields_but_not_closes(tmp_path):
    from scripts.storage import publish_snapshot
    etf = {"snapshot_id": "old", "records": [{"tradeDate": "20261116"}],
           "flatRecords": [{"productCode": "510330", "tradeDate": "20261116", "closePrice": 1.5}]}
    index = {"snapshot_id": "old", "records": [{"tradeDate": "20261116"}],
             "flatRecords": [{"indexCode": "H00300", "tradeDate": "20261116", "closeValue": 5993.46,
                              "indexNameEnAll": "CSI 300 Total Return Index", "tradingVol": 1000}]}
    publish_snapshot(tmp_path, "old", etf, index)
    candidate = {**index, "snapshot_id": "new", "flatRecords": [
        {"indexCode": "H00300", "tradeDate": "20261116", "closeValue": 5993.46}]}
    assert same_published_market(tmp_path, {**etf, "snapshot_id": "new"}, candidate) == "old"
    candidate["flatRecords"][0]["closeValue"] = 5993.47
    assert same_published_market(tmp_path, {**etf, "snapshot_id": "new"}, candidate) is None


def test_nikkei_overlap_recheck_does_not_rewrite_unchanged_rows(tmp_path):
    import sqlite3
    from scripts.storage import init_reliability_schema, upsert_nikkei_anchor_records
    database = tmp_path / "market.db"
    init_reliability_schema(database)
    row = {"tradeDate": "20261113", "open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0}
    first = upsert_nikkei_anchor_records(database, [row], "first", "WIND_MCP")
    second = upsert_nikkei_anchor_records(database, [row], "second", "WIND_MCP")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT updated_at FROM nikkei225_anchor_prices").fetchone()[0] == "first"
    assert (first["inserted"], first["replaced"], second["changed_dates"]) == (1, 0, [])


def test_nikkei_incomplete_tokyo_session_is_not_a_daily_close():
    from datetime import datetime
    from scripts.nikkei_anchor_sync import _normalize
    names = ("TIME", "OPEN", "MATCH", "HIGH", "LOW", "TURNOVER", "VOLUME")
    row = ["2026-11-16T00:00:00.000+09:00", "100", "101", "102", "99", "1000", "20"]
    payload = {"data": {"columns": [{"name": name} for name in names], "rows": [row]}}
    assert _normalize(payload, now_jst=datetime.fromisoformat("2026-11-16T09:30:00+09:00")) == []
    assert len(_normalize(payload, now_jst=datetime.fromisoformat("2026-11-16T16:00:00+09:00"))) == 1
    payload["data"]["rows"] = [row[:-2] + [None, None]]
    assert _normalize(payload, now_jst=datetime.fromisoformat("2026-11-16T16:00:00+09:00")) == []


def test_nikkei_read_guard_hides_preclose_bar_after_market_closes():
    from datetime import datetime
    from scripts.storage import nikkei_close_is_published
    morning = datetime.fromisoformat("2026-11-16T09:30:00+09:00")
    evening = datetime.fromisoformat("2026-11-16T16:00:00+09:00")
    assert not nikkei_close_is_published("20261116", "2026-11-16T08:30:00+08:00", morning)
    assert not nikkei_close_is_published("20261116", "2026-11-16T08:30:00+08:00", evening)
    assert nikkei_close_is_published("20261116", "2026-11-16T15:45:00+09:00", evening)
    assert nikkei_close_is_published("20261113", "2026-11-13T16:00:00+09:00", morning)


def test_nikkei_final_close_can_replace_equal_preclose_value(tmp_path, monkeypatch):
    import sqlite3
    from scripts import storage
    database = tmp_path / "market.db"
    storage.init_reliability_schema(database)
    row = {"tradeDate": "20261116", "open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0}
    storage.upsert_nikkei_anchor_records(database, [row], "preclose", "WIND_MCP")
    monkeypatch.setattr(storage, "nikkei_close_is_published", lambda *_: False)
    result = storage.upsert_nikkei_anchor_records(database, [row], "afterclose", "WIND_MCP")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT updated_at FROM nikkei225_anchor_prices").fetchone()[0] == "afterclose"
    assert result["replaced"] == 1


def test_validation_rejects_bad_price_and_duplicate():
    rows = [
        {"tradeDate": "20260105", "productCode": "512530", "closePrice": 1.5},
        {"tradeDate": "20260105", "productCode": "512530", "closePrice": 1.5},
        {"tradeDate": "20260106", "productCode": "562310", "closePrice": 0},
    ]
    errors = validate_records(rows, {"512530", "562310", "510330"})
    assert any("duplicate" in e for e in errors)
    assert any("invalid closePrice" in e for e in errors)


def test_records_are_grouped_by_trade_date():
    rows = [{"tradeDate": "20260105", "productCode": "512530", "closePrice": 1.5}]
    assert records_to_calendar(rows) == [{"tradeDate": "20260105", "prices": {"512530": 1.5}}]


def test_next_fetch_start_is_day_after_latest_record():
    rows = [{"tradeDate": "20261028", "productCode": "512530"}]
    assert next_fetch_start(rows, "512530", "20180101", "productCode") == "20261029"


def test_today_is_included_in_fetch_range():
    assert should_fetch_range("20261029", "20261029") is True
    assert should_fetch_range("20261030", "20261029") is False


def test_latest_common_product_date_uses_last_date_available_for_all_etfs():
    rows = [
        {"tradeDate": "20261111", "productCode": "512530", "closePrice": 1.0},
        {"tradeDate": "20261111", "productCode": "562310", "closePrice": 1.0},
        {"tradeDate": "20261111", "productCode": "510330", "closePrice": 1.0},
        {"tradeDate": "20261112", "productCode": "512530", "closePrice": 1.0},
        {"tradeDate": "20261112", "productCode": "562310", "closePrice": 1.0},
        {"tradeDate": "20261112", "productCode": "510330", "closePrice": 1.0},
    ]

    assert latest_common_product_date(rows, {"512530", "562310", "510330"}, "20261113") == "20261112"


def test_latest_common_product_date_does_not_use_partial_latest_date():
    rows = [
        {"tradeDate": "20261111", "productCode": "512530", "closePrice": 1.0},
        {"tradeDate": "20261111", "productCode": "562310", "closePrice": 1.0},
        {"tradeDate": "20261111", "productCode": "510330", "closePrice": 1.0},
        {"tradeDate": "20261112", "productCode": "512530", "closePrice": 1.0},
    ]

    assert latest_common_product_date(rows, {"512530", "562310", "510330"}, "20261113") == "20261111"


def test_empty_tail_after_latest_record_is_not_a_historical_gap():
    empty = FetchResult(
        rows=[],
        provider="AkShare",
        upstream="CNI",
        request={"start_date": "20261031", "end_date": "20261102"},
    )

    assert is_empty_trailing_fetch(empty, "20261031", "20261030") is True
    assert is_empty_trailing_fetch(empty, "20261029", "20261030") is False


def test_nonempty_tail_is_not_treated_as_unpublished():
    result = FetchResult(
        rows=[{"tradeDate": "20261102", "indexCode": "480080", "closeValue": 1234.5}],
        provider="AkShare",
        upstream="CNI",
        request={"start_date": "20261031", "end_date": "20261102"},
    )

    assert is_empty_trailing_fetch(result, "20261031", "20261030") is False


def test_reference_calendar_uses_wind_verified_dates_without_filling_pair_values():
    rows = [
        {"tradeDate": "20260105", "values": {"480080": 5000, "A": 100, "B": 200}},
        {"tradeDate": "20260106", "values": {"480080": 5010}},
        {"tradeDate": "20260107", "values": {"480080": 5020, "A": 102, "B": 202}},
    ]

    assert reference_trading_dates(rows) == ["20260105", "20260106", "20260107"]


def test_normalize_exchange_calendar_removes_officially_closed_day():
    assert normalize_exchange_trading_dates(["20180615", "20180618", "20180619", "20261007", "20261008"]) == [
        "20180615", "20180619", "20261008"
    ]


def test_h00922_can_replace_unverified_history_without_weakening_other_indexes():
    import pytest
    old = [{"tradeDate": "20261008", "indexCode": "H00922", "closeValue": 100.0}]
    new = [{"tradeDate": "20261008", "indexCode": "H00922", "closeValue": 101.0}]
    assert merge_index_records(old, new, replace_codes={"H00922"}) == new
    with pytest.raises(ValueError, match="conflicting index observation"):
        merge_index_records(old, new)


def test_hk_cny_total_return_index_keeps_its_native_observation_dates():
    mainland_dates = {"20260105", "20260106"}
    assert is_index_date_valid_for_calendar("H20915", "20260104", mainland_dates)
    assert not is_index_date_valid_for_calendar("H00922", "20260104", mainland_dates)


def test_reference_calendar_uses_exchange_dates_and_drops_spurious_holiday():
    rows = [
        {"tradeDate": "20180615", "values": {"480080": 5000}},
        {"tradeDate": "20180618", "values": {"480080": 5001}},
        {"tradeDate": "20180619", "values": {"480080": 5002}},
    ]

    assert reference_trading_dates(rows, ["20180615", "20180619"]) == ["20180615", "20180619"]


def test_reference_calendar_rejects_missing_exchange_trading_day():
    import pytest

    rows = [
        {"tradeDate": "20260105", "values": {"480080": 5000}},
        {"tradeDate": "20260107", "values": {"480080": 5002}},
    ]

    with pytest.raises(ValueError, match="missing exchange trading dates"):
        reference_trading_dates(rows, ["20260105", "20260106", "20260107"])


def test_reference_calendar_ignores_unpublished_trailing_exchange_day():
    rows = [
        {"tradeDate": "20261106", "values": {"480080": 5000}},
        # Another series may already have a row for the calendar's current day.
        {"tradeDate": "20261109", "values": {"H00821": 101}},
    ]

    assert reference_trading_dates(rows, ["20261106", "20261109"]) == ["20261106"]


def test_unpublished_series_tail_is_deferred_from_canonical_snapshot():
    rows = [
        {"tradeDate": "20261106", "indexCode": "480080", "closeValue": 5000},
        {"tradeDate": "20261109", "indexCode": "H20903", "closeValue": 4935.12},
    ]

    kept, deferred = align_index_records_to_reference_calendar(rows, ["20261106"])
    assert [row["tradeDate"] for row in kept] == ["20261106"]
    assert deferred[0]["tradeDate"] == "20261109"


def test_index_fetch_ranges_backfills_internal_gap_with_next_trade_day_context():
    rows = [
        {"tradeDate": "20130627", "indexCode": "H20180", "closeValue": 4130.47},
        {"tradeDate": "20130701", "indexCode": "H20180", "closeValue": 4283.64},
        {"tradeDate": "20130702", "indexCode": "H20180", "closeValue": 4243.39},
    ]
    calendar = ["20130627", "20130628", "20130701", "20130702"]

    assert index_fetch_ranges(rows, "H20180", "20121231", "20130702", calendar) == [
        ("20130628", "20130701")
    ]


def test_index_fetch_ranges_does_not_treat_pre_inception_as_gap():
    rows = [
        {"tradeDate": "20121231", "indexCode": "932000CNY010", "closeValue": 1000.0},
        {"tradeDate": "20131231", "indexCode": "932000CNY010", "closeValue": 1000.0},
        {"tradeDate": "20140102", "indexCode": "932000CNY010", "closeValue": 1016.45},
    ]
    calendar = ["20121231", "20130104", "20131227", "20131230", "20131231", "20140102"]

    assert index_fetch_ranges(rows, "932000CNY010", "20131231", "20140102", calendar) == []

