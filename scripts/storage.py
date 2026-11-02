from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os


SCHEMA = """
CREATE TABLE IF NOT EXISTS etf_prices (
    trade_date TEXT NOT NULL,
    product_code TEXT NOT NULL,
    close_price REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'PROVENANCE_UNKNOWN',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (trade_date, product_code)
);
CREATE INDEX IF NOT EXISTS idx_etf_prices_code_date
ON etf_prices(product_code, trade_date);
CREATE TABLE IF NOT EXISTS index_prices (
    trade_date TEXT NOT NULL,
    index_code TEXT NOT NULL,
    close_value REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'PROVENANCE_UNKNOWN',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (trade_date, index_code)
);
CREATE INDEX IF NOT EXISTS idx_index_prices_code_date
ON index_prices(index_code, trade_date);
"""


def init_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)


RELIABILITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_observations (
    raw_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    value_raw TEXT,
    unit_raw TEXT,
    provider TEXT NOT NULL,
    upstream_publisher TEXT NOT NULL,
    provider_request_id TEXT,
    source_url TEXT,
    fetched_at TEXT NOT NULL,
    raw_sha256 TEXT,
    parser_version TEXT NOT NULL DEFAULT 'v1',
    fetch_batch_id TEXT NOT NULL,
    source_publish_at TEXT,
    source_version TEXT NOT NULL DEFAULT 'unknown'
);
CREATE TABLE IF NOT EXISTS quality_issues (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    issue_code TEXT NOT NULL,
    severity TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    raw_record_id INTEGER,
    resolution_status TEXT NOT NULL DEFAULT 'open',
    resolution_evidence_id TEXT
);
CREATE TABLE IF NOT EXISTS canonical_observations (
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    normalized_value REAL,
    normalized_unit TEXT NOT NULL,
    selected_raw_id INTEGER,
    selection_reason TEXT NOT NULL,
    fact_verified INTEGER NOT NULL DEFAULT 0,
    quality_status TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    PRIMARY KEY(symbol, kind, trade_date)
);
CREATE TABLE IF NOT EXISTS release_manifest (
    snapshot_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    data_start_end TEXT,
    provider_summary TEXT,
    raw_hashes TEXT,
    validation_report_hash TEXT,
    formula_version TEXT,
    code_revision TEXT,
    published_at TEXT
);
"""


def init_reliability_schema(path: Path) -> None:
    init_database(path)
    with sqlite3.connect(path) as connection:
        connection.executescript(RELIABILITY_SCHEMA)


def record_observations(path: Path, rows: list[dict]) -> None:
    init_reliability_schema(path)
    with sqlite3.connect(path) as connection:
        connection.executemany(
            """INSERT INTO raw_observations
            (symbol,kind,trade_date,value_raw,unit_raw,provider,upstream_publisher,
             provider_request_id,source_url,fetched_at,raw_sha256,parser_version,
             fetch_batch_id,source_publish_at,source_version)
            VALUES (:symbol,:kind,:trade_date,:value_raw,:unit_raw,:provider,:upstream_publisher,
             :provider_request_id,:source_url,COALESCE(:fetched_at, :fallback_fetched_at),:raw_sha256,
             COALESCE(:parser_version,'v1'),:fetch_batch_id,:source_publish_at,COALESCE(:source_version,'unknown'))""",
            [{
                "symbol": row.get("symbol"), "kind": row.get("kind"), "trade_date": row.get("trade_date"),
                "value_raw": row.get("value_raw"), "unit_raw": row.get("unit_raw"),
                "provider": row.get("provider", "PROVENANCE_UNKNOWN"),
                "upstream_publisher": row.get("upstream_publisher", "UNKNOWN"),
                "provider_request_id": row.get("provider_request_id"), "source_url": row.get("source_url"),
                "fetched_at": row.get("fetched_at"), "fallback_fetched_at": datetime.now(timezone.utc).isoformat(),
                "raw_sha256": row.get("raw_sha256"), "parser_version": row.get("parser_version", "v1"),
                "fetch_batch_id": row.get("fetch_batch_id", "unknown"), "source_publish_at": row.get("source_publish_at"),
                "source_version": row.get("source_version", "unknown"),
            } for row in rows],
        )


def record_legacy_observations(path: Path, etf_rows: list[dict], index_rows: list[dict]) -> None:
    """Register old rows without guessing which provider produced them."""
    init_reliability_schema(path)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as connection:
        known = {(row[0], row[1], row[2]) for row in connection.execute("SELECT symbol,kind,trade_date FROM raw_observations")}
        pending = []
        for row in etf_rows:
            symbol, kind, day, value, unit = row["productCode"], "etf", row["tradeDate"], row["closePrice"], "元/份"
            if (symbol, kind, day) not in known:
                pending.append((symbol, kind, day, str(value), unit, "PROVENANCE_UNKNOWN", "UNKNOWN", now, "legacy", "legacy-migration", "legacy"))
                known.add((symbol, kind, day))
        for row in index_rows:
            symbol, kind, day, value, unit = row["indexCode"], "index", row["tradeDate"], row["closeValue"], "index_point"
            if (symbol, kind, day) not in known:
                pending.append((symbol, kind, day, str(value), unit, "PROVENANCE_UNKNOWN", "UNKNOWN", now, "legacy", "legacy-migration", "legacy"))
                known.add((symbol, kind, day))
        connection.executemany("""INSERT INTO raw_observations(symbol,kind,trade_date,value_raw,unit_raw,provider,upstream_publisher,fetched_at,parser_version,fetch_batch_id,source_version)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", pending)


def mark_legacy_sources_unknown(path: Path) -> int:
    """Correct only the misleading legacy provenance label, never market values."""
    init_database(path)
    with sqlite3.connect(path) as connection:
        cursor = connection.execute("UPDATE etf_prices SET source='PROVENANCE_UNKNOWN' WHERE source='akshare'")
        cursor2 = connection.execute("UPDATE index_prices SET source='PROVENANCE_UNKNOWN' WHERE source='akshare'")
        return cursor.rowcount + cursor2.rowcount


def save_raw_payload(data_root: Path, batch_id: str, label: str, raw_bytes: bytes) -> tuple[Path, str] | None:
    if not raw_bytes:
        return None
    digest = hashlib.sha256(raw_bytes).hexdigest()
    target_dir = data_root / "raw" / "market" / batch_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{label}-{digest[:16]}.bin"
    if not target.exists():
        target.write_bytes(raw_bytes)
    return target, digest


def record_quality_issues(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    init_reliability_schema(path)
    with sqlite3.connect(path) as connection:
        connection.executemany(
            """INSERT INTO quality_issues(symbol,kind,trade_date,issue_code,severity,detected_at,batch_id,raw_record_id,resolution_status)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [(row["symbol"], row["kind"], row["trade_date"], row["issue_code"], row.get("severity", "BLOCKED"), row.get("detected_at", datetime.now(timezone.utc).isoformat()), row.get("batch_id", "unknown"), row.get("raw_record_id"), row.get("resolution_status", "open")) for row in rows],
        )


def record_canonical_observations(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    init_reliability_schema(path)
    with sqlite3.connect(path) as connection:
        connection.executemany(
            """INSERT OR REPLACE INTO canonical_observations
               (symbol,kind,trade_date,normalized_value,normalized_unit,selected_raw_id,selection_reason,fact_verified,quality_status,batch_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [(row["symbol"], row["kind"], row["trade_date"], row["normalized_value"], row["normalized_unit"], row.get("selected_raw_id"), row["selection_reason"], int(row.get("fact_verified", False)), row.get("quality_status", "PASS"), row["batch_id"]) for row in rows],
        )


def delete_canonical_index_observations(path: Path, keys: list[tuple[str, str]]) -> None:
    if not keys:
        return
    init_reliability_schema(path)
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "DELETE FROM canonical_observations WHERE kind='index' AND symbol=? AND trade_date=?",
            keys,
        )


def record_release_manifest(path: Path, manifest: dict) -> None:
    init_reliability_schema(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """INSERT OR REPLACE INTO release_manifest
               (snapshot_id,created_at,status,data_start_end,provider_summary,raw_hashes,validation_report_hash,formula_version,code_revision,published_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (manifest["snapshot_id"], manifest.get("created_at"), manifest.get("status"), manifest.get("data_start_end"), json.dumps(manifest.get("provider_summary", {}), ensure_ascii=False), json.dumps(manifest.get("sha256", {}), ensure_ascii=False), manifest.get("validation_report_hash"), manifest.get("formula_version", "prism-v2"), manifest.get("code_revision", "working-tree"), manifest.get("created_at")),
        )


def publish_snapshot(data_root: Path, snapshot_id: str, etf_payload: dict, index_payload: dict, *, fail_at: str | None = None) -> dict:
    """Stage both payloads then atomically switch one manifest pointer."""
    release_dir = data_root / "releases" / snapshot_id
    release_dir.mkdir(parents=True, exist_ok=False)
    if fail_at == "json":
        raise RuntimeError("simulated JSON write failure")
    etf_path = release_dir / "etf_prices.json"
    index_path = release_dir / "index_prices.json"
    etf_path.write_text(json.dumps(etf_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    index_path.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "snapshot_id": snapshot_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "published",
        "files": {"etf": str(etf_path.relative_to(data_root)), "index": str(index_path.relative_to(data_root))},
        "sha256": {"etf": hashlib.sha256(etf_path.read_bytes()).hexdigest(), "index": hashlib.sha256(index_path.read_bytes()).hexdigest()},
    }
    if fail_at == "manifest":
        raise RuntimeError("simulated manifest write failure")
    manifest_tmp = data_root / "current_manifest.json.tmp"
    manifest_tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(manifest_tmp, data_root / "current_manifest.json")
    return manifest


def _upsert_etf_rows(connection, records: list[dict], updated_at: str, source_by_key: dict | None = None) -> None:
    source_by_key = source_by_key or {}
    connection.executemany(
        """INSERT INTO etf_prices(trade_date, product_code, close_price, source, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(trade_date, product_code) DO UPDATE SET
             close_price=excluded.close_price,
             source=excluded.source,
             updated_at=excluded.updated_at""",
        [(r["tradeDate"], r["productCode"], r["closePrice"], source_by_key.get((r["tradeDate"], r["productCode"]), "PROVENANCE_UNKNOWN"), updated_at) for r in records],
    )


def upsert_records(path: Path, records: list[dict], updated_at: str, source_by_key: dict | None = None) -> None:
    init_database(path)
    with sqlite3.connect(path) as connection:
        _upsert_etf_rows(connection, records, updated_at, source_by_key)


def read_records(path: Path) -> list[dict]:
    init_database(path)
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT trade_date, product_code, close_price FROM etf_prices ORDER BY trade_date, product_code"
        ).fetchall()
    return [{"tradeDate": d, "productCode": c, "closePrice": float(p)} for d, c, p in rows]


def _upsert_index_rows(connection, records: list[dict], updated_at: str, source_by_key: dict | None = None) -> None:
    source_by_key = source_by_key or {}
    connection.executemany(
        """INSERT INTO index_prices(trade_date, index_code, close_value, source, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(trade_date, index_code) DO UPDATE SET
             close_value=excluded.close_value,
             source=excluded.source,
             updated_at=excluded.updated_at""",
        [(r["tradeDate"], r["indexCode"], r["closeValue"], source_by_key.get((r["tradeDate"], r["indexCode"]), "PROVENANCE_UNKNOWN"), updated_at) for r in records],
    )


def upsert_index_records(path: Path, records: list[dict], updated_at: str, source_by_key: dict | None = None) -> None:
    init_database(path)
    with sqlite3.connect(path) as connection:
        _upsert_index_rows(connection, records, updated_at, source_by_key)


def upsert_market_records_atomic(path: Path, records: list[dict], index_records: list[dict], updated_at: str, source_by_key: dict | None = None, index_source_by_key: dict | None = None, *, delete_index_keys: list[tuple[str, str]] | None = None, fail_at: str | None = None) -> None:
    """Commit ETF and index canonical rows in one SQLite transaction."""
    init_database(path)
    connection = sqlite3.connect(path)
    try:
        with connection:
            _upsert_etf_rows(connection, records, updated_at, source_by_key)
            if fail_at == "sqlite":
                raise sqlite3.OperationalError("simulated SQLite write failure")
            if delete_index_keys:
                connection.executemany(
                    "DELETE FROM index_prices WHERE trade_date=? AND index_code=?",
                    delete_index_keys,
                )
            _upsert_index_rows(connection, index_records, updated_at, index_source_by_key)
    finally:
        connection.close()


def read_index_records(path: Path) -> list[dict]:
    init_database(path)
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT trade_date, index_code, close_value FROM index_prices ORDER BY trade_date, index_code").fetchall()
    return [{"tradeDate": d, "indexCode": c, "closeValue": float(v)} for d, c, v in rows]
