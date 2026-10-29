import argparse
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import DATA_PATH, DATABASE_PATH, INDEX_DATA_PATH, INDEXES, INDEX_START_DATE, PRODUCT_START_DATES, PRODUCTS, START_DATE, STRATEGIES
from .fetch_data import current_end_date, fetch_csi_total_return_history, fetch_index_history, fetch_index_history_etfirst, fetch_product_history, fetch_product_history_etfirst
from .validate_data import validate_records
from .storage import read_index_records, read_records, upsert_index_records, upsert_records
from .prism_metrics import calculate_prism_metrics


def merge_records(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged = {(r["tradeDate"], r["productCode"]): r for r in existing}
    merged.update({(r["tradeDate"], r["productCode"]): r for r in incoming})
    return [merged[key] for key in sorted(merged)]


def records_to_calendar(records: list[dict]) -> list[dict]:
    dates: dict[str, dict] = {}
    for row in records:
        dates.setdefault(row["tradeDate"], {})[row["productCode"]] = row["closePrice"]
    return [{"tradeDate": d, "prices": prices} for d, prices in sorted(dates.items())]


def index_records_to_calendar(records: list[dict]) -> list[dict]:
    dates: dict[str, dict] = {}
    for row in records:
        dates.setdefault(row["tradeDate"], {})[row["indexCode"]] = row["closeValue"]
    return [{"tradeDate": d, "values": values} for d, values in sorted(dates.items())]


def merge_index_records(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged = {(r["tradeDate"], r["indexCode"]): r for r in existing}
    merged.update({(r["tradeDate"], r["indexCode"]): r for r in incoming})
    return [merged[key] for key in sorted(merged)]


def next_fetch_start(records: list[dict], code: str, fallback: str, key: str) -> str:
    latest = max((row["tradeDate"] for row in records if row.get(key) == code), default=None)
    if not latest:
        return fallback
    return (datetime.strptime(latest, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")


def should_fetch_range(fetch_start: str, end_date: str) -> bool:
    """Allow a one-day request when the next missing date is today."""
    return fetch_start <= end_date


def update_dataset(path: Path = DATA_PATH, api_key: Optional[str] = None, end_date: Optional[str] = None) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"records": []}
    incoming: list[dict] = []
    existing = read_records(DATABASE_PATH)
    for code in PRODUCTS:
        fetch_start = next_fetch_start(existing, code, PRODUCT_START_DATES.get(code, START_DATE), "productCode")
        fetch_end = end_date or current_end_date()
        try:
            incoming.extend(fetch_product_history_etfirst(code, fetch_start, fetch_end))
        except Exception as primary_error:
            try:
                incoming.extend(fetch_product_history(code, fetch_start, fetch_end, api_key))
            except Exception as fallback_error:
                raise RuntimeError(f"ETFirst and AkShare both failed for {code}. ETFirst: {primary_error}; AkShare: {fallback_error}") from fallback_error
    records = merge_records(existing or payload.get("flatRecords", []), incoming)
    errors = validate_records(records, set(PRODUCTS))
    if errors:
        raise ValueError("; ".join(errors))
    calendar = records_to_calendar(records)
    updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    upsert_records(DATABASE_PATH, records, updated_at)
    output = {
        "schemaVersion": 1,
        "source": "AkShare",
        "updatedAt": updated_at,
        "latestTradeDate": calendar[-1]["tradeDate"] if calendar else None,
        "products": PRODUCTS,
        "records": calendar,
        "flatRecords": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as temp:
        json.dump(output, temp, ensure_ascii=False, indent=2)
        temp.flush()
        temp_path = Path(temp.name)
    temp_path.replace(path)

    index_incoming: list[dict] = []
    index_end = end_date or current_end_date()
    existing_indexes = read_index_records(DATABASE_PATH)
    for code in INDEXES:
        fetch_start = next_fetch_start(existing_indexes, code, INDEX_START_DATE, "indexCode")
        if not should_fetch_range(fetch_start, index_end):
            continue
        try:
            index_incoming.extend(fetch_index_history_etfirst(code, fetch_start, index_end))
        except Exception as primary_error:
            try:
                if code.startswith("H") or code.endswith("CNY010"):
                    index_incoming.extend(fetch_csi_total_return_history(code, fetch_start, index_end, api_key))
                else:
                    index_incoming.extend(fetch_index_history(code, fetch_start, index_end, api_key))
            except Exception as fallback_error:
                raise RuntimeError(f"ETFirst and AkShare both failed for index {code}. ETFirst: {primary_error}; AkShare: {fallback_error}") from fallback_error
    index_records = merge_index_records(existing_indexes, index_incoming)
    if not index_records:
        raise ValueError("指数历史数据为空")
    upsert_index_records(DATABASE_PATH, index_records, updated_at)
    index_calendar = calculate_prism_metrics(index_records_to_calendar(index_records))
    index_output = {
        "schemaVersion": 1, "source": "ETFirst/AkShare", "updatedAt": updated_at,
        "latestTradeDate": index_calendar[-1]["tradeDate"], "indexes": INDEXES, "strategies": STRATEGIES,
        "records": index_calendar, "flatRecords": index_records,
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=INDEX_DATA_PATH.parent, delete=False, suffix=".tmp") as temp:
        json.dump(index_output, temp, ensure_ascii=False, indent=2)
        temp.flush()
        index_temp_path = Path(temp.name)
    index_temp_path.replace(INDEX_DATA_PATH)
    return {
        "etfCount": len(PRODUCTS),
        "indexCount": len(INDEXES),
        "strategyCount": len(STRATEGIES) + 2,
        "etfLatestTradeDate": output["latestTradeDate"],
        "indexLatestTradeDate": index_output["latestTradeDate"],
        "updatedAt": updated_at,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()
    update_dataset(api_key=args.api_key)

