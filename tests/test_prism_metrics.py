import pytest

from scripts.prism_metrics import calculate_prism_metrics


def test_prism_uses_raw_index_ratio_and_40_day_spread():
    rows = [
        {"tradeDate": f"2025{i:04d}", "values": {"480080": 100 + i, "480081": 200 + i}}
        for i in range(1, 43)
    ]
    result = calculate_prism_metrics(rows)
    row = result[-1]
    assert row["ratio"] == pytest.approx(142 / 242)
    assert row["return40Spread"] == pytest.approx((142 / 102 - 1) - (242 / 202 - 1))


def test_prism_rsi_is_bounded_and_requires_history():
    rows = [
        {"tradeDate": f"2025{i:04d}", "values": {"480080": 100 + i, "480081": 200}}
        for i in range(1, 20)
    ]
    result = calculate_prism_metrics(rows)
    assert result[0]["rsi14"] is None
    assert 0 <= result[-1]["rsi14"] <= 100


def test_prism_has_242_day_rsi_average():
    rows = [
        {"tradeDate": f"2025{i:04d}", "values": {"480080": 100 + i, "480081": 200}}
        for i in range(1, 260)
    ]
    result = calculate_prism_metrics(rows)
    assert result[-1]["rsiMa242"] is not None


def test_242_day_indicators_are_blank_before_full_window():
    rows = [
        {"tradeDate": f"2025{i:04d}", "values": {"480080": 100 + i, "480081": 200}}
        for i in range(1, 100)
    ]
    result = calculate_prism_metrics(rows)
    assert result[-1]["ratioMa242"] is None
    assert result[-1]["ratioUpper242"] is None
    assert result[-1]["return40Ma242"] is None
