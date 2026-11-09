from datetime import date, timedelta
import pytest

from scripts.dividend.research_backtest import backtest_ah_momentum


def _rows(a, h):
    return [
        {"tradeDate": (date(2024, 1, 1) + timedelta(days=i)).strftime("%Y%m%d"), "aClose": av, "hClose": hv}
        for i, (av, hv) in enumerate(zip(a, h))
    ]


def test_ah_backtest_has_buy_hold_and_equal_weight_baselines_and_t_plus_one_signal():
    # A leads over the 40-interval lookback; after the signal close, the
    # strategy must wait until the next common close before switching.
    series = _rows([100 + 2 * i for i in range(1, 46)], [100 + i for i in range(1, 46)])
    result = backtest_ah_momentum(series, lookback=40)

    assert result["assetMode"] == "theoretical_index"
    assert result["execution"] == "signal_close_then_next_common_close"
    assert {item["strategy"] for item in result["summary"]} == {
        "buy_hold_a", "buy_hold_h", "daily_rebalanced_50_50", "d40_momentum_switch"
    }
    switch = next(item for item in result["summary"] if item["strategy"] == "d40_momentum_switch")
    assert switch["firstSignalDate"] == "20240210"
    assert switch["firstExecutionDate"] == "20240211"
    assert switch["lastSignalFilled"] is False


def test_ah_backtest_rejects_gaps_nonpositive_prices_and_invalid_costs():
    with pytest.raises(ValueError, match="strictly increasing"):
        backtest_ah_momentum([{"tradeDate": "20240102", "aClose": 1, "hClose": 1},
                              {"tradeDate": "20240101", "aClose": 1, "hClose": 1}])
    with pytest.raises(ValueError, match="positive"):
        backtest_ah_momentum([{"tradeDate": "20240101", "aClose": 0, "hClose": 1}])
    with pytest.raises(ValueError, match="cost"):
        backtest_ah_momentum([], cost_bps=-1)


def test_ah_backtest_costs_reduce_switching_strategy_value():
    series = _rows([100 + 2 * i for i in range(1, 46)], [100 + i for i in range(1, 46)])
    free = backtest_ah_momentum(series, lookback=40, cost_bps=0)
    charged = backtest_ah_momentum(series, lookback=40, cost_bps=20)
    free_value = next(x["finalValue"] for x in free["summary"] if x["strategy"] == "d40_momentum_switch")
    charged_value = next(x["finalValue"] for x in charged["summary"] if x["strategy"] == "d40_momentum_switch")
    assert charged_value <= free_value
    charged_buy_a = next(x for x in charged["summary"] if x["strategy"] == "buy_hold_a")
    assert charged_buy_a["estimatedTradingCost"] > 0
    assert charged_buy_a["oneWayTurnover"] == 1
