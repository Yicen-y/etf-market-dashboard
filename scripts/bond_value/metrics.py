"""Daily CSI 300 valuation and equity-versus-bond metrics."""

from __future__ import annotations

from bisect import bisect_right
from math import isfinite


def _positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number > 0 else None


def build_rows(prices, valuations, bond_yields, roe_by_date=None):
    """Join data by equity trading day; carry only the last known bond yield."""
    roe_by_date = roe_by_date or {}
    prices_by_day = {str(row["tradeDate"]): row for row in prices}
    values_by_day = {str(row["tradeDate"]): row for row in valuations}
    yields = sorted(
        (str(row["tradeDate"]), _positive(row.get("yieldPct")))
        for row in bond_yields
        if _positive(row.get("yieldPct")) is not None
    )
    yield_dates = [row[0] for row in yields]
    result = []
    # The index close series defines the canonical equity trading calendar.
    # Valuation-only observations must not create chart dates without an index close.
    for day in sorted(prices_by_day):
        price = prices_by_day.get(day, {})
        valuation = values_by_day.get(day, {})
        pe = _positive(valuation.get("pe"))
        pb = _positive(valuation.get("pb"))
        wind_roe = _positive(roe_by_date.get(day))
        implicit_roe = pb / pe * 100 if pe is not None and pb is not None else None
        roe = wind_roe if wind_roe is not None else implicit_roe
        roe_source = "WIND" if wind_roe is not None else "PE_PB_IMPLIED" if implicit_roe is not None else None
        index = bisect_right(yield_dates, day) - 1
        bond_date, bond_yield = yields[index] if index >= 0 else (None, None)
        result.append({
            "tradeDate": day,
            "close": _positive(price.get("closeValue")),
            "pe": pe,
            "pb": pb,
            "roePct": roe,
            "implicitRoePct": implicit_roe,
            "roeSource": roe_source,
            "cityEarningsRatio": pe / roe if pe is not None and roe is not None else None,
            "earningsYieldPct": 100 / pe if pe is not None else None,
            "bondYieldPct": bond_yield,
            "bondYieldDate": bond_date,
            "equityBondValuePp": 100 / pe - bond_yield if pe is not None and bond_yield is not None else None,
        })
    return result
