"""Store the 17 requested CSI industry total-return series in separate SQLite tables."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
import uuid

from .config import DATABASE_PATH
from .fetch_data import fetch_exchange_trading_dates
from .index_verification import _fetch


INDICES = (
    ("H20596", "煤炭", "周期"), ("H00819", "有色金属", "周期"),
    ("H20229", "军工", "制造"), ("H20522", "新能源汽车", "成长"),
    ("H20539", "白酒", "消费"), ("H00807", "食品饮料", "消费"),
    ("H20451", "医疗", "医药"), ("H21152", "创新药", "医药"),
    ("H20180", "银行", "金融"), ("H20168", "证券", "金融"),
    ("H20595", "保险", "金融"), ("H20025", "地产", "地产"),
    ("H20184", "半导体", "科技"), ("H20651", "计算机", "科技"),
    ("H21071", "人工智能", "科技"), ("H21151", "光伏", "新能源"),
    ("H00941", "新能源", "新能源"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS industry_total_return_indices (
 index_code TEXT PRIMARY KEY, name TEXT NOT NULL, rotation_category TEXT NOT NULL,
 provider_symbol TEXT NOT NULL, return_type TEXT NOT NULL CHECK(return_type='total_return'),
 source_url TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS industry_total_return_batches (
 batch_id TEXT PRIMARY KEY, index_code TEXT NOT NULL, request_start TEXT NOT NULL,
 request_end TEXT NOT NULL, row_count INTEGER NOT NULL, raw_sha256 TEXT NOT NULL,
 raw_payload BLOB NOT NULL, fetched_at TEXT NOT NULL, source_url TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS industry_total_return_prices (
 trade_date TEXT NOT NULL, index_code TEXT NOT NULL, close_value REAL NOT NULL CHECK(close_value>0),
 source TEXT NOT NULL, batch_id TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(index_code,trade_date),
 FOREIGN KEY(index_code) REFERENCES industry_total_return_indices(index_code),
 FOREIGN KEY(batch_id) REFERENCES industry_total_return_batches(batch_id)
);
CREATE INDEX IF NOT EXISTS ix_industry_total_return_prices_date
 ON industry_total_return_prices(trade_date);
"""


def validate(result, code: str, calendar: set[str], start: str, end: str) -> list[tuple[str, float]]:
    if result.provider != "CSI official HTTP" or not result.raw_bytes or not result.raw_sha256:
        raise ValueError(f"{code}: official raw response missing")
    if not result.rows:
        raise ValueError(f"{code}: no observations")
    observations = []
    seen = set()
    for row in result.rows:
        day, value = row["tradeDate"], float(row["closeValue"])
        if row["indexCode"] != code or not start <= day <= end:
            raise ValueError(f"{code}: response identity or date mismatch")
        if "Total Return" not in str(row.get("indexNameEnAll") or ""):
            raise ValueError(f"{code}: provider did not identify a total-return series")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{code}: invalid close on {day}")
        if day not in calendar:
            if day == start:
                continue  # CSI can include a prior holiday placeholder at the range boundary.
            raise ValueError(f"{code}: unexpected non-trading date {day}")
        if day in seen:
            raise ValueError(f"{code}: duplicate trading day {day}")
        seen.add(day)
        observations.append((day, value))
    observations.sort()
    if not observations:
        raise ValueError(f"{code}: no exchange trading days")
    expected = {day for day in calendar if observations[0][0] <= day <= observations[-1][0]}
    missing = sorted(expected - seen)
    if missing:
        raise ValueError(f"{code}: {len(missing)} missing trading days, first {missing[0]}")
    return observations


def _existing_prices(database: Path) -> dict[str, dict[str, float]]:
    if not database.exists():
        return {}
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='industry_total_return_prices'").fetchone():
            return {}
        prices: dict[str, dict[str, float]] = {}
        for code, day, value in db.execute("SELECT index_code,trade_date,close_value FROM industry_total_return_prices"):
            prices.setdefault(code, {})[day] = value
        return prices


def sync(database: Path = DATABASE_PATH, *, start: str = "20190101", end: str,
         overlap_days: int = 7, full: bool = False,
         fetcher=_fetch, calendar_fetcher=fetch_exchange_trading_dates, dry_run=False) -> list[dict]:
    if overlap_days < 1:
        raise ValueError("overlap_days must be positive")
    datetime.strptime(start, "%Y%m%d")
    datetime.strptime(end, "%Y%m%d")
    if start > end:
        raise ValueError("start must not be after end")
    existing = _existing_prices(database)
    windows = {}
    for code, _, _ in INDICES:
        latest = max(existing.get(code, {}), default=None)
        windows[code] = max(start, (datetime.strptime(latest, "%Y%m%d") - timedelta(days=overlap_days)).strftime("%Y%m%d")) if latest and not full else start
    calendar = set(calendar_fetcher(min(windows.values()), end))
    if not calendar:
        raise ValueError("exchange trading calendar is unavailable")
    fetched = []
    summary = []
    for code, name, category in INDICES:
        request_start = windows[code]
        result = fetcher(code, request_start, end)
        rows = validate(result, code, calendar, request_start, end)
        previous = existing.get(code, {})
        added = sum(day not in previous for day, _ in rows)
        revised = sum(day in previous and previous[day] != value for day, value in rows)
        fetched.append((code, name, category, result, rows, request_start))
        summary.append({"code": code, "name": name, "count": len(rows),
                        "requestStart": request_start, "first": rows[0][0],
                        "last": rows[-1][0], "added": added, "revised": revised,
                        "rawSha256": result.raw_sha256})
    if dry_run:
        return summary
    now = datetime.now(timezone.utc).isoformat()
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(SCHEMA)
        with db:
            for code, name, category, result, rows, request_start in fetched:
                batch_id = uuid.uuid4().hex
                db.execute("""INSERT INTO industry_total_return_indices VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(index_code) DO UPDATE SET name=excluded.name,
                    rotation_category=excluded.rotation_category,provider_symbol=excluded.provider_symbol,
                    return_type=excluded.return_type,source_url=excluded.source_url,updated_at=excluded.updated_at""",
                    (code, name, category, f"{code}.CSI", "total_return", result.source_url, now))
                db.execute("INSERT INTO industry_total_return_batches VALUES(?,?,?,?,?,?,?,?,?)",
                    (batch_id, code, request_start, end, len(rows), result.raw_sha256,
                     result.raw_bytes, result.fetched_at, result.source_url))
                db.executemany("""INSERT INTO industry_total_return_prices VALUES(?,?,?,?,?,?)
                    ON CONFLICT(index_code,trade_date) DO UPDATE SET close_value=excluded.close_value,
                    source=excluded.source,batch_id=excluded.batch_id,updated_at=excluded.updated_at
                    WHERE industry_total_return_prices.close_value<>excluded.close_value""",
                    [(day, code, value, "CSI official HTTP", batch_id, now) for day, value in rows])
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    parser.add_argument("--start", default="20190101")
    parser.add_argument("--end", required=True)
    parser.add_argument("--overlap-days", type=int, default=7,
                        help="calendar days to re-fetch before each series' latest saved date")
    parser.add_argument("--full", action="store_true", help="re-fetch from --start")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(sync(args.database, start=args.start, end=args.end,
                          overlap_days=args.overlap_days, full=args.full,
                          dry_run=args.dry_run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
