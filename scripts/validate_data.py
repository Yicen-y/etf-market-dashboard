from datetime import datetime
import math


def validate_records(records: list[dict], product_codes: set[str]) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for row in records:
        trade_date = row.get("tradeDate", "")
        code = row.get("productCode", "")
        try:
            datetime.strptime(trade_date, "%Y%m%d")
        except (TypeError, ValueError):
            errors.append(f"invalid tradeDate: {trade_date}")
        if code not in product_codes:
            errors.append(f"unsupported productCode: {code}")
        price = row.get("closePrice")
        if not _finite_positive(price):
            errors.append(f"invalid closePrice: {code} {trade_date}")
        key = (trade_date, code)
        if key in seen:
            errors.append(f"duplicate record: {code} {trade_date}")
        seen.add(key)
    return errors


def _finite_positive(value) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def validate_index_records(records: list[dict], index_codes: set[str]) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for row in records:
        trade_date = row.get("tradeDate", "")
        code = row.get("indexCode", "")
        try:
            datetime.strptime(trade_date, "%Y%m%d")
        except (TypeError, ValueError):
            errors.append(f"invalid tradeDate: {trade_date}")
        if code not in index_codes:
            errors.append(f"unsupported indexCode: {code}")
        if not _finite_positive(row.get("closeValue")):
            errors.append(f"invalid closeValue: {code} {trade_date}")
        key = (trade_date, code)
        if key in seen:
            errors.append(f"duplicate index record: {code} {trade_date}")
        seen.add(key)
    return errors

