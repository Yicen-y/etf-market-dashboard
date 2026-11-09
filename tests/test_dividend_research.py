from datetime import date, timedelta
import pytest

from scripts.dividend.research import ah_common_40, dividend_regression, dividend_spread_and_percentile
from scripts.dividend.research import condition_forward_returns


def rows(values):
    return [{"tradeDate": f"2020{(i // 28 + 1):02d}{(i % 28 + 1):02d}", "closeValue": v} for i, v in enumerate(values)]


def test_full_sample_ols_and_expanding_are_distinct_and_valid():
    start = date(2018, 1, 1)
    data = [{"tradeDate": (start + timedelta(days=i * 30)).strftime("%Y%m%d"),
             "closeValue": 100 * 1.08 ** (((start + timedelta(days=i * 30)) - start).days / 365.2425)} for i in range(40)]
    fixed = dividend_regression(data)
    pit = dividend_regression(data, mode="expanding_point_in_time", expanding_warmup=20)
    assert abs(fixed["annualizedGrowth"] - .08) < 1e-10
    assert fixed["rows"][-1]["mode"] == "fixed_asof"
    assert pit["rows"][0]["z"] is None
    extended = data + [{"tradeDate": "20240401", "closeValue": 2000}]
    pit_extended = dividend_regression(extended, mode="expanding_point_in_time", expanding_warmup=20)
    assert pit["rows"][:-1] == pit_extended["rows"][:-2]


def test_regression_rejects_missing_nonpositive_and_duplicates():
    bad = [{"tradeDate": "20200101", "closeValue": 1}, {"tradeDate": "20200102", "closeValue": 0}]
    try:
        dividend_regression(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid closes must be rejected")


def test_common_day_40_return_spread_requires_41_joint_points():
    a = [{"tradeDate": f"2020{i:04d}", "closeValue": 100 + i} for i in range(1, 43)]
    h = [{"tradeDate": f"2020{i:04d}", "closeValue": 100} for i in range(1, 43)]
    result = ah_common_40(a, h)
    assert result[39]["spread40"] is None
    assert abs(result[40]["spread40"] - (141 / 101 - 1)) < 1e-12
    h_missing = [row for row in h if row["tradeDate"] != "2020020"]
    assert ah_common_40(a, h_missing)[-1]["quality"] == "READY"


def test_dividend_spread_does_not_fabricate_missing_or_short_history_percentile():
    assert dividend_spread_and_percentile(None, 2, [1] * 40)["quality"] == "MISSING_OFFICIAL"
    out = dividend_spread_and_percentile(4.5, 3.2, [1, 2, 3], min_samples=4)
    assert abs(out["spreadPp"] - 1.3) < 1e-12
    assert out["percentile"] is None


def test_expected_joint_calendar_gap_blocks_every_window_crossing_missing_point():
    start = date(2024, 1, 1)
    calendar = [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(55)]
    a = [{"tradeDate": day, "closeValue": 100 + i} for i, day in enumerate(calendar) if i != 10]
    h = [{"tradeDate": day, "closeValue": 100 + i / 2} for i, day in enumerate(calendar)]
    result = ah_common_40(a, h, expected_common_dates=calendar)
    by_day = {row["tradeDate"]: row for row in result}
    assert by_day[calendar[10]]["quality"] == "MISSING_COMMON_OBSERVATION"
    assert by_day[calendar[40]]["spread40"] is None
    assert by_day[calendar[53]]["quality"] == "READY"


def test_pit_z_condition_returns_start_after_signal_close_and_match_baseline():
    prices = [{"tradeDate": f"202001{i:02d}", "closeValue": 100.0 + i} for i in range(1, 9)]
    signals = [{"tradeDate": row["tradeDate"], "z": -2.0 if i == 1 else 0.5, "mode": "expanding_point_in_time"}
               for i, row in enumerate(prices[:-2], start=1)]
    result = condition_forward_returns(signals, prices, horizons=(2,))
    low = next(row for row in result if row["bucket"] == "z_below_minus_1_5")
    expected = prices[3]["closeValue"] / prices[1]["closeValue"] - 1
    assert low["horizon"] == 2
    assert low["meanReturn"] == expected
    assert low["sampleCount"] == 1
    assert low["nonOverlappingCount"] == 1
    baseline = next(row for row in result if row["bucket"] == "all_signals")
    assert low["meanExcessVsUnconditional"] == pytest.approx(low["meanReturn"] - baseline["meanReturn"])
    assert low["excessCi95Low"] <= low["meanExcessVsUnconditional"] <= low["excessCi95High"]
    assert low["meanMaxDrawdown"] == 0
    assert "HAC" in low["uncertaintyMethod"]


def test_condition_return_rejects_retrospective_fixed_asof_signals():
    with pytest.raises(ValueError, match="point-in-time"):
        condition_forward_returns([{"tradeDate": "20200101", "z": -2, "mode": "fixed_asof"}],
                                  [{"tradeDate": "20200101", "closeValue": 100}])
