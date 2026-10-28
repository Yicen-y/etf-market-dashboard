from pathlib import Path

from scripts.update_data import merge_records, next_fetch_start, records_to_calendar
from scripts.validate_data import validate_records


def test_merge_deduplicates_and_prefers_incoming():
    old = [{"tradeDate": "20260105", "productCode": "512530", "closePrice": 1.5}]
    new = [{"tradeDate": "20260105", "productCode": "512530", "closePrice": 1.6}]
    assert merge_records(old, new)[0]["closePrice"] == 1.6


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

