"""Calendar verification and guarded incremental update for Wind All A (881001.WI)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DATABASE_PATH
from .import_wind_alla import CODE

SOURCE = "AkShare tool_trade_date_hist_sina (Sina trading calendar)"


def verify_calendar(db: sqlite3.Connection, calendar_dates: set[str], through: str) -> dict:
    """Mark dates verified only after exact equality with the independent calendar."""
    rows = db.execute(
        "SELECT trade_date FROM wind_index_daily_prices WHERE wind_code=? AND trade_date BETWEEN '2019-01-01' AND ? ORDER BY trade_date",
        (CODE, through),
    ).fetchall()
    actual = [row[0] for row in rows]
    expected = sorted(day for day in calendar_dates if "2019-01-01" <= day <= through)
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        return {"status": "FAIL", "actual_count": len(actual), "expected_count": len(expected),
                "missing_dates": sorted(set(expected) - set(actual)),
                "nontrading_dates": sorted(set(actual) - set(expected))}
    encoded = json.dumps(expected, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    checked_at = datetime.now(timezone.utc).isoformat()
    db.execute("""CREATE TABLE IF NOT EXISTS wind_index_calendar_checks (
        check_id TEXT PRIMARY KEY, wind_code TEXT NOT NULL, calendar_source TEXT NOT NULL,
        calendar_sha256 TEXT NOT NULL, calendar_dates_json TEXT NOT NULL,
        start_date TEXT NOT NULL, end_date TEXT NOT NULL, expected_count INTEGER NOT NULL,
        actual_count INTEGER NOT NULL, checked_at TEXT NOT NULL, status TEXT NOT NULL)""")
    columns = {row[1] for row in db.execute("PRAGMA table_info(wind_index_daily_prices)")}
    if "verification_status" not in columns:
        db.execute("ALTER TABLE wind_index_daily_prices ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED'")
    if "calendar_check_id" not in columns:
        db.execute("ALTER TABLE wind_index_daily_prices ADD COLUMN calendar_check_id TEXT")
    db.execute(
        "INSERT OR IGNORE INTO wind_index_calendar_checks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (digest, CODE, SOURCE, digest, encoded.decode(), "2019-01-01", through,
         len(expected), len(actual), checked_at, "PASS"),
    )
    db.execute(
        "UPDATE wind_index_daily_prices SET verification_status='PASS',calendar_check_id=? "
        "WHERE wind_code=? AND trade_date BETWEEN '2019-01-01' AND ? "
        "AND (verification_status!='PASS' OR calendar_check_id!=?)",
        (digest, CODE, through, digest),
    )
    return {"status": "PASS", "actual_count": len(actual), "expected_count": len(expected),
            "calendar_sha256": digest, "check_id": digest}


def _calendar_dates() -> set[str]:
    import akshare as ak

    dates = ak.tool_trade_date_hist_sina()["trade_date"]
    return {str(value)[:10] for value in dates}


def _fetch_wind(begin: str, end: str, skill_dir: Path) -> bytes:
    request = {"windcode": CODE, "begin_date": begin, "end_date": end, "period": "1d"}
    request_name = f"request-881001-{uuid.uuid4().hex}.json"
    request_path = skill_dir / "scripts" / request_name
    try:
        request_path.write_text(json.dumps(request), encoding="utf-8")
        result = subprocess.run(
            ["node", "scripts/cli.mjs", "call", "index_data", "get_index_kline", f"@scripts/{request_name}"],
            cwd=skill_dir, capture_output=True, check=True,
        )
        return result.stdout
    finally:
        request_path.unlink(missing_ok=True)


def incremental_update(db_path: Path, calendar_dates: set[str], through: str,
                       raw_response: bytes | None = None, skill_dir: Path | None = None) -> dict:
    with sqlite3.connect(db_path) as db:
        row = db.execute("SELECT MAX(trade_date) FROM wind_index_daily_prices WHERE wind_code=?", (CODE,)).fetchone()
        if not row or not row[0]:
            raise ValueError("Initial Wind All A history must be imported first")
        latest = row[0]
        if through <= latest:
            return {"status": "UNCHANGED", "latest_date": latest, "inserted_rows": 0}
        needed = sorted(day for day in calendar_dates if latest < day <= through)
        if not needed:
            return {"status": "UNCHANGED", "latest_date": latest, "inserted_rows": 0}
        begin = (date.fromisoformat(latest) - timedelta(days=14)).isoformat()
        if raw_response is None:
            if skill_dir is None:
                raise ValueError("Wind CLI skill directory required for live update")
            raw_response = _fetch_wind(begin, through, skill_dir)
        envelope = json.loads(raw_response.decode("utf-8-sig"))
        if envelope.get("isError") or envelope.get("ok") is False:
            raise ValueError(f"Wind MCP unavailable: {envelope.get('code', 'unknown')}")
        meta = envelope.get("cli_meta", {})
        if meta.get("server_type") != "index_data" or meta.get("tool_name") != "get_index_kline":
            raise ValueError("Unexpected Wind MCP response tool")
        payload = json.loads(envelope["content"][0]["text"])
        if payload.get("error"):
            raise ValueError(f"Wind MCP error: {payload['error']}")
        table = payload["data"]
        names = [column["name"] for column in table["columns"]]
        fields = ("TIME", "OPEN", "MATCH", "HIGH", "LOW", "TURNOVER", "VOLUME")
        if any(name not in names for name in fields):
            raise ValueError("Wind response missing required daily K-line fields")
        observations = {}
        for values in table["rows"]:
            item = dict(zip(names, values))
            day = item["TIME"][:10]
            if day < begin or day > through or day not in calendar_dates or day in observations:
                raise ValueError(f"Invalid or duplicate Wind trading date: {day}")
            if any(Decimal(item[field]) <= 0 for field in ("OPEN", "MATCH", "HIGH", "LOW")):
                raise ValueError(f"Invalid Wind price: {day}")
            observations[day] = item
        missing = set(needed) - observations.keys()
        if missing:
            raise ValueError(f"Missing Wind trading dates: {sorted(missing)}")
        for day, item in observations.items():
            existing = db.execute(
                "SELECT open_value,close_value,high_value,low_value,turnover,volume FROM wind_index_daily_prices "
                "WHERE wind_code=? AND trade_date=?", (CODE, day),
            ).fetchone()
            values = tuple(item[field] for field in fields[1:])
            if existing is not None and existing != values:
                raise ValueError(f"Wind historical revision requires review: {day}")
        sha = hashlib.sha256(raw_response).hexdigest()
        request = json.dumps({"windcode": CODE, "begin_date": begin, "end_date": through, "period": "1d"}, sort_keys=True)
        now = datetime.now(timezone.utc).isoformat()
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "INSERT OR IGNORE INTO wind_index_kline_batches VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (sha, CODE, "Wind MCP", "index_data.get_index_kline", request, now,
             sha, raw_response, min(observations), max(observations), len(observations)),
        )
        for day in needed:
            item = observations[day]
            db.execute(
                "INSERT INTO wind_index_daily_prices(wind_code,trade_date,open_value,close_value,high_value,low_value,turnover,volume,source_timestamp,batch_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (CODE, day, *(item[field] for field in fields[1:]), item["TIME"], sha),
            )
        result = verify_calendar(db, calendar_dates, through)
        if result["status"] != "PASS":
            raise ValueError(f"Calendar verification failed: {result}")
        return {"status": "PASS", "inserted_rows": len(needed), "latest_date": through,
                "calendar_sha256": result["calendar_sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("verify", "incremental"))
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    local_now = datetime.now(ZoneInfo("Asia/Shanghai"))
    completed_day = local_now.date() if local_now.hour >= 16 else local_now.date() - timedelta(days=1)
    parser.add_argument("--through", default=completed_day.isoformat())
    parser.add_argument("--wind-cli-dir", type=Path, default=Path.home() / ".agents/skills/wind-mcp-skill")
    args = parser.parse_args()
    calendar = _calendar_dates()
    if not any(day >= args.through for day in calendar):
        raise SystemExit("Trading calendar does not cover the requested through date")
    if args.mode == "verify":
        with sqlite3.connect(args.database) as db:
            result = verify_calendar(db, calendar, args.through)
    else:
        result = incremental_update(args.database, calendar, args.through, skill_dir=args.wind_cli_dir)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
