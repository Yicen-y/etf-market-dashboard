"""Bootstrap and incrementally refresh the temporary Nikkei anchor series."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from scripts.config import DATABASE_PATH, ROOT
from scripts.storage import read_nikkei_anchor_records, record_observations, save_raw_payload, upsert_nikkei_anchor_records
from scripts.wind_mcp_client import WindMcpClient
from scripts.wind_credentials import get_authorization

ENDPOINT = "https://mcp.wind.com.cn/vserver_index_data/mcp/"
REQUESTED_NAME = "日经225全收益指数"
SOURCE = "WIND_MCP_NAME_LOOKUP_UNVERIFIED_TR"
CSV_PATH = ROOT / "data" / "nikkei225_anchor.csv"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def bootstrap_csv(database: Path = DATABASE_PATH, csv_path: Path = CSV_PATH) -> dict:
    """One-time import of the already retrieved baseline, idempotently."""
    current = read_nikkei_anchor_records(database)
    if current or not csv_path.exists():
        return {"inserted": 0, "replaced": 0, "alreadyBootstrapped": bool(current)}
    with csv_path.open("r", encoding="utf-8", newline="") as stream:
        records = [{
            "tradeDate": row["date"].replace("-", ""), "open": float(row["open"]),
            "close": float(row["close"]), "high": float(row["high"]), "low": float(row["low"]),
        } for row in csv.DictReader(stream)]
    result = upsert_nikkei_anchor_records(database, records, _now(), SOURCE)
    batch_id = "nikkei-bootstrap-" + datetime.now().strftime("%Y%m%d%H%M%S")
    record_observations(database, [{
        "symbol": "NKY225_TEMP", "kind": "index", "trade_date": row["tradeDate"],
        "value_raw": str(row["close"]), "unit_raw": "index_point",
        "provider": "WIND_MCP", "upstream_publisher": "Nikkei name lookup; return type unverified",
        "provider_request_id": json.dumps({"tool": "get_index_kline", "windcode": REQUESTED_NAME, "period": "10"}, ensure_ascii=False),
        "source_url": ENDPOINT, "fetched_at": _now(), "fetch_batch_id": batch_id,
        "source_version": "temporary-baseline-v1",
    } for row in records])
    return {**result, "alreadyBootstrapped": False}


def _payload(result: dict) -> dict:
    for block in result.get("content", []):
        if block.get("type") == "text":
            value = json.loads(block.get("text", ""))
            if isinstance(value, dict):
                return value
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    raise ValueError("Wind MCP returned no parseable index response")


def _normalize(payload: dict) -> list[dict]:
    data = payload.get("data", {})
    columns = [column.get("name") for column in data.get("columns", [])]
    rows = data.get("rows", [])
    required = {"TIME", "OPEN", "MATCH", "HIGH", "LOW"}
    if not required.issubset(columns):
        raise ValueError("Wind response does not contain the expected daily OHLC fields")
    positions = {name: columns.index(name) for name in required}
    result, seen = [], set()
    for values in rows:
        stamp = str(values[positions["TIME"]])
        # The Chinese-name endpoint also returns stale carry-forward rows with
        # a synthetic +02:15 offset. Keep only Tokyo close timestamps (+09:00).
        if not stamp.endswith("+09:00"):
            continue
        day = stamp[:10].replace("-", "")
        record = {"tradeDate": day, "open": float(values[positions["OPEN"]]),
                  "close": float(values[positions["MATCH"]]), "high": float(values[positions["HIGH"]]),
                  "low": float(values[positions["LOW"]])}
        if len(day) != 8 or day in seen or any(value <= 0 for key, value in record.items() if key != "tradeDate"):
            raise ValueError("Wind returned an invalid or duplicate Nikkei daily observation")
        seen.add(day)
        result.append(record)
    return sorted(result, key=lambda row: row["tradeDate"])


def sync_nikkei_anchor(database: Path = DATABASE_PATH, *, authorization: str | None = None,
                       endpoint: str = ENDPOINT, end_date: str | None = None) -> dict:
    bootstrap = bootstrap_csv(database)
    existing = read_nikkei_anchor_records(database)
    if not existing:
        return {"status": "NO_BASELINE", "inserted": 0, "replaced": 0}
    auth = authorization or get_authorization()
    if not auth:
        return {"status": "SKIPPED_NO_CREDENTIAL", "inserted": 0, "replaced": 0,
                "bootstrap": bootstrap}
    latest = existing[-1]["tradeDate"]
    # Re-fetch a short overlap to accept late publication/corrections, while
    # leaving the older baseline untouched.
    start_date = (datetime.strptime(latest, "%Y%m%d") - timedelta(days=10)).strftime("%Y-%m-%d")
    finish = end_date or datetime.now().astimezone().date().isoformat()
    request = {"windcode": REQUESTED_NAME, "begin_date": start_date,
               "end_date": finish, "period": "10", "count": 0}
    with WindMcpClient(endpoint, auth) as client:
        client.initialize()
        response = client.call_tool("get_index_kline", request)
    raw = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    batch_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-nikkei"
    saved = save_raw_payload(ROOT / "data", batch_id, "nikkei225-incremental", raw)
    payload = _payload(response)
    records = _normalize(payload)
    if not records:
        return {"status": "NO_NEW_ROWS", "inserted": 0, "replaced": 0,
                "fromDate": start_date.replace("-", ""), "toDate": finish.replace("-", ""),
                "rawSha256": saved[1] if saved else None}
    result = upsert_nikkei_anchor_records(database, records, _now(), SOURCE)
    raw_records = [{
        "symbol": "NKY225_TEMP", "kind": "index", "trade_date": row["tradeDate"],
        "value_raw": str(row["close"]), "unit_raw": "index_point", "provider": "WIND_MCP",
        "upstream_publisher": "Nikkei name lookup; return type unverified",
        "provider_request_id": json.dumps(request, ensure_ascii=False, sort_keys=True),
        "source_url": endpoint, "fetched_at": _now(), "raw_sha256": saved[1] if saved else None,
        "fetch_batch_id": batch_id, "source_version": "temporary-name-lookup-v1",
    } for row in records]
    record_observations(database, raw_records)
    return {"status": "UPDATED", **result, "fromDate": records[0]["tradeDate"],
            "toDate": records[-1]["tradeDate"], "rawSha256": saved[1] if saved else None,
            "source": SOURCE, "bootstrap": bootstrap}


if __name__ == "__main__":
    print(json.dumps(sync_nikkei_anchor(), ensure_ascii=False, indent=2))
