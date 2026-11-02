from pathlib import Path

from scripts.fetch_data import FetchResult
from scripts.update_data import index_fetch_ranges, is_empty_trailing_fetch, merge_records, next_fetch_start, normalize_exchange_trading_dates, records_to_calendar, reference_trading_dates, should_fetch_range
from scripts.validate_data import validate_records


def test_merge_rejects_conflicting_observation_instead_of_silent_overwrite():
    import pytest
    old = [{"tradeDate": "20260105", "productCode": "512530", "closePrice": 1.5}]
    new = [{"tradeDate": "20260105", "productCode": "512530", "closePrice": 1.6}]
    with pytest.raises(ValueError, match="conflicting observation"):
        merge_records(old, new)


def test_merge_keeps_identical_observation_idempotent():
    old = [{"tradeDate": "20260105", "productCode": "512530", "closePrice": 1.5}]
    assert merge_records(old, old)[0]["closePrice"] == 1.5


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
    assert normalize_exchange_trading_dates(["20180615", "20180618", "20180619"]) == [
        "20180615", "20180619"
    ]


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

