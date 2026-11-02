from __future__ import annotations

from typing import Any


GROWTH_CODE = "480080"
VALUE_CODE = "480081"
PRISM_FORMULA_VERSION = "prism-v4-exchange-calendar"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return (sum((value - mean) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def _align_to_trading_calendar(
    rows: list[dict[str, Any]], trading_dates: list[str] | None
) -> list[dict[str, Any]]:
    """Align observations to an explicit exchange trading-day sequence.

    Missing observations are represented by an empty ``values`` mapping.  No
    value is interpolated or carried forward.  When no calendar is supplied,
    the ordered input dates are treated as the already-validated trading-day
    sequence for backwards compatibility with callers and unit tests.
    """
    row_by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        trade_date = row.get("tradeDate")
        if not trade_date:
            raise ValueError("prism row is missing tradeDate")
        if trade_date in row_by_date:
            raise ValueError(f"duplicate prism tradeDate: {trade_date}")
        row_by_date[trade_date] = row

    calendar = list(trading_dates) if trading_dates is not None else list(row_by_date)
    if calendar != sorted(calendar) or len(calendar) != len(set(calendar)):
        raise ValueError("trading_dates must be sorted and unique")
    return [
        row_by_date.get(trade_date, {"tradeDate": trade_date, "values": {}})
        for trade_date in calendar
    ]


def calculate_prism_metrics(
    rows: list[dict[str, Any]],
    growth_code: str = GROWTH_CODE,
    value_code: str = VALUE_CODE,
    *,
    trading_dates: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Calculate Prism indicators for one aligned pair of index codes."""
    rows = _align_to_trading_calendar(rows, trading_dates)
    ratios: list[float | None] = []
    for row in rows:
        growth = row.get("values", {}).get(growth_code)
        value = row.get("values", {}).get(value_code)
        ratios.append(None if growth is None or value in (None, 0) else growth / value)

    changes = [None] + [None if ratios[i] is None or ratios[i - 1] is None else ratios[i] - ratios[i - 1] for i in range(1, len(ratios))]
    gains = [None if change is None else max(change, 0.0) for change in changes]
    losses = [None if change is None else max(-change, 0.0) for change in changes]
    avg_gain = avg_loss = None
    rsi: list[float | None] = [None] * len(rows)
    for i in range(14, len(rows)):
        change_window = changes[i - 13:i + 1]
        if any(change is None for change in change_window):
            avg_gain = avg_loss = None
            continue
        if avg_gain is None or avg_loss is None:
            avg_gain = _mean([value for value in gains[i - 13:i + 1] if value is not None])
            avg_loss = _mean([value for value in losses[i - 13:i + 1] if value is not None])
        else:
            avg_gain = (avg_gain * 13 + gains[i]) / 14
            avg_loss = (avg_loss * 13 + losses[i]) / 14
        if avg_gain == 0 and avg_loss == 0:
            rsi[i] = 50.0
        elif avg_loss == 0:
            rsi[i] = 100.0
        else:
            rsi[i] = 100 - 100 / (1 + avg_gain / avg_loss)

    result = []
    for i, row in enumerate(rows):
        growth = row.get("values", {}).get(growth_code)
        value = row.get("values", {}).get(value_code)
        spread40 = None
        spread_coverage = "INSUFFICIENT_HISTORY" if i < 40 else "MISSING_ENDPOINT"
        if i >= 40 and growth not in (None, 0) and value not in (None, 0):
            old = rows[i - 40].get("values", {})
            if old.get(growth_code) and old.get(value_code):
                spread40 = (growth / old[growth_code] - 1) - (value / old[value_code] - 1)
                spread_coverage = (
                    "PASS"
                    if all(value is not None for value in ratios[i - 40:i + 1])
                    else "INTERMEDIATE_GAP"
                )
        ratio_window = ratios[max(0, i - 241): i + 1]
        complete_ratio_window = len(ratio_window) == 242 and all(value is not None for value in ratio_window)
        ma = _mean(ratio_window) if complete_ratio_window else None
        std = _std(ratio_window) if ma is not None else None
        result.append({
            "tradeDate": row["tradeDate"],
            "values": row.get("values", {}),
            "ratio": ratios[i],
            "ratioMa242": ma,
            "ratioUpper242": None if ma is None else ma + 2 * std,
            "ratioLower242": None if ma is None else ma - 2 * std,
            "return40Spread": spread40,
            "return40CoverageStatus": spread_coverage,
            "return40Ma242": None,
            "rsi14": rsi[i],
            "rsiMa242": None,
        })
    spreads = [r["return40Spread"] for r in result]
    for i, row in enumerate(result):
        spread_window = spreads[max(0, i - 241): i + 1]
        if len(spread_window) == 242 and all(value is not None for value in spread_window):
            row["return40Ma242"] = _mean(spread_window)
        rsi_window = [x["rsi14"] for x in result[max(0, i - 241): i + 1]]
        if len(rsi_window) == 242 and all(value is not None for value in rsi_window):
            row["rsiMa242"] = _mean(rsi_window)
    return result


def trim_to_analysis_ready(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hide only the leading formula warm-up, preserving later real gaps."""
    required = ("ratio", "ratioMa242", "return40Spread", "return40Ma242", "rsi14", "rsiMa242")
    for position, row in enumerate(rows):
        if all(row.get(field) is not None for field in required):
            return rows[position:]
    return []
