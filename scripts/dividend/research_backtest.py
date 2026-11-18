"""Point-in-time theoretical backtests for A/H dividend total-return indices."""

from __future__ import annotations

from datetime import datetime
import math


def _validated(rows):
    result = []
    previous = None
    for row in rows:
        day = str(row.get("tradeDate", ""))
        try:
            datetime.strptime(day, "%Y%m%d")
        except ValueError:
            raise ValueError(f"invalid trade date: {day}") from None
        if previous is not None and day <= previous:
            raise ValueError("trade dates must be strictly increasing")
        previous = day
        a, h = row.get("aClose"), row.get("hClose")
        for code, value in (("A", a), ("H", h)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{code} index close must be positive on {day}")
        result.append((day, float(a), float(h)))
    return result


def _summary(strategy, wealth, path, turnover, cost, first_signal=None, first_execution=None,
             last_signal_filled=True):
    peak = 0.0
    max_drawdown = 0.0
    for value in path:
        peak = max(peak, value)
        if peak:
            max_drawdown = min(max_drawdown, value / peak - 1)
    return {"strategy": strategy, "initialValue": 1.0, "finalValue": wealth,
            "totalReturn": wealth - 1, "maxDrawdown": max_drawdown, "oneWayTurnover": turnover,
            "estimatedTradingCost": cost, "firstSignalDate": first_signal,
            "firstExecutionDate": first_execution, "lastSignalFilled": last_signal_filled}


class _Portfolio:
    """Two risky assets and cash, charged on the value actually traded."""

    def __init__(self, target, cost_rate):
        self.cost_rate = cost_rate
        self.units = [0.0, 0.0]
        self.cash = 1.0
        self.turnover = 0.0
        self.cost = 0.0
        self.path = []
        self.rebalance(target, (1.0, 1.0))
        self.path.append(self.value((1.0, 1.0)))

    def value(self, prices):
        return self.cash + sum(units * price for units, price in zip(self.units, prices))

    def weights(self, prices):
        wealth = self.value(prices)
        return tuple(units * price / wealth for units, price in zip(self.units, prices))

    def rebalance(self, target, prices):
        wealth = self.value(prices)
        current = self.weights(prices)
        bought = sum(max(a - b, 0) for a, b in zip(target, current))
        sold = sum(max(b - a, 0) for a, b in zip(target, current))
        fee = wealth * (bought + sold) * self.cost_rate
        investable = wealth - fee
        self.units = [investable * weight / price for weight, price in zip(target, prices)]
        self.cash = investable * (1 - sum(target))
        self.turnover += max(bought, sold)
        self.cost += fee

    def mark(self, prices):
        self.path.append(self.value(prices))


def backtest_ah_momentum(rows, *, lookback=40, cost_bps=0.0):
    """Compare theoretical total-return index portfolios on common observed dates.

    D40 is known after close t. Its target allocation is applied at the next
    common observed close, so it first earns returns from that close onward.
    Cost is a proportional one-way turnover haircut at each rebalance.
    """
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 1:
        raise ValueError("lookback must be a positive integer")
    if isinstance(cost_bps, bool) or not isinstance(cost_bps, (int, float)) or not math.isfinite(cost_bps) or not 0 <= cost_bps <= 1000:
        raise ValueError("cost must be finite and between 0 and 1000 bps")
    series = _validated(rows)
    if len(series) < 2:
        raise ValueError("at least two common observations are required")
    cost_rate = float(cost_bps) / 10000
    days = [x[0] for x in series]
    a_values = [x[1] for x in series]
    h_values = [x[2] for x in series]

    portfolios = [_Portfolio(target, cost_rate) for target in ((1.0, 0.0), (0.0, 1.0), (0.5, 0.5), (0.5, 0.5))]
    pending = None
    first_signal = first_execution = None
    last_signal_filled = True

    for i in range(1, len(series)):
        prices = (a_values[i] / a_values[0], h_values[i] / h_values[0])
        portfolios[2].rebalance((0.5, 0.5), prices)

        # Execute yesterday's after-close signal at today's close. This affects
        # the portfolio only from the next common-date interval onwards.
        if pending is not None:
            signal_day, target = pending
            portfolios[3].rebalance(target, prices)
            if first_execution is None:
                first_signal, first_execution = signal_day, days[i]
            pending = None
            last_signal_filled = True
        for portfolio in portfolios:
            portfolio.mark(prices)

        # Signal uses the close on this date; schedule at the following close.
        if i >= lookback:
            d40 = (a_values[i] / a_values[i - lookback] - 1) - (h_values[i] / h_values[i - lookback] - 1)
            target = (1.0, 0.0) if d40 > 0 else (0.0, 1.0)
            pending = (days[i], target)
            last_signal_filled = False

    summaries = [_summary(name, p.path[-1], p.path, p.turnover, p.cost,
                          first_signal if index == 3 else None,
                          first_execution if index == 3 else None,
                          last_signal_filled if index == 3 else True)
                 for index, (name, p) in enumerate(zip(
                     ("buy_hold_a", "buy_hold_h", "daily_rebalanced_50_50", "d40_momentum_switch"), portfolios))]
    return {"assetMode": "theoretical_index", "execution": "signal_close_then_next_common_close",
            "signalRule": f"D{lookback}>0: target A; otherwise target H; signal after close, fill next common close",
            "lookback": lookback, "costBps": float(cost_bps), "returnType": "CNY total return index",
            "dateBasis": "intersection of supplied valid A/H observations; independent holiday calendar not asserted",
            "startDate": days[0], "endDate": days[-1], "observationCount": len(series),
            "summary": summaries,
            "warnings": ["理论指数研究，不代表可交易ETF回测。", "未提供独立港股交易日历；只使用两端共同观测日。",
                         "成本按单边换手比例乘固定bps简化估算，不包含跨境税费、跟踪误差、现金利息和ETF折溢价。"]}
