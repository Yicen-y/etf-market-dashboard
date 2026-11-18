"""Project a published index snapshot for one chart without recalculating metrics."""

from __future__ import annotations

ETF_INDEX_CODES = ("H00821", "H00918", "H00300")
PRISM_CODES = ("480080", "480081")


def project_index_view(payload: dict, *, strategy: str | None = None,
                       codes: tuple[str, ...] = (), start: str | None = None,
                       end: str | None = None) -> dict:
    if start and end and start > end:
        raise ValueError("start must not be later than end")
    strategies = {item["id"]: item for item in payload["strategies"]}
    if strategy and codes:
        raise ValueError("strategy and codes are mutually exclusive")
    if strategy == "etf-index":
        selected = ETF_INDEX_CODES
    elif strategy == "prism":
        selected = PRISM_CODES
    elif strategy in strategies:
        selected = (strategies[strategy]["a"], strategies[strategy]["b"])
    elif strategy:
        raise ValueError("unknown strategy")
    elif codes and len(codes) == len(set(codes)) and all(code in payload["indexes"] for code in codes):
        selected = codes
    else:
        raise ValueError("provide valid index codes or strategy")

    def in_range(row):
        day = row["tradeDate"]
        return (start is None or day >= start) and (end is None or day <= end)

    rows = []
    for row in payload["records"]:
        if not in_range(row):
            continue
        values = {code: row.get("values", {}).get(code) for code in selected
                  if code in row.get("values", {})}
        if strategy == "prism":
            rows.append({**row, "values": values})
        else:
            rows.append({"tradeDate": row["tradeDate"], "values": values})
    result = {key: value for key, value in payload.items()
              if key not in {"records", "flatRecords", "strategyMetrics", "strategyInputStatus"}}
    result["records"] = rows
    result["indexes"] = {code: payload["indexes"][code] for code in selected}
    if strategy in strategies:
        result["strategyMetrics"] = {
            strategy: [row for row in payload.get("strategyMetrics", {}).get(strategy, []) if in_range(row)]
        }
        result["strategyInputStatus"] = {
            strategy: payload.get("strategyInputStatus", {}).get(strategy)
        }
    return result
