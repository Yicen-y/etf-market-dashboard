"""Import saved Wind MCP daily K-line responses without publishing a snapshot.

The 14 strategy indices remain governed by scripts.config.INDEXES. This table
stores the separate Wind All A series and its exact response evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from .config import DATABASE_PATH

CODE = "881001.WI"
SCHEMA = """
CREATE TABLE IF NOT EXISTS wind_index_kline_batches (
    batch_id TEXT PRIMARY KEY,
    wind_code TEXT NOT NULL,
    provider TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    request_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL,
    raw_response BLOB NOT NULL,
    coverage_start TEXT NOT NULL,
    coverage_end TEXT NOT NULL,
    row_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS wind_index_daily_prices (
    wind_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open_value TEXT NOT NULL,
    close_value TEXT NOT NULL,
    high_value TEXT NOT NULL,
    low_value TEXT NOT NULL,
    turnover TEXT,
    volume TEXT,
    source_timestamp TEXT NOT NULL,
    batch_id TEXT NOT NULL REFERENCES wind_index_kline_batches(batch_id),
    PRIMARY KEY (wind_code, trade_date)
);
"""


def import_responses(db_path: Path, response_dir: Path) -> dict:
    paths = sorted(response_dir.glob("20??.json"))
    if len(paths) != 8 or [p.stem for p in paths] != [str(y) for y in range(2019, 2027)]:
        raise ValueError("Expected exactly one response file for each year 2019–2026")

    parsed = []
    seen_dates = set()
    for path in paths:
        raw = path.read_bytes()
        envelope = json.loads(raw.decode("utf-8-sig"))
        if envelope.get("isError") or envelope.get("ok") is False:
            raise ValueError(f"Wind response failed: {path.name}")
        meta = envelope["cli_meta"]
        if meta["server_type"] != "index_data" or meta["tool_name"] != "get_index_kline":
            raise ValueError(f"Wrong Wind tool: {path.name}")
        payload = json.loads(envelope["content"][0]["text"])
        if payload.get("error"):
            raise ValueError(f"Wind payload error: {path.name}")
        table = payload["data"]
        names = [col["name"] for col in table["columns"]]
        required = ("TIME", "OPEN", "MATCH", "HIGH", "LOW", "TURNOVER", "VOLUME")
        if any(name not in names for name in required):
            raise ValueError(f"Missing Wind fields: {path.name}")
        rows = []
        for source_row in table["rows"]:
            row = dict(zip(names, source_row))
            trade_date = date.fromisoformat(row["TIME"][:10])
            if trade_date.year != int(path.stem) or trade_date.weekday() >= 5:
                raise ValueError(f"Unexpected trading date: {trade_date}")
            key = trade_date.isoformat()
            if key in seen_dates:
                raise ValueError(f"Duplicate date: {key}")
            seen_dates.add(key)
            prices = [Decimal(row[name]) for name in ("OPEN", "MATCH", "HIGH", "LOW")]
            if any(value <= 0 for value in prices):
                raise ValueError(f"Nonpositive price: {key}")
            rows.append((CODE, key, *(row[name] for name in required[1:]), row["TIME"]))
        if not rows:
            raise ValueError(f"Empty Wind batch: {path.name}")
        end = f"{path.stem}-12-31" if path.stem != "2026" else "2026-11-17"
        request = {"windcode": CODE, "begin_date": f"{path.stem}-01-01", "end_date": end, "period": "1d"}
        sha = hashlib.sha256(raw).hexdigest()
        parsed.append((sha, request, datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(), raw, rows))

    inserted = 0
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(SCHEMA)
        for sha, request, fetched_at, raw, rows in parsed:
            batch_id = sha
            db.execute(
                "INSERT OR IGNORE INTO wind_index_kline_batches VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (batch_id, CODE, "Wind MCP", "index_data.get_index_kline", json.dumps(request, sort_keys=True),
                 fetched_at, sha, raw, rows[0][1], rows[-1][1], len(rows)),
            )
            for row in rows:
                existing = db.execute(
                    "SELECT open_value,close_value,high_value,low_value,turnover,volume "
                    "FROM wind_index_daily_prices WHERE wind_code=? AND trade_date=?", row[:2]
                ).fetchone()
                values = row[2:-1]
                if existing is not None:
                    if existing != values:
                        raise ValueError(f"Wind historical revision requires review: {row[1]}")
                    continue
                db.execute("INSERT INTO wind_index_daily_prices VALUES (?,?,?,?,?,?,?,?,?,?)", row + (batch_id,))
                inserted += 1
    return {"wind_code": CODE, "fetched_rows": len(seen_dates), "inserted_rows": inserted,
            "first_date": min(seen_dates), "last_date": max(seen_dates), "batches": len(parsed)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    args = parser.parse_args()
    print(json.dumps(import_responses(args.database, args.responses), ensure_ascii=False))


if __name__ == "__main__":
    main()
