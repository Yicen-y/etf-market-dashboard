"""Versioned SQLite storage for official dividend valuation observations."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import sqlite3
from pathlib import Path


RESEARCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_series (
    series_id TEXT PRIMARY KEY,
    source_code TEXT,
    series_name TEXT NOT NULL,
    currency TEXT NOT NULL,
    return_type TEXT NOT NULL,
    unit TEXT NOT NULL,
    provider TEXT NOT NULL,
    upstream TEXT NOT NULL,
    source_url TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_observations (
    series_id TEXT NOT NULL,
    observation_date TEXT NOT NULL,
    value REAL NOT NULL,
    available_at TEXT,
    provider TEXT NOT NULL,
    upstream TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    raw_payload_ref TEXT NOT NULL,
    quality_status TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY(series_id, observation_date, provider, source_hash),
    FOREIGN KEY(series_id) REFERENCES research_series(series_id)
);
CREATE INDEX IF NOT EXISTS idx_research_observations_series_date
ON research_observations(series_id, observation_date, fetched_at);
"""


SERIES_DEFINITIONS = {
    "CSI_DIV_YIELD2_000922": {"source_code": "000922", "series_name": "中证红利官方股息率2",
                               "currency": "CNY", "return_type": "valuation_metric", "unit": "%"},
    "CCDC_CN10Y": {"source_code": None, "series_name": "中债国债收益率曲线10年到期收益率",
                    "currency": "CNY", "return_type": "yield_curve", "unit": "%"},
}


def record_research_series(path: Path, series_id: str, rows: list[dict], metadata: dict,
                           source_hash: str, raw_payload_ref: str) -> int:
    if series_id not in SERIES_DEFINITIONS:
        raise ValueError(f"unsupported research series: {series_id}")
    fetched_at = datetime.now(timezone.utc).isoformat()
    definition = SERIES_DEFINITIONS[series_id]
    seen = set()
    accepted = []
    for row in rows:
        day = str(row.get("tradeDate", ""))
        try:
            datetime.strptime(day, "%Y%m%d")
        except ValueError:
            raise ValueError(f"invalid research observation date: {day}") from None
        value = row.get("value")
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"invalid research observation value on {day}")
        if day in seen:
            raise ValueError(f"duplicate research observation date: {day}")
        seen.add(day)
        accepted.append((series_id, day, float(value), metadata.get("availableAt"),
                         metadata["provider"], metadata["upstream"], source_hash,
                         raw_payload_ref, "VALID", fetched_at))
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(RESEARCH_SCHEMA)
        connection.execute(
            """INSERT INTO research_series(series_id,source_code,series_name,currency,return_type,unit,provider,upstream,source_url,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(series_id) DO UPDATE SET
               source_code=excluded.source_code,series_name=excluded.series_name,currency=excluded.currency,
               return_type=excluded.return_type,unit=excluded.unit,provider=excluded.provider,
               upstream=excluded.upstream,source_url=excluded.source_url,updated_at=excluded.updated_at""",
            (series_id, definition["source_code"], definition["series_name"], definition["currency"],
             definition["return_type"], metadata.get("unit", definition["unit"]), metadata["provider"],
             metadata["upstream"], metadata.get("sourceUrl"), fetched_at),
        )
        before = connection.total_changes
        connection.executemany(
            """INSERT OR IGNORE INTO research_observations
               (series_id,observation_date,value,available_at,provider,upstream,source_hash,raw_payload_ref,quality_status,fetched_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""", accepted,
        )
        return connection.total_changes - before


def read_research_series(path: Path, series_id: str, start_date: str, end_date: str, *, include_revisions=False) -> list[dict]:
    if not path.exists():
        return []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_observations'").fetchone()
        if not exists:
            return []
        rows = connection.execute(
            """SELECT observation_date,value,provider,quality_status,fetched_at,source_hash,raw_payload_ref
               FROM research_observations WHERE series_id=? AND observation_date BETWEEN ? AND ?
               ORDER BY observation_date,fetched_at""", (series_id, start_date, end_date),
        ).fetchall()
    items = [dict(tradeDate=row["observation_date"], value=row["value"], availableAt=None, provider=row["provider"],
                  qualityStatus=row["quality_status"], fetchedAt=row["fetched_at"],
                  sourceHash=row["source_hash"], rawPayloadRef=row["raw_payload_ref"]) for row in rows]
    if include_revisions:
        return items
    latest = {}
    for item in items:
        latest[item["tradeDate"]] = {key: item[key] for key in ("tradeDate", "value", "availableAt", "qualityStatus", "provider")}
    return list(latest.values())


def research_series_metadata(path: Path, series_id: str) -> dict | None:
    if not path.exists():
        return None
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_series'").fetchone()
        if not exists:
            return None
        row = connection.execute("SELECT * FROM research_series WHERE series_id=?", (series_id,)).fetchone()
        if not row:
            return None
        return dict(row)
