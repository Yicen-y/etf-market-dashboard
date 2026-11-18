from datetime import date

import pytest

from scripts.metrics import BenchmarkOutOfRange, calculate_metrics, resolve_benchmark_date


def test_weekend_uses_previous_trading_day():
    assert resolve_benchmark_date(date(2026, 1, 1), [date(2025, 12, 31), date(2026, 1, 5)]) == date(2025, 12, 31)


def test_before_range_raises():
    with pytest.raises(BenchmarkOutOfRange):
        resolve_benchmark_date(date(2025, 1, 1), [date(2025, 12, 31)])


def test_metrics_calculate_difference_and_5050():
    records = [
        {"tradeDate": "20251231", "prices": {"512530": 1.0, "562310": 2.0, "510330": 3.0}},
        {"tradeDate": "20260105", "prices": {"512530": 1.1, "562310": 1.8, "510330": 3.3}},
    ]
    result = calculate_metrics(records, date(2026, 1, 1), {"512530": {}, "562310": {}, "510330": {}})
    row = result["series"][1]
    assert row["returns"]["512530"] == pytest.approx(0.1)
    assert row["returns"]["562310"] == pytest.approx(-0.1)
    assert row["difference"] == pytest.approx(0.2)
    assert row["portfolio5050"] == pytest.approx(0.0)


def test_5050_is_initial_equal_weight_buy_and_hold_without_rebalancing():
    records = [
        {"tradeDate": "20260102", "prices": {"512530": 100.0, "562310": 100.0}},
        {"tradeDate": "20260105", "prices": {"512530": 200.0, "562310": 100.0}},
        {"tradeDate": "20260106", "prices": {"512530": 200.0, "562310": 200.0}},
    ]
    result = calculate_metrics(records, date(2026, 1, 2), {"512530": {}, "562310": {}})
    assert [row["portfolio5050"] for row in result["series"]] == pytest.approx([0.0, 0.5, 1.0])

