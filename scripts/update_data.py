import argparse
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import DATA_PATH, PRODUCTS, START_DATE
from .fetch_data import current_end_date, fetch_product_history
from .validate_data import validate_records


def merge_records(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged = {(r["tradeDate"], r["productCode"]): r for r in existing}
    merged.update({(r["tradeDate"], r["productCode"]): r for r in incoming})
    return [merged[key] for key in sorted(merged)]


def records_to_calendar(records: list[dict]) -> list[dict]:
    dates: dict[str, dict] = {}
    for row in records:
        dates.setdefault(row["tradeDate"], {})[row["productCode"]] = row["closePrice"]
    return [{"tradeDate": d, "prices": prices} for d, prices in sorted(dates.items())]


def update_dataset(path: Path = DATA_PATH, api_key: Optional[str] = None, end_date: Optional[str] = None) -> None:
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"records": []}
    incoming: list[dict] = []
    for code in PRODUCTS:
        incoming.extend(fetch_product_history(code, START_DATE, end_date or current_end_date(), api_key))
    records = merge_records(payload.get("flatRecords", []), incoming)
    errors = validate_records(records, set(PRODUCTS))
    if errors:
        raise ValueError("; ".join(errors))
    calendar = records_to_calendar(records)
    output = {
        "schemaVersion": 1,
        "source": "南方基金 ETFirst",
        "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default=os.getenv("ETFIRST_API_KEY"))
    args = parser.parse_args()
    if not args.api_key:
        raise SystemExit("ETFIRST_API_KEY is required")
    update_dataset(api_key=args.api_key)

