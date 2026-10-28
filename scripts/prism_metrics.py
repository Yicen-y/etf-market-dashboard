from __future__ import annotations

from typing import Any


GROWTH_CODE = "480080"
VALUE_CODE = "480081"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return (sum((value - mean) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def calculate_prism_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Calculate the original Prism indicators from raw 480080/480081 points."""
    ratios: list[float | None] = []
    for row in rows:
        growth = row.get("values", {}).get(GROWTH_CODE)
        value = row.get("values", {}).get(VALUE_CODE)
        ratios.append(None if growth is None or value in (None, 0) else growth / value)

    changes = [None] + [None if ratios[i] is None or ratios[i - 1] is None else ratios[i] - ratios[i - 1] for i in range(1, len(ratios))]
    gains = [change if change is not None and change > 0 else 0.0 for change in changes]
    losses = [-change if change is not None and change < 0 else 0.0 for change in changes]
    avg_gain = avg_loss = None
    rsi: list[float | None] = [None] * len(rows)
    if len(rows) > 14:
        avg_gain = _mean(gains[1:15])
        avg_loss = _mean(losses[1:15])
        for i in range(14, len(rows)):
            if i > 14:
                avg_gain = (avg_gain * 13 + gains[i]) / 14
                avg_loss = (avg_loss * 13 + losses[i]) / 14
            rsi[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)

    result = []
    for i, row in enumerate(rows):
        growth = row.get("values", {}).get(GROWTH_CODE)
        value = row.get("values", {}).get(VALUE_CODE)
        spread40 = None
        if i >= 40 and growth and value:
            old = rows[i - 40].get("values", {})
            if old.get(GROWTH_CODE) and old.get(VALUE_CODE):
                spread40 = (growth / old[GROWTH_CODE] - 1) - (value / old[VALUE_CODE] - 1)
        window = [x for x in ratios[max(0, i - 241): i + 1] if x is not None]
        ma = _mean(window) if len(window) == min(242, i + 1) else None
        std = _std(window) if ma is not None else None
        result.append({
            "tradeDate": row["tradeDate"],
            "values": row.get("values", {}),
            "ratio": ratios[i],
            "ratioMa242": ma,
            "ratioUpper242": None if ma is None else ma + 2 * std,
            "ratioLower242": None if ma is None else ma - 2 * std,
            "return40Spread": spread40,
            "return40Ma242": None,
            "rsi14": rsi[i],
            "rsiMa242": None,
        })
    spreads = [r["return40Spread"] for r in result]
    for i, row in enumerate(result):
        window = [x for x in spreads[max(0, i - 241): i + 1] if x is not None]
        if len(window) == min(242, i + 1):
            row["return40Ma242"] = _mean(window)
        rsi_window = [x["rsi14"] for x in result[max(0, i - 241): i + 1] if x["rsi14"] is not None]
        if rsi_window and len(rsi_window) == min(242, i - 13):
            row["rsiMa242"] = _mean(rsi_window)
    return result
