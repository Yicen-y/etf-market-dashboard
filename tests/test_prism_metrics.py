import pytest
from datetime import date, timedelta

from scripts.prism_metrics import calculate_prism_metrics


def _weekday_calendar(start: date, count: int) -> list[str]:
    days = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return days


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


def test_prism_metrics_supports_each_strategy_pair_from_python():
    rows = [{"tradeDate": f"2026{i:04d}", "values": {"A": 100 + i, "B": 200 + i}} for i in range(1, 45)]
    result = calculate_prism_metrics(rows, "A", "B")
    assert result[-1]["ratio"] is not None
    assert result[-1]["return40Spread"] is not None


def test_exchange_holiday_does_not_break_trading_day_windows():
    trading_dates = _weekday_calendar(date(2024, 1, 2), 310)
    # Treat one weekday as an exchange holiday. It is not part of the actual
    # trading-day sequence and therefore must not be reported as a data gap.
    exchange_holiday = trading_dates.pop(85)
    rows = [
        {
            "tradeDate": day,
            "values": {"H00300": 3000 + i, "A": 100 + i, "B": 200 + i},
        }
        for i, day in enumerate(trading_dates)
    ]
    rows.append({
        "tradeDate": exchange_holiday,
        "values": {"H00300": 9999, "A": 9999, "B": 9999},
    })
    rows.sort(key=lambda row: row["tradeDate"])

    result = calculate_prism_metrics(rows, "A", "B", trading_dates=trading_dates)

    assert exchange_holiday not in {row["tradeDate"] for row in result}
    assert result[40]["return40Spread"] is not None
    assert result[241]["ratioMa242"] is not None
    assert result[241]["ratioUpper242"] is not None
    assert result[281]["return40Ma242"] is not None
    assert result[255]["rsiMa242"] is not None


def test_missing_observation_on_real_trading_day_is_kept_as_a_gap():
    trading_dates = _weekday_calendar(date(2024, 1, 2), 310)
    missing_day = trading_dates[100]
    rows = []
    for i, day in enumerate(trading_dates):
        values = {"H00300": 3000 + i}
        if day != missing_day:
            values.update({"A": 100 + i, "B": 200 + i})
        rows.append({"tradeDate": day, "values": values})

    result = calculate_prism_metrics(rows, "A", "B", trading_dates=trading_dates)

    assert result[100]["tradeDate"] == missing_day
    assert result[100]["ratio"] is None
    assert result[100]["return40Spread"] is None
    assert result[100]["return40CoverageStatus"] == "MISSING_ENDPOINT"
    assert result[140]["return40Spread"] is None
    assert result[140]["return40CoverageStatus"] == "MISSING_ENDPOINT"
    assert result[120]["return40Spread"] is not None
    assert result[120]["return40CoverageStatus"] == "INTERMEDIATE_GAP"
    assert result[101]["rsi14"] is None
    assert result[114]["rsi14"] is None
    assert result[115]["rsi14"] is not None
    assert result[241]["ratioMa242"] is None


def test_reference_calendar_preserves_a_wholly_missing_trading_day():
    trading_dates = _weekday_calendar(date(2026, 1, 2), 45)
    missing_day = trading_dates[20]
    rows = [
        {"tradeDate": day, "values": {"A": 100 + i, "B": 200 + i}}
        for i, day in enumerate(trading_dates)
        if day != missing_day
    ]

    result = calculate_prism_metrics(rows, "A", "B", trading_dates=trading_dates)

    assert len(result) == len(trading_dates)
    assert result[20]["tradeDate"] == missing_day
    assert result[20]["values"] == {}
    assert result[20]["ratio"] is None
