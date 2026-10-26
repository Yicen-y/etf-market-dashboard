from datetime import datetime


def validate_records(records: list[dict], product_codes: set[str]) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for row in records:
        trade_date = row.get("tradeDate", "")
        code = row.get("productCode", "")
        try:
            datetime.strptime(trade_date, "%Y%m%d")
        except ValueError:
            errors.append(f"invalid tradeDate: {trade_date}")
        if code not in product_codes:
            errors.append(f"unsupported productCode: {code}")
        price = row.get("closePrice")
        if price is None or price <= 0:
            errors.append(f"invalid closePrice: {code} {trade_date}")
        key = (trade_date, code)
        if key in seen:
            errors.append(f"duplicate record: {code} {trade_date}")
        seen.add(key)
    return errors

