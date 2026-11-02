"""Read-only comparison of Wind MCP observations against local index prices."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.wind_config import WindIndexMapping


def normalize_wind_rows(
    payload: dict[str, Any], mapping: WindIndexMapping, *, date_field: str, close_field: str,
    rows_field: str = "rows",
) -> list[dict[str, Any]]:
    rows = payload.get(rows_field)
    if not isinstance(rows, list):
        raise ValueError(f"Wind payload missing list field: {rows_field}")
    if not mapping.wind_code:
        raise ValueError(f"Wind instrument mapping is not verified for {mapping.local_code}")
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or date_field not in row or close_field not in row:
            raise ValueError("Wind row has missing or ambiguous date/close fields")
        raw_date = str(row[date_field]).replace("-", "")
        try:
            day = datetime.strptime(raw_date, "%Y%m%d").strftime("%Y%m%d")
            close = float(row[close_field])
        except (TypeError, ValueError):
            raise ValueError("Wind row contains an invalid date or close value") from None
        key = (mapping.local_code, day)
        if not math.isfinite(close) or close <= 0 or key in seen:
            raise ValueError("Wind row contains a non-positive, non-finite, or duplicate observation")
        seen.add(key)
        result.append({"tradeDate": day, "indexCode": mapping.local_code, "closeValue": close})
    return result


def load_local_index_rows(database_path: Path, start_date: str, end_date: str) -> dict[tuple[str, str], float]:
    uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            "SELECT index_code, trade_date, close_value FROM index_prices WHERE trade_date BETWEEN ? AND ?",
            (start_date, end_date),
        ).fetchall()
    return {(code, day): float(value) for code, day, value in rows}


def compare_index_rows(
    local_rows: Mapping[tuple[str, str], float], wind_rows: Sequence[dict[str, Any]], *,
    abs_tolerance: float = 0.0, rel_tolerance: float = 0.0,
) -> list[dict[str, Any]]:
    wind = {(row["indexCode"], row["tradeDate"]): float(row["closeValue"]) for row in wind_rows}
    results = []
    for key in sorted(set(local_rows) | set(wind)):
        local_value, wind_value = local_rows.get(key), wind.get(key)
        if wind_value is None:
            status = "WIND_MISSING"
        elif local_value is None:
            status = "LOCAL_MISSING"
        else:
            delta = abs(wind_value - local_value)
            threshold = max(abs_tolerance, rel_tolerance * abs(wind_value))
            status = "MATCH" if delta <= threshold else "VALUE_MISMATCH"
        delta = abs(wind_value - local_value) if wind_value is not None and local_value is not None else None
        results.append({
            "indexCode": key[0], "tradeDate": key[1], "localValue": local_value,
            "windValue": wind_value, "absoluteDelta": delta,
            "relativeDelta": delta / abs(wind_value) if delta is not None and wind_value else None,
            "status": status,
        })
    return results
