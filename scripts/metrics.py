from datetime import date, datetime
from typing import Any


class BenchmarkOutOfRange(ValueError):
    pass


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def resolve_benchmark_date(selected_date: date, trading_dates: list[date]) -> date:
    valid = [d for d in trading_dates if d <= selected_date]
    if not valid:
        raise BenchmarkOutOfRange("选择日期早于可用数据范围")
    return max(valid)


def calculate_metrics(records: list[dict[str, Any]], selected_date: date, products: dict[str, dict]) -> dict[str, Any]:
    dates = [parse_date(row["tradeDate"]) for row in records]
    actual = resolve_benchmark_date(selected_date, dates)
    actual_key = actual.strftime("%Y%m%d")
    by_date = {row["tradeDate"]: row.get("prices", {}) for row in records}
    baseline = by_date[actual_key]
    series = []
    for row in records:
        prices = row.get("prices", {})
        returns = {}
        for code in products:
            price = prices.get(code)
            base = baseline.get(code)
            returns[code] = None if price is None or base is None else price / base - 1
        dividend = returns.get("512530")
        growth = returns.get("562310")
        portfolio = None if dividend is None or growth is None else (dividend + growth) / 2
        difference = None if dividend is None or growth is None else dividend - growth
        series.append({"tradeDate": row["tradeDate"], "prices": prices, "returns": returns,
                       "difference": difference, "portfolio5050": portfolio})
    return {"selectedDate": selected_date.isoformat(), "actualBenchmarkDate": actual.isoformat(),
            "latestTradeDate": parse_date(records[-1]["tradeDate"]).isoformat(), "series": series}

