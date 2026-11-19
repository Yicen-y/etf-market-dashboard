"""Collect and independently verify SW2021 level-one index history.

Wind snapshots are supplied by Codex after a real MCP call. This module never
pretends that the deployed FastAPI process has access to the Codex MCP session.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
import uuid
from zoneinfo import ZoneInfo

from .config import DATABASE_PATH
from .storage import init_reliability_schema, record_observations, record_quality_issues, save_raw_payload


INDUSTRIES = {
    "801010": "农林牧渔", "801030": "基础化工", "801040": "钢铁", "801050": "有色金属",
    "801080": "电子", "801110": "家用电器", "801120": "食品饮料", "801130": "纺织服饰",
    "801140": "轻工制造", "801150": "医药生物", "801160": "公用事业", "801170": "交通运输",
    "801180": "房地产", "801200": "商贸零售", "801210": "社会服务", "801230": "综合",
    "801710": "建筑材料", "801720": "建筑装饰", "801730": "电力设备", "801740": "国防军工",
    "801750": "计算机", "801760": "传媒", "801770": "通信", "801780": "银行",
    "801790": "非银金融", "801880": "汽车", "801890": "机械设备", "801950": "煤炭",
    "801960": "石油石化", "801970": "环保", "801980": "美容护理",
}
START = date(2019, 1, 1)
SW2021_INDEX_LAUNCH = "2021-12-13"
NEW_SW2021_CODES = frozenset({"801960", "801970", "801980"})
AK_COLUMNS = {"代码": "index_code", "日期": "trade_date", "开盘": "open", "最高": "high",
              "最低": "low", "收盘": "close", "成交量": "volume", "成交额": "amount"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS sw2021_indices (
 index_code TEXT PRIMARY KEY, name TEXT NOT NULL, classification_version TEXT NOT NULL,
 index_family TEXT NOT NULL, return_basis TEXT NOT NULL, raw_return_basis TEXT NOT NULL,
 akshare_code TEXT NOT NULL, wind_code TEXT, enabled INTEGER NOT NULL,
 backfill_before TEXT NOT NULL, backfill_note TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sw2021_source_fields (
 source TEXT NOT NULL, raw_field TEXT NOT NULL, stored_field TEXT NOT NULL,
 raw_unit TEXT NOT NULL, transform TEXT NOT NULL, evidence TEXT NOT NULL,
 PRIMARY KEY(source,raw_field)
);
CREATE TABLE IF NOT EXISTS sw2021_fetch_batches (
 batch_id TEXT PRIMARY KEY, index_code TEXT NOT NULL, requested_start TEXT NOT NULL,
 requested_end TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
 status TEXT NOT NULL, error TEXT, raw_path TEXT, raw_sha256 TEXT,
 source_latest_date TEXT, akshare_version TEXT
);
CREATE TABLE IF NOT EXISTS sw2021_daily (
 index_code TEXT NOT NULL, trade_date TEXT NOT NULL, open REAL NOT NULL,
 high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
 volume REAL, amount REAL, source TEXT NOT NULL, fetched_at TEXT NOT NULL,
 batch_id TEXT NOT NULL, quality_status TEXT NOT NULL, raw_record_id INTEGER,
 raw_ordinal INTEGER NOT NULL, PRIMARY KEY(index_code,trade_date)
);
CREATE TABLE IF NOT EXISTS sw2021_daily_revisions (
 revision_id INTEGER PRIMARY KEY, index_code TEXT NOT NULL, trade_date TEXT NOT NULL,
 old_json TEXT NOT NULL, new_json TEXT NOT NULL, detected_at TEXT NOT NULL,
 batch_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sw2021_trade_calendar (trade_date TEXT PRIMARY KEY, source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sw2021_wind_batches (
 batch_id TEXT PRIMARY KEY, index_code TEXT NOT NULL, wind_code TEXT NOT NULL,
 requested_start TEXT NOT NULL, requested_end TEXT NOT NULL, fetched_at TEXT NOT NULL,
 status TEXT NOT NULL, error TEXT, raw_path TEXT, raw_sha256 TEXT,
 row_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sw2021_wind_daily (
 index_code TEXT NOT NULL, trade_date TEXT NOT NULL, close REAL NOT NULL,
 batch_id TEXT NOT NULL, fetched_at TEXT NOT NULL,
 PRIMARY KEY(index_code,trade_date)
);
CREATE TABLE IF NOT EXISTS sw2021_wind_revisions (
 revision_id INTEGER PRIMARY KEY, index_code TEXT NOT NULL, trade_date TEXT NOT NULL,
 old_close REAL NOT NULL, new_close REAL NOT NULL, old_batch_id TEXT NOT NULL,
 new_batch_id TEXT NOT NULL, detected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sw2021_verification (
 index_code TEXT NOT NULL, trade_date TEXT NOT NULL, ak_close REAL,
 wind_close REAL, absolute_error REAL, relative_error REAL,
 status TEXT NOT NULL, reason TEXT NOT NULL, ak_batch_id TEXT,
 wind_batch_id TEXT, checked_at TEXT NOT NULL,
 PRIMARY KEY(index_code,trade_date)
);
CREATE VIEW IF NOT EXISTS sw2021_approved_daily AS
 SELECT d.* FROM sw2021_daily d JOIN sw2021_verification v
 ON d.index_code=v.index_code AND d.trade_date=v.trade_date
 WHERE d.quality_status='QC_PASSED' AND v.status='VERIFIED'
 AND v.ak_batch_id=d.batch_id;
CREATE INDEX IF NOT EXISTS ix_sw2021_verify_status ON sw2021_verification(index_code,status);
"""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def completed_day() -> date:
    local = datetime.now(ZoneInfo("Asia/Shanghai"))
    return local.date() if local.hour >= 17 else local.date() - timedelta(days=1)


def connect(path: Path = DATABASE_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def migrate(path: Path = DATABASE_PATH) -> None:
    init_reliability_schema(path)
    with connect(path) as db:
        db.executescript(SCHEMA)
        db.executemany("""INSERT INTO sw2021_indices VALUES (?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(index_code) DO UPDATE SET name=excluded.name,
          classification_version=excluded.classification_version,
          index_family=excluded.index_family,return_basis=excluded.return_basis,
          raw_return_basis=excluded.raw_return_basis,akshare_code=excluded.akshare_code,
          enabled=excluded.enabled,backfill_before=excluded.backfill_before,
          backfill_note=excluded.backfill_note""",
          [(code, name, "SW2021", "申万一级行业指数", "ORDINARY_INDEX_UNCONFIRMED",
            "AKShare index_hist_sw 原始指数点位；非独立全收益，不额外复权",
            code, None, 1, SW2021_INDEX_LAUNCH,
            "切换日前的历史序列可能采用旧分类或回溯计算；需逐行业确认，不能作为SW2021当时实时信号")
           for code, name in INDUSTRIES.items()])
        db.executemany("""INSERT INTO sw2021_source_fields VALUES (?,?,?,?,?,?)
          ON CONFLICT(source,raw_field) DO UPDATE SET raw_unit=excluded.raw_unit,
          transform=excluded.transform,evidence=excluded.evidence""", [
            ("AKShare:index_hist_sw", "收盘", "close", "index points", "as returned", "AKShare column label"),
            ("AKShare:index_hist_sw", "开盘", "open", "index points", "as returned", "AKShare column label"),
            ("AKShare:index_hist_sw", "最高", "high", "index points", "as returned", "AKShare column label"),
            ("AKShare:index_hist_sw", "最低", "low", "index points", "as returned", "AKShare column label"),
            ("AKShare:index_hist_sw", "成交量", "volume", "reported value; 亿股 inferred", "as returned", "2019-01-02 801050 cross-source ratio ≈1e8; publisher unit unconfirmed"),
            ("AKShare:index_hist_sw", "成交额", "amount", "reported value; 亿元 inferred", "as returned", "2019-01-02 801050 cross-source ratio ≈1e8; publisher unit unconfirmed"),
            ("Wind MCP:get_index_kline", "MATCH", "close", "index points", "as returned", "801050 2019-01-02 and 2026-11-09 same-day AKShare close match"),
        ])


def parse_akshare(frame, code: str, start: date, end: date) -> list[dict]:
    missing = set(AK_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"AKShare fields missing: {sorted(missing)}")
    rows = []
    seen = set()
    for ordinal, source in enumerate(frame.to_dict("records")):
        if str(source["代码"]) != code:
            raise ValueError(f"AKShare code mismatch: {source['代码']} != {code}")
        day = date.fromisoformat(str(source["日期"])[:10])
        if not start <= day <= end:
            continue
        if day.isoformat() in seen:
            raise ValueError(f"AKShare duplicate date: {code} {day}")
        seen.add(day.isoformat())
        row = {"index_code": code, "trade_date": day.isoformat(), "raw_ordinal": ordinal}
        for source_key, field in AK_COLUMNS.items():
            if field in ("index_code", "trade_date"):
                continue
            value = source[source_key]
            row[field] = None if value is None or str(value).lower() in ("nan", "none", "nat", "") else float(value)
        rows.append(row)
    rows.sort(key=lambda x: x["trade_date"])
    return rows


def qc_status(row: dict, previous_close: float | None = None) -> tuple[str, str]:
    prices = [row.get(k) for k in ("open", "high", "low", "close")]
    if any(x is None or not math.isfinite(x) or x <= 0 for x in prices):
        return "FAILED", "INVALID_PRICE"
    opening, high, low, close = prices
    if low > high or min(opening, close) < low - 0.011 or max(opening, close) > high + 0.011:
        return "FAILED", "OHLC_INCONSISTENT"
    if any(x is not None and (not math.isfinite(x) or x < 0) for x in (row.get("volume"), row.get("amount"))):
        return "FAILED", "INVALID_TURNOVER"
    if previous_close and abs(close / previous_close - 1) > 0.3:
        return "REVIEW", "LARGE_DAILY_JUMP"
    return "QC_PASSED", ""


def load_calendar(path: Path = DATABASE_PATH, provider=None) -> int:
    migrate(path)
    if provider is None:
        import akshare as provider
    dates = provider.tool_trade_date_hist_sina()["trade_date"]
    days = [(str(value)[:10], "AKShare tool_trade_date_hist_sina") for value in dates
            if START.isoformat() <= str(value)[:10] <= completed_day().isoformat()]
    with connect(path) as db:
        db.executemany("INSERT OR IGNORE INTO sw2021_trade_calendar VALUES (?,?)", days)
    return len(days)


def fetch_akshare(code: str, provider=None, *, attempts: int = 3, delay: float = 0.7):
    if provider is None:
        import akshare as provider
    error = None
    for attempt in range(attempts):
        try:
            frame = provider.index_hist_sw(symbol=code, period="day")
            if frame is None or frame.empty:
                raise ValueError(f"AKShare empty response for {code}")
            return frame
        except Exception as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(delay * 2 ** attempt)
    raise RuntimeError(f"AKShare failed after {attempts} attempts: {error}") from error


def collect_code(code: str, path: Path = DATABASE_PATH, *, start: date = START,
                 end: date | None = None, provider=None, attempts: int = 3) -> dict:
    if code not in INDUSTRIES:
        raise ValueError(f"Unknown SW2021 code: {code}")
    end = min(end or completed_day(), completed_day())
    if start > end:
        raise ValueError("start must be on or before the last completed day")
    migrate(path)
    batch = "sw-ak-" + uuid.uuid4().hex
    started = now_utc()
    with connect(path) as db:
        db.execute("INSERT INTO sw2021_fetch_batches(batch_id,index_code,requested_start,requested_end,started_at,status) VALUES (?,?,?,?,?,'RUNNING')",
                   (batch, code, start.isoformat(), end.isoformat(), started))
    try:
        frame = fetch_akshare(code, provider, attempts=attempts)
        rows = parse_akshare(frame, code, start, end)
        if not rows:
            raise ValueError(f"AKShare has no rows in requested range for {code}")
        raw = frame.to_json(orient="records", date_format="iso", force_ascii=False).encode("utf-8")
        raw_path, digest = save_raw_payload(path.parent, batch, f"sw2021-{code}", raw)
        import akshare as ak
        version = getattr(provider or ak, "__version__", "unknown")
        inserted = revised = failed = review = 0
        previous = None
        with connect(path) as db:
            prior = db.execute("SELECT close FROM sw2021_daily WHERE index_code=? AND trade_date<? ORDER BY trade_date DESC LIMIT 1",
                               (code, rows[0]["trade_date"])).fetchone()
            previous = prior[0] if prior else None
            for row in rows:
                status, reason = qc_status(row, previous)
                previous = row["close"] if row["close"] and math.isfinite(row["close"]) else previous
                failed += status == "FAILED"
                review += status == "REVIEW"
                old = db.execute("SELECT * FROM sw2021_daily WHERE index_code=? AND trade_date=?",
                                 (code, row["trade_date"])).fetchone()
                fields = ("open", "high", "low", "close", "volume", "amount")
                if status == "FAILED":
                    record_observations(path, [{"symbol": code, "kind": "sw2021_index",
                        "trade_date": row["trade_date"], "value_raw": str(row["close"]),
                        "unit_raw": "index_points", "provider": "AKShare",
                        "upstream_publisher": "SWS Research", "provider_request_id": batch,
                        "source_url": "https://www.swsresearch.com/institute-sw/api/index_publish/trend/",
                        "fetched_at": started, "raw_sha256": digest,
                        "parser_version": "sw2021-v1", "fetch_batch_id": batch,
                        "source_publish_at": None, "source_version": "unknown"}], db)
                    bad_raw_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                    record_quality_issues(path, [{"symbol": code, "kind": "sw2021_index",
                        "trade_date": row["trade_date"], "issue_code": reason,
                        "severity": "BLOCKED", "batch_id": batch,
                        "raw_record_id": bad_raw_id}], db)
                    if old:
                        db.execute("UPDATE sw2021_daily SET quality_status='FAILED' WHERE index_code=? AND trade_date=?",
                                   (code, row["trade_date"]))
                        db.execute("UPDATE sw2021_verification SET status='STALE',reason=? WHERE index_code=? AND trade_date=?",
                                   (f"AKShare QC failure: {reason}", code, row["trade_date"]))
                    continue
                if status == "REVIEW":
                    record_quality_issues(path, [{"symbol": code, "kind": "sw2021_index",
                        "trade_date": row["trade_date"], "issue_code": reason,
                        "severity": "REVIEW", "batch_id": batch}], db)
                elif status == "QC_PASSED":
                    db.execute("""UPDATE quality_issues SET resolution_status='resolved',
                      resolution_evidence_id=? WHERE symbol=? AND kind='sw2021_index'
                      AND trade_date=? AND issue_code IN ('INVALID_PRICE','OHLC_INCONSISTENT','INVALID_TURNOVER')
                      AND resolution_status='open'""", (batch, code, row["trade_date"]))
                if old and all(old[field] == row[field] for field in fields) and old["quality_status"] == status:
                    continue
                record_observations(path, [{"symbol": code, "kind": "sw2021_index",
                    "trade_date": row["trade_date"], "value_raw": str(row["close"]),
                    "unit_raw": "index_points", "provider": "AKShare",
                    "upstream_publisher": "SWS Research", "provider_request_id": batch,
                    "source_url": "https://www.swsresearch.com/institute-sw/api/index_publish/trend/",
                    "fetched_at": started, "raw_sha256": digest,
                    "parser_version": "sw2021-v1", "fetch_batch_id": batch,
                    "source_publish_at": None, "source_version": "unknown"}], db)
                raw_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                if old:
                    old_values = {key: old[key] for key in fields}
                    new_values = {key: row[key] for key in fields}
                    db.execute("INSERT INTO sw2021_daily_revisions(index_code,trade_date,old_json,new_json,detected_at,batch_id) VALUES (?,?,?,?,?,?)",
                               (code, row["trade_date"], json.dumps(old_values), json.dumps(new_values), started, batch))
                    db.execute("UPDATE sw2021_verification SET status='STALE',reason='AKShare source revision requires re-verification' WHERE index_code=? AND trade_date=?",
                               (code, row["trade_date"]))
                    revised += 1
                else:
                    inserted += 1
                db.execute("""INSERT INTO sw2021_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(index_code,trade_date) DO UPDATE SET
                  open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,
                  volume=excluded.volume,amount=excluded.amount,source=excluded.source,
                  fetched_at=excluded.fetched_at,batch_id=excluded.batch_id,
                  quality_status=excluded.quality_status,raw_record_id=excluded.raw_record_id,
                  raw_ordinal=excluded.raw_ordinal""",
                  (code, row["trade_date"], row["open"], row["high"], row["low"], row["close"],
                   row["volume"], row["amount"], "AKShare:index_hist_sw:SWS", started,
                   batch, status, raw_id, row["raw_ordinal"]))
            db.execute("""UPDATE sw2021_fetch_batches SET finished_at=?,status=?,
              raw_path=?,raw_sha256=?,source_latest_date=?,akshare_version=? WHERE batch_id=?""",
              (now_utc(), "PARTIAL" if failed else "COMPLETED", str(raw_path), digest,
               rows[-1]["trade_date"], version, batch))
        return {"code": code, "name": INDUSTRIES[code], "batch_id": batch,
                "start": rows[0]["trade_date"], "end": rows[-1]["trade_date"],
                "returned": len(rows), "inserted": inserted, "revised": revised,
                "qc_failed": failed, "qc_review": review,
                "status": "PARTIAL" if failed else "COMPLETED"}
    except Exception as exc:
        with connect(path) as db:
            db.execute("UPDATE sw2021_fetch_batches SET finished_at=?,status='FAILED',error=? WHERE batch_id=?",
                       (now_utc(), f"{type(exc).__name__}: {exc}", batch))
        raise


def collect_many(codes: list[str], path: Path = DATABASE_PATH, *, start: date = START,
                 end: date | None = None, provider=None, rate_delay: float = 0.6) -> list[dict]:
    results = []
    for index, code in enumerate(codes):
        if index and rate_delay:
            time.sleep(rate_delay)
        try:
            results.append(collect_code(code, path, start=start, end=end, provider=provider))
        except Exception as exc:
            results.append({"code": code, "name": INDUSTRIES.get(code), "status": "FAILED",
                            "error": f"{type(exc).__name__}: {exc}"})
    return results


def incremental_start(path: Path, code: str, overlap_days: int = 30) -> date:
    with connect(path) as db:
        row = db.execute("SELECT MAX(trade_date) FROM sw2021_daily WHERE index_code=?", (code,)).fetchone()
    return max(START, date.fromisoformat(row[0]) - timedelta(days=overlap_days)) if row and row[0] else START


def parse_wind_snapshot(raw: bytes, code: str, start: date, end: date) -> list[tuple[str, float]]:
    """Accept the actual Codex Wind MCP/CLI envelope; MATCH is its close field."""
    envelope = json.loads(raw)
    if envelope.get("ok") is False or envelope.get("isError"):
        raise ValueError(f"Wind MCP error: {envelope.get('code')} {envelope.get('message')}")
    if "content" in envelope:
        payload = json.loads(envelope["content"][0]["text"])
    else:
        payload = envelope
    if payload.get("error"):
        raise ValueError(f"Wind response error: {payload['error']}")
    data = payload.get("data") or {}
    if isinstance(data.get("data"), list):
        data = data["data"][0]
    columns = [column["name"] for column in data.get("columns", [])]
    if "TIME" not in columns or "MATCH" not in columns:
        raise ValueError(f"Wind TIME/MATCH fields missing: {columns}")
    time_at, close_at = columns.index("TIME"), columns.index("MATCH")
    result = []
    seen = set()
    for record in data.get("rows", []):
        day = str(record[time_at])[:10]
        if not start.isoformat() <= day <= end.isoformat():
            raise ValueError(f"Wind out-of-range date: {day}")
        if day in seen:
            raise ValueError(f"Wind duplicate date: {day}")
        seen.add(day)
        value = float(record[close_at])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Wind invalid close: {day} {value}")
        result.append((day, value))
    if not result:
        raise ValueError(f"Wind empty history for {code}")
    result.sort()
    return result


def import_wind(code: str, wind_code: str, file: Path, path: Path = DATABASE_PATH,
                *, start: date = START, end: date | None = None) -> dict:
    if code not in INDUSTRIES:
        raise ValueError(f"Unknown SW2021 code: {code}")
    if wind_code != code + ".SI":
        raise ValueError("Wind code does not match the confirmed SW2021 index mapping")
    end = end or completed_day()
    migrate(path)
    raw = file.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    batch = "sw-wind-" + hashlib.sha256(f"{code}:{start}:{end}:{digest}".encode()).hexdigest()[:24]
    fetched = now_utc()
    target = path.parent / "verification" / "sw2021" / "wind" / f"{batch}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(raw)
    try:
        rows = parse_wind_snapshot(raw, code, start, end)
    except Exception as exc:
        with connect(path) as db:
            db.execute("""INSERT INTO sw2021_wind_batches
              (batch_id,index_code,wind_code,requested_start,requested_end,fetched_at,status,error,raw_path,raw_sha256,row_count)
              VALUES (?,?,?,?,?,?,'FAILED',?,?,?,0)
              ON CONFLICT(batch_id) DO UPDATE SET status='FAILED',error=excluded.error""",
              (batch, code, wind_code, start.isoformat(), end.isoformat(), fetched,
               f"{type(exc).__name__}: {exc}", str(target), digest))
        raise
    with connect(path) as db:
        existing = db.execute("SELECT wind_code FROM sw2021_indices WHERE index_code=?", (code,)).fetchone()
        if existing[0] and existing[0] != wind_code:
            raise ValueError(f"Wind identity changed: {existing[0]} -> {wind_code}")
        db.execute("UPDATE sw2021_indices SET wind_code=? WHERE index_code=?", (wind_code, code))
        db.execute("""INSERT INTO sw2021_wind_batches
          (batch_id,index_code,wind_code,requested_start,requested_end,fetched_at,status,raw_path,raw_sha256,row_count)
          VALUES (?,?,?,?,?,?,'COMPLETED',?,?,?)
          ON CONFLICT(batch_id) DO UPDATE SET status='COMPLETED',error=NULL,row_count=excluded.row_count""",
          (batch, code, wind_code, start.isoformat(), end.isoformat(), fetched, str(target), digest, len(rows)))
        for day, close in rows:
            old = db.execute("SELECT close,batch_id FROM sw2021_wind_daily WHERE index_code=? AND trade_date=?",
                             (code, day)).fetchone()
            if old and old["close"] == close:
                continue
            if old:
                db.execute("""INSERT INTO sw2021_wind_revisions
                  (index_code,trade_date,old_close,new_close,old_batch_id,new_batch_id,detected_at)
                  VALUES (?,?,?,?,?,?,?)""",
                  (code, day, old["close"], close, old["batch_id"], batch, fetched))
                db.execute("UPDATE sw2021_verification SET status='STALE',reason='Wind source revision requires re-verification' WHERE index_code=? AND trade_date=?",
                           (code, day))
            db.execute("""INSERT INTO sw2021_wind_daily VALUES (?,?,?,?,?)
              ON CONFLICT(index_code,trade_date) DO UPDATE SET close=excluded.close,
              batch_id=excluded.batch_id,fetched_at=excluded.fetched_at""",
              (code, day, close, batch, fetched))
    return {"code": code, "wind_code": wind_code, "batch_id": batch,
            "start": rows[0][0], "end": rows[-1][0], "rows": len(rows)}


def verify_code(code: str, path: Path = DATABASE_PATH, *, threshold: Decimal = Decimal("0.0001")) -> dict:
    migrate(path)
    checked = now_utc()
    counts: dict[str, int] = {}
    with connect(path) as db:
        ak = {row["trade_date"]: row for row in db.execute("SELECT * FROM sw2021_daily WHERE index_code=?", (code,))}
        wind = {row["trade_date"]: row for row in db.execute("SELECT * FROM sw2021_wind_daily WHERE index_code=?", (code,))}
        if not wind:
            return {"code": code, "status": "WIND_UNAVAILABLE", "ak_rows": len(ak), "wind_rows": 0}
        for day in sorted(set(ak) | set(wind)):
            local, reference = ak.get(day), wind.get(day)
            absolute = relative = None
            if local is None:
                if code in NEW_SW2021_CODES and day < SW2021_INDEX_LAUNCH:
                    status, reason = "HISTORICAL_BACKFILL_ONLY", "Wind has pre-launch history; AKShare series begins at 2021-12-13"
                else:
                    status, reason = "AK_MISSING", "Wind has a date absent from AKShare"
            elif reference is None:
                status, reason = "WIND_MISSING", "AKShare has a date absent from Wind snapshot"
            elif local["quality_status"] != "QC_PASSED":
                status, reason = "QC_BLOCKED", f"AKShare local QC: {local['quality_status']}"
            else:
                absolute = abs(Decimal(str(local["close"])) - Decimal(str(reference["close"])))
                relative = absolute / abs(Decimal(str(reference["close"])))
                status = "VERIFIED" if relative <= threshold else "CONFLICT"
                reason = "MATCH close within relative tolerance" if status == "VERIFIED" else "Close exceeds relative tolerance; inspect identity, history revision and precision"
            counts[status] = counts.get(status, 0) + 1
            db.execute("""INSERT INTO sw2021_verification VALUES (?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(index_code,trade_date) DO UPDATE SET ak_close=excluded.ak_close,
              wind_close=excluded.wind_close,absolute_error=excluded.absolute_error,
              relative_error=excluded.relative_error,status=excluded.status,
              reason=excluded.reason,ak_batch_id=excluded.ak_batch_id,
              wind_batch_id=excluded.wind_batch_id,checked_at=excluded.checked_at""",
              (code, day, local["close"] if local else None, reference["close"] if reference else None,
               float(absolute) if absolute is not None else None,
               float(relative) if relative is not None else None, status, reason,
               local["batch_id"] if local else None, reference["batch_id"] if reference else None, checked))
    return {"code": code, "ak_rows": len(ak), "wind_rows": len(wind),
            "common_rows": len(set(ak) & set(wind)), "status_counts": counts}


def build_report(path: Path = DATABASE_PATH, *, start: date = START,
                 end: date | None = None) -> dict:
    migrate(path)
    end = min(end or completed_day(), completed_day())
    with connect(path) as db:
        calendar = [row[0] for row in db.execute("SELECT trade_date FROM sw2021_trade_calendar WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
                                                  (start.isoformat(), end.isoformat()))]
        if not calendar:
            raise ValueError("A-share trade calendar is empty; run calendar collection first")
        industries = []
        anomalies = []
        for code, name in INDUSTRIES.items():
            daily = {row["trade_date"]: row for row in db.execute("SELECT * FROM sw2021_daily WHERE index_code=? AND trade_date BETWEEN ? AND ?",
                                                              (code, start.isoformat(), end.isoformat()))}
            wind = {row["trade_date"]: row for row in db.execute("SELECT * FROM sw2021_wind_daily WHERE index_code=? AND trade_date BETWEEN ? AND ?",
                                                             (code, start.isoformat(), end.isoformat()))}
            verified = {row["trade_date"]: row for row in db.execute("SELECT * FROM sw2021_verification WHERE index_code=? AND trade_date BETWEEN ? AND ?",
                                                                 (code, start.isoformat(), end.isoformat()))}
            missing = [day for day in calendar if day not in daily]
            longest = streak = 0
            missing_set = set(missing)
            for day in calendar:
                streak = streak + 1 if day in missing_set else 0
                longest = max(longest, streak)
            common = set(daily) & set(wind)
            differences = [v for day, v in verified.items() if day in common and v["relative_error"] is not None]
            conflicts = sum(v["status"] == "CONFLICT" for v in verified.values())
            passed = sum(v["status"] == "VERIFIED" for v in verified.values())
            qc_failed = sum(v["quality_status"] == "FAILED" for v in daily.values())
            qc_review = sum(v["quality_status"] == "REVIEW" for v in daily.values())
            failed_fetch = db.execute("SELECT error FROM sw2021_fetch_batches WHERE index_code=? AND status='FAILED' ORDER BY started_at DESC LIMIT 1", (code,)).fetchone()
            status = ("FAILED" if not daily else "CONFLICT" if conflicts else
                      "PARTIAL" if missing or qc_failed or qc_review or passed != len(daily) else "VERIFIED")
            fetch_status = "FAILED" if not daily else "PARTIAL" if missing else "FETCHED"
            item = {"code": code, "name": name, "start": min(daily) if daily else None,
                    "end": max(daily) if daily else None, "ak_rows": len(daily),
                    "wind_rows": len(wind), "common_rows": len(common), "verified_rows": passed,
                    "missing_trading_days": len(missing), "max_consecutive_missing": longest,
                    "prelaunch_backfill_only": sum(code in NEW_SW2021_CODES and day < SW2021_INDEX_LAUNCH for day in missing),
                    "calendar_coverage": round(len(set(daily) & set(calendar)) / len(calendar), 6),
                    "wind_coverage": round(len(common) / len(daily), 6) if daily else 0,
                    "verified_coverage": round(passed / len(daily), 6) if daily else 0,
                    "max_absolute_error": max((v["absolute_error"] for v in differences), default=None),
                    "max_relative_error": max((v["relative_error"] for v in differences), default=None),
                    "mean_relative_error": (sum(v["relative_error"] for v in differences) / len(differences)) if differences else None,
                    "conflicts": conflicts, "qc_failed": qc_failed, "qc_review": qc_review,
                    "fetch_status": fetch_status, "verification_status": status if wind else "WIND_UNAVAILABLE",
                    "last_fetch_error": failed_fetch[0] if failed_fetch else None,
                    "historical_backfill_before": SW2021_INDEX_LAUNCH}
            industries.append(item)
            for day in missing:
                prelaunch = code in NEW_SW2021_CODES and day < SW2021_INDEX_LAUNCH
                anomalies.append({"code": code, "trade_date": day,
                                  "type": "HISTORICAL_BACKFILL_ONLY" if prelaunch else "AK_MISSING",
                                  "ak_close": None, "wind_close": wind[day]["close"] if day in wind else None,
                                  "absolute_error": None, "relative_error": None,
                                  "reason": "Wind pre-launch backfill; AKShare series begins 2021-12-13" if prelaunch else "A-share trading day absent from AKShare history",
                                  "resolved": False, "allow_business_use": False})
            for day, row in verified.items():
                if row["status"] == "VERIFIED" or day in missing_set:
                    continue
                anomalies.append({"code": code, "trade_date": day, "type": row["status"],
                                  "ak_close": row["ak_close"], "wind_close": row["wind_close"],
                                  "absolute_error": row["absolute_error"], "relative_error": row["relative_error"],
                                  "reason": row["reason"], "resolved": False, "allow_business_use": False})
            for day, row in daily.items():
                if row["quality_status"] != "QC_PASSED" and day not in verified:
                    anomalies.append({"code": code, "trade_date": day, "type": row["quality_status"],
                                      "ak_close": row["close"], "wind_close": None,
                                      "absolute_error": None, "relative_error": None,
                                      "reason": "Local OHLC/turnover QC or large-jump review",
                                      "resolved": False, "allow_business_use": False})
        total = {"target_indices": len(INDUSTRIES),
                 "ak_collected": sum(x["ak_rows"] > 0 for x in industries),
                 "qc_passed_indices": sum(x["ak_rows"] > 0 and not x["qc_failed"] and not x["qc_review"] for x in industries),
                 "wind_queried": sum(x["wind_rows"] > 0 for x in industries),
                 "wind_fully_verified": sum(x["verification_status"] == "VERIFIED" for x in industries),
                 "wind_partially_verified": sum(x["verification_status"] in ("PARTIAL", "CONFLICT") for x in industries),
                 "wind_unverified": sum(x["verification_status"] == "WIND_UNAVAILABLE" for x in industries),
                 "ak_rows": sum(x["ak_rows"] for x in industries),
                 "wind_common_rows": sum(x["common_rows"] for x in industries),
                 "missing_trading_days": sum(x["missing_trading_days"] for x in industries),
                 "historical_backfill_only": sum(x["prelaunch_backfill_only"] for x in industries),
                 "conflict_rows": sum(x["conflicts"] for x in industries),
                 "unresolved_anomalies": len(anomalies)}
    return {"generated_at": now_utc(), "range": {"start": start.isoformat(), "end": end.isoformat()},
            "source": {"akshare": "AKShare index_hist_sw / SWS Research",
                       "wind": "Wind MCP index_data.get_index_kline / MATCH close",
                       "calendar": "AKShare tool_trade_date_hist_sina"},
            "classification_history": {"version": "SW2021", "index_launch": SW2021_INDEX_LAUNCH,
                "before_launch": "legacy classification or retrospective series; per-index construction needs confirmation; not contemporaneously available under SW2021"},
            "totals": total, "industries": industries, "anomalies": anomalies}


def write_report(report: dict, output: Path) -> tuple[Path, Path, Path]:
    output.parent.mkdir(parents=True, exist_ok=True)
    json_path = output.with_suffix(".json")
    md_path = output.with_suffix(".md")
    exceptions_path = output.with_name(output.name + "-anomalies.csv")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    columns = ("code", "trade_date", "type", "ak_close", "wind_close",
               "absolute_error", "relative_error", "reason", "resolved", "allow_business_use")
    with exceptions_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(report["anomalies"])
    lines = ["# 申万2021版31行业数据验收", "",
             f"数据区间：{report['range']['start']} ~ {report['range']['end']}", "",
             "| 行业 | 代码 | AK起始 | AK结束 | AK条数 | 缺失交易日 | 日历覆盖率 | 采集状态 | Wind共同日期 | 共同日核验率 | 最大相对误差 | 超限 | 核验状态 |",
             "|---|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---|"]
    for item in report["industries"]:
        lines.append(f"| {item['name']} | {item['code']} | {item['start'] or '—'} | {item['end'] or '—'} | {item['ak_rows']} | {item['missing_trading_days']} | {item['calendar_coverage']:.2%} | {item['fetch_status']} | {item['common_rows']} | {item['verified_coverage']:.2%} | {item['max_relative_error'] if item['max_relative_error'] is not None else '—'} | {item['conflicts']} | {item['verification_status']} |")
    exceptions = Counter(item["type"] for item in report["anomalies"])
    totals = report["totals"]
    database_status = "PASS" if totals["ak_collected"] == totals["target_indices"] else "PARTIAL"
    quality_status = "PASS" if totals["qc_passed_indices"] == totals["target_indices"] and not totals["missing_trading_days"] else "PARTIAL"
    wind_status = "PASS" if totals["wind_fully_verified"] == totals["target_indices"] else "PARTIAL" if totals["wind_queried"] else "FAIL"
    lines.extend(["", "## 验收汇总", "", "```json", json.dumps(report["totals"], ensure_ascii=False, indent=2), "```", "",
                  f"数据库写入状态：{database_status}；数据质量状态：{quality_status}；Wind 核验状态：{wind_status}。", "",
                  "后续行业轮动数据准入：PARTIAL，仅 `sw2021_approved_daily` 中通过的逐日记录可作为候选；全区间缺口和历史分类可用性尚未解决。", "",
                  "## 异常记录", "", f"类型计数：{json.dumps(exceptions, ensure_ascii=False)}", "",
                  f"逐项原始值与原因详见 `{exceptions_path.name}`，结构化记录见 `{json_path.name}` 的 anomalies 数组。所有未解决异常均禁止业务使用。", "",
                  "2021版切换前的序列可能为旧分类或回溯值；不能当作当时已发布的 SW2021 实时信号。", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path, exceptions_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["collect", "calendar", "import-wind", "verify", "report"])
    parser.add_argument("--db", type=Path, default=DATABASE_PATH)
    parser.add_argument("--code", help="one code or comma-separated codes; default all 31")
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--overlap-days", type=int, default=30)
    parser.add_argument("--rate-delay", type=float, default=0.6)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--wind-code")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    codes = args.code.split(",") if args.code else list(INDUSTRIES)
    if any(code not in INDUSTRIES for code in codes):
        parser.error("unknown SW2021 code")
    if args.command == "calendar":
        result = {"calendar_days": load_calendar(args.db)}
    elif args.command == "collect":
        result = []
        for index, code in enumerate(codes):
            if index and args.rate_delay:
                time.sleep(args.rate_delay)
            start = incremental_start(args.db, code, args.overlap_days) if args.incremental and args.db.exists() else args.start
            result.extend(collect_many([code], args.db, start=start, end=args.end, rate_delay=0))
    elif args.command == "import-wind":
        if len(codes) != 1 or not args.file or not args.wind_code:
            parser.error("import-wind needs one --code, --wind-code and --file")
        result = import_wind(codes[0], args.wind_code, args.file, args.db, start=args.start, end=args.end)
    elif args.command == "verify":
        result = [verify_code(code, args.db) for code in codes]
    else:
        result = build_report(args.db, start=args.start, end=args.end)
        output = args.output or args.db.parent / "verification" / "sw2021" / "acceptance"
        paths = write_report(result, output)
        result = {"totals": result["totals"], "reports": [str(x) for x in paths]}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
