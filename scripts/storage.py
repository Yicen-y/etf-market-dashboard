from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, time as clock_time, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
import os
import re
import time


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
CREATE TABLE IF NOT EXISTS nikkei225_anchor_prices (
    trade_date TEXT PRIMARY KEY,
    open_value REAL,
    close_value REAL NOT NULL,
    high_value REAL,
    low_value REAL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nikkei225_anchor_date
ON nikkei225_anchor_prices(trade_date);
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
CREATE TABLE IF NOT EXISTS market_price_revisions (
    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    old_value REAL NOT NULL,
    new_value REAL NOT NULL,
    old_source TEXT NOT NULL,
    new_source TEXT NOT NULL,
    old_raw_id INTEGER,
    new_raw_id INTEGER,
    fetch_batch_id TEXT NOT NULL,
    detected_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_price_revisions_key
ON market_price_revisions(kind,symbol,trade_date);
"""


def init_reliability_schema(path: Path) -> None:
    init_database(path)
    with sqlite3.connect(path) as connection:
        connection.executescript(RELIABILITY_SCHEMA)


def record_observations(path: Path, rows: list[dict], connection=None) -> None:
    if connection is None:
        init_reliability_schema(path)
        with sqlite3.connect(path) as own_connection:
            return record_observations(path, rows, own_connection)
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
    """Legacy compatibility hook: unknown history must not masquerade as raw evidence."""
    return None


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


def record_quality_issues(path: Path, rows: list[dict], connection=None) -> None:
    if not rows:
        return
    if connection is None:
        init_reliability_schema(path)
        with sqlite3.connect(path) as own_connection:
            return record_quality_issues(path, rows, own_connection)
    connection.executemany(
            """INSERT INTO quality_issues(symbol,kind,trade_date,issue_code,severity,detected_at,batch_id,raw_record_id,resolution_status,resolution_evidence_id)
               SELECT ?,?,?,?,?,?,?,?,?,? WHERE NOT EXISTS (
                 SELECT 1 FROM quality_issues WHERE symbol=? AND kind=? AND trade_date=?
                 AND issue_code=? AND resolution_status=?)""",
            [(row["symbol"], row["kind"], row["trade_date"], row["issue_code"], row.get("severity", "BLOCKED"), row.get("detected_at", datetime.now(timezone.utc).isoformat()), row.get("batch_id", "unknown"), row.get("raw_record_id"), row.get("resolution_status", "open"), row.get("resolution_evidence_id"), row["symbol"], row["kind"], row["trade_date"], row["issue_code"], row.get("resolution_status", "open")) for row in rows],
        )


def record_canonical_observations(path: Path, rows: list[dict], connection=None) -> None:
    if not rows:
        return
    if connection is None:
        init_reliability_schema(path)
        with sqlite3.connect(path) as own_connection:
            return record_canonical_observations(path, rows, own_connection)
    connection.executemany(
            """INSERT INTO canonical_observations
               (symbol,kind,trade_date,normalized_value,normalized_unit,selected_raw_id,selection_reason,fact_verified,quality_status,batch_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(symbol,kind,trade_date) DO UPDATE SET
                 normalized_value=excluded.normalized_value,
                 normalized_unit=excluded.normalized_unit,
                 selected_raw_id=excluded.selected_raw_id,
                 selection_reason=excluded.selection_reason,
                 fact_verified=excluded.fact_verified,
                 quality_status=excluded.quality_status,
                 batch_id=excluded.batch_id
               WHERE canonical_observations.normalized_value IS NOT excluded.normalized_value
                  OR canonical_observations.normalized_unit IS NOT excluded.normalized_unit
                  OR (canonical_observations.selected_raw_id IS NULL AND excluded.selected_raw_id IS NOT NULL)""",
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


def record_release_manifest(path: Path, manifest: dict, connection=None) -> None:
    if connection is None:
        init_reliability_schema(path)
        with sqlite3.connect(path) as own_connection:
            return record_release_manifest(path, manifest, own_connection)
    connection.execute(
            """INSERT OR REPLACE INTO release_manifest
               (snapshot_id,created_at,status,data_start_end,provider_summary,raw_hashes,validation_report_hash,formula_version,code_revision,published_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (manifest["snapshot_id"], manifest.get("created_at"), manifest.get("status"), manifest.get("data_start_end"), json.dumps(manifest.get("provider_summary", {}), ensure_ascii=False), json.dumps(manifest.get("sha256", {}), ensure_ascii=False), manifest.get("validation_report_hash"), manifest.get("formula_version", "prism-v2"), manifest.get("code_revision", "working-tree"), manifest.get("created_at") if manifest.get("status") == "published" else None),
        )


def publish_snapshot(data_root: Path, snapshot_id: str, etf_payload: dict, index_payload: dict, *, fail_at: str | None = None, activate: bool = True, fetch_batch_id: str | None = None, prepublish_fingerprint: str | None = None, expected_raw_count: int | None = None, expected_canonical_count: int | None = None) -> dict:
    """Stage both payloads then atomically switch one manifest pointer."""
    release_dir = data_root / "releases" / snapshot_id
    release_dir.mkdir(parents=True, exist_ok=False)
    if fail_at == "json":
        raise RuntimeError("simulated JSON write failure")
    etf_path = release_dir / "etf_prices.json"
    index_path = release_dir / "index_prices.json"
    etf_json = json.dumps(etf_payload, ensure_ascii=False, indent=2)
    index_json = json.dumps(index_payload, ensure_ascii=False, indent=2)
    etf_path.write_text(etf_json, encoding="utf-8")
    index_path.write_text(index_json, encoding="utf-8")
    manifest = {
        "snapshot_id": snapshot_id,
        "fetch_batch_id": fetch_batch_id,
        "prepublish_fingerprint": prepublish_fingerprint,
        "expected_raw_count": expected_raw_count,
        "expected_canonical_count": expected_canonical_count,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "published",
        "files": {"etf": etf_path.relative_to(data_root).as_posix(), "index": index_path.relative_to(data_root).as_posix()},
        "sha256": {"etf": hashlib.sha256(etf_path.read_bytes()).hexdigest(), "index": hashlib.sha256(index_path.read_bytes()).hexdigest()},
    }
    from .snapshot import read_dataset
    read_dataset(data_root, manifest, "etf")
    read_dataset(data_root, manifest, "index")
    if fail_at == "manifest":
        raise RuntimeError("simulated manifest write failure")
    (release_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if activate:
        activate_snapshot(data_root, manifest)
    return manifest


def activate_snapshot(data_root: Path, manifest: dict) -> None:
    """Expose a fully staged release through one atomic pointer replacement.

    Root-level JSON files are historical compatibility artifacts, not live
    publication targets: replacing two files cannot form one atomic snapshot.
    """
    from .snapshot import read_dataset
    for key in ("etf", "index"):
        read_dataset(data_root, manifest, key)
    manifest_tmp = data_root / "current_manifest.json.tmp"
    manifest_tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _replace_with_reader_retry(manifest_tmp, data_root / "current_manifest.json")


def _replace_with_reader_retry(source: Path, target: Path) -> None:
    """Windows cannot replace a destination while a reader holds its handle."""
    deadline = time.monotonic() + 2.0
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if os.name != "nt" or time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def market_fingerprint(database: Path) -> str:
    """Digest the market and provenance state before a staged release writes it."""
    digest = hashlib.sha256()
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        for table, order in (("etf_prices", "trade_date,product_code"),
                             ("index_prices", "trade_date,index_code"),
                             ("canonical_observations", "symbol,kind,trade_date"),
                             ("raw_observations", "raw_record_id"),
                             ("quality_issues", "issue_id")):
            digest.update(table.encode("ascii"))
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order}"):
                digest.update(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                digest.update(b"\n")
    return digest.hexdigest()


def _database_matches_release(database: Path, etf: dict, index: dict, manifest: dict) -> bool:
    try:
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            etf_values = {(day, code): value for day, code, value in connection.execute(
                "SELECT trade_date,product_code,close_price FROM etf_prices")}
            index_values = {(day, code): value for day, code, value in connection.execute(
                "SELECT trade_date,index_code,close_value FROM index_prices")}
            batch = manifest.get("fetch_batch_id")
            if batch:
                raw_count = connection.execute("SELECT COUNT(*) FROM raw_observations WHERE fetch_batch_id=?", (batch,)).fetchone()[0]
                canonical_count, unlinked = connection.execute(
                    "SELECT COUNT(*),SUM(selected_raw_id IS NULL) FROM canonical_observations WHERE batch_id=?", (batch,)).fetchone()
                if (manifest.get("expected_raw_count") is not None and raw_count != manifest["expected_raw_count"]
                    or manifest.get("expected_canonical_count") is not None and canonical_count != manifest["expected_canonical_count"]
                    or unlinked):
                    return False
        return all(etf_values.get((row["tradeDate"], row["productCode"])) == row["closePrice"]
                   for row in etf["flatRecords"]) and all(
                   index_values.get((row["tradeDate"], row["indexCode"])) == row["closeValue"]
                   for row in index["flatRecords"])
    except (OSError, sqlite3.Error, KeyError, TypeError):
        return False


def recover_prepared_release(data_root: Path, database: Path) -> dict:
    """Finish a valid prepared release after a crash; never guess missing data."""
    from .snapshot import read_dataset, read_manifest
    try:
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            candidates = connection.execute(
                "SELECT snapshot_id,created_at FROM release_manifest WHERE status='prepared' ORDER BY created_at DESC"
            ).fetchall()
    except (OSError, sqlite3.Error):
        return {"state": "NO_PENDING"}
    if not candidates:
        return {"state": "NO_PENDING"}
    current = read_manifest(data_root)
    for snapshot_id, created_at in candidates:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", snapshot_id or ""):
            return {"state": "BLOCKED", "snapshot_id": snapshot_id, "reason": "invalid release identifier"}
        if current["snapshot_id"] == snapshot_id:
            with sqlite3.connect(database) as connection:
                connection.execute("UPDATE release_manifest SET status='published',published_at=? WHERE snapshot_id=?",
                                   (datetime.now(timezone.utc).isoformat(), snapshot_id))
            return {"state": "RECOVERED", "snapshot_id": snapshot_id}
        if current.get("created_at") and created_at <= current["created_at"]:
            continue
        manifest_path = data_root / "releases" / snapshot_id / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest["snapshot_id"] != snapshot_id or any(
                not str(manifest["files"][key]).replace("\\", "/").startswith(f"releases/{snapshot_id}/")
                for key in ("etf", "index")
            ):
                raise ValueError("release identity mismatch")
            etf = read_dataset(data_root, manifest, "etf")
            index = read_dataset(data_root, manifest, "index")
            if not _database_matches_release(database, etf, index, manifest):
                if manifest.get("prepublish_fingerprint") and market_fingerprint(database) == manifest["prepublish_fingerprint"]:
                    with sqlite3.connect(database) as connection:
                        connection.execute("UPDATE release_manifest SET status='aborted' WHERE snapshot_id=?", (snapshot_id,))
                    return {"state": "ABORTED", "snapshot_id": snapshot_id}
                raise ValueError("database does not match staged release")
            activate_snapshot(data_root, manifest)
            with sqlite3.connect(database) as connection:
                connection.execute("UPDATE release_manifest SET status='published',published_at=? WHERE snapshot_id=?",
                                   (datetime.now(timezone.utc).isoformat(), snapshot_id))
            return {"state": "RECOVERED", "snapshot_id": snapshot_id}
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            return {"state": "BLOCKED", "snapshot_id": snapshot_id, "reason": str(error)}
    return {"state": "SUPERSEDED"}


def _upsert_etf_rows(connection, records: list[dict], updated_at: str, source_by_key: dict | None = None) -> None:
    source_by_key = source_by_key or {}
    connection.executemany(
        """INSERT INTO etf_prices(trade_date, product_code, close_price, source, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(trade_date, product_code) DO UPDATE SET
             close_price=excluded.close_price,
             source=CASE WHEN excluded.source='PROVENANCE_UNKNOWN' THEN etf_prices.source ELSE excluded.source END,
             updated_at=excluded.updated_at
           WHERE etf_prices.close_price IS NOT excluded.close_price""",
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
             source=CASE WHEN excluded.source='PROVENANCE_UNKNOWN' THEN index_prices.source ELSE excluded.source END,
             updated_at=excluded.updated_at
           WHERE index_prices.close_value IS NOT excluded.close_value""",
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


def commit_market_release(path: Path, *, raw_rows: list[dict], quality_rows: list[dict],
                          etf_rows: list[dict], index_rows: list[dict], updated_at: str,
                          etf_sources: dict, index_sources: dict,
                          delete_index_keys: list[tuple[str, str]],
                          canonical_rows: list[dict], canonical_delete_keys: list[tuple[str, str]],
                          manifest: dict, fail_at: str | None = None) -> None:
    """Make prices, source links and the prepared marker one SQLite commit."""
    init_reliability_schema(path)
    with sqlite3.connect(path) as connection:
        record_observations(path, raw_rows, connection)
        record_quality_issues(path, quality_rows, connection)
        batch = manifest.get("fetch_batch_id")
        raw_ids = {(symbol, kind, day): raw_id for raw_id, symbol, kind, day in connection.execute(
            "SELECT raw_record_id,symbol,kind,trade_date FROM raw_observations WHERE fetch_batch_id=? ORDER BY raw_record_id", (batch,))}
        for kind, rows, table, code_column, value_column, sources in (
            ("etf", etf_rows, "etf_prices", "product_code", "close_price", etf_sources),
            ("index", index_rows, "index_prices", "index_code", "close_value", index_sources),
        ):
            for row in rows:
                day = row["tradeDate"]
                symbol = row["productCode"] if kind == "etf" else row["indexCode"]
                value = row["closePrice"] if kind == "etf" else row["closeValue"]
                previous = connection.execute(
                    f"SELECT {value_column},source FROM {table} WHERE trade_date=? AND {code_column}=?",
                    (day, symbol)).fetchone()
                if not previous or previous[0] == value:
                    continue
                prior_raw = connection.execute(
                    "SELECT selected_raw_id FROM canonical_observations WHERE symbol=? AND kind=? AND trade_date=?",
                    (symbol, kind, day)).fetchone()
                candidate_source = sources.get((day, symbol), "PROVENANCE_UNKNOWN")
                selected_source = previous[1] if candidate_source == "PROVENANCE_UNKNOWN" else candidate_source
                connection.execute("""INSERT INTO market_price_revisions
                    (kind,symbol,trade_date,old_value,new_value,old_source,new_source,
                     old_raw_id,new_raw_id,fetch_batch_id,detected_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (kind, symbol, day, previous[0], value, previous[1], selected_source,
                     prior_raw[0] if prior_raw else None, raw_ids.get((symbol, kind, day)),
                     batch, updated_at))
        _upsert_etf_rows(connection, etf_rows, updated_at, etf_sources)
        if delete_index_keys:
            connection.executemany("DELETE FROM index_prices WHERE trade_date=? AND index_code=?", delete_index_keys)
        _upsert_index_rows(connection, index_rows, updated_at, index_sources)
        if fail_at == "sqlite":
            raise sqlite3.OperationalError("simulated release transaction failure")
        linked = [{**row, "selected_raw_id": raw_ids.get((row["symbol"], row["kind"], row["trade_date"]))}
                  for row in canonical_rows]
        if any(row["selected_raw_id"] is None for row in linked):
            raise ValueError("canonical row lacks raw evidence")
        record_canonical_observations(path, linked, connection)
        if canonical_delete_keys:
            connection.executemany("DELETE FROM canonical_observations WHERE kind='index' AND symbol=? AND trade_date=?", canonical_delete_keys)
        record_release_manifest(path, {**manifest, "status": "prepared"}, connection)


def read_index_records(path: Path) -> list[dict]:
    init_database(path)
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT trade_date, index_code, close_value FROM index_prices ORDER BY trade_date, index_code").fetchall()
    return [{"tradeDate": d, "indexCode": c, "closeValue": float(v)} for d, c, v in rows]


def upsert_nikkei_anchor_records(path: Path, records: list[dict], updated_at: str, source: str) -> dict:
    """Persist the separate Tokyo-calendar series without mixing it into CSI data."""
    if not records:
        return {"inserted": 0, "replaced": 0}
    init_database(path)
    with sqlite3.connect(path) as connection:
        existing = {row[0]: row[1:] for row in connection.execute(
            "SELECT trade_date,open_value,close_value,high_value,low_value,source,updated_at "
            "FROM nikkei225_anchor_prices WHERE trade_date BETWEEN ? AND ?",
            (min(row["tradeDate"] for row in records), max(row["tradeDate"] for row in records)))}
        changed = [row for row in records if row["tradeDate"] not in existing
                   or existing[row["tradeDate"]][:5] != (
                       row.get("open"), row["close"], row.get("high"), row.get("low"), source)
                   or not nikkei_close_is_published(row["tradeDate"], existing[row["tradeDate"]][5])]
        connection.executemany(
            """INSERT INTO nikkei225_anchor_prices
               (trade_date,open_value,close_value,high_value,low_value,source,updated_at)
               VALUES (?,?,?,?,?,?,?) ON CONFLICT(trade_date) DO UPDATE SET
               open_value=excluded.open_value,close_value=excluded.close_value,
               high_value=excluded.high_value,low_value=excluded.low_value,
               source=excluded.source,updated_at=excluded.updated_at""",
        [(row["tradeDate"], row.get("open"), row["close"], row.get("high"), row.get("low"), source, updated_at) for row in changed],
        )
    return {"inserted": sum(row["tradeDate"] not in existing for row in changed),
            "replaced": sum(row["tradeDate"] in existing for row in changed),
            "changed_dates": [row["tradeDate"] for row in changed]}


def read_nikkei_anchor_records(path: Path) -> list[dict]:
    init_database(path)
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT trade_date,open_value,close_value,high_value,low_value,source,updated_at "
            "FROM nikkei225_anchor_prices ORDER BY trade_date"
        ).fetchall()
    return [{"tradeDate": d, "open": o, "close": c, "high": h, "low": l, "source": s, "updatedAt": u}
            for d, o, c, h, l, s, u in rows if nikkei_close_is_published(d, u)]


def nikkei_close_is_published(trade_date: str, updated_at: str, now_tokyo: datetime | None = None) -> bool:
    """Hide a same-day temporary bar until it was fetched after Tokyo close."""
    current = now_tokyo or datetime.now(ZoneInfo("Asia/Tokyo"))
    today = current.strftime("%Y%m%d")
    if trade_date < today:
        return True
    if trade_date > today or current.time() < clock_time(15, 30):
        return False
    try:
        fetched = datetime.fromisoformat(updated_at)
        if fetched.tzinfo is None:
            return False
        tokyo = fetched.astimezone(ZoneInfo("Asia/Tokyo"))
        return tokyo.date() == current.date() and tokyo.time() >= clock_time(15, 30)
    except ValueError:
        return False


def corroborating_raw_matches(database: Path, data_root: Path, kind: str, symbol: str, day: str,
                              value: float, limit: int = 5) -> list[dict]:
    """Report independently matching archived raw responses without claiming selection."""
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        candidates = connection.execute("""SELECT raw_record_id,provider,upstream_publisher,raw_sha256,
            fetch_batch_id,source_version FROM raw_observations
            WHERE kind=? AND symbol=? AND trade_date=? AND CAST(value_raw AS REAL)=?
              AND raw_sha256 IS NOT NULL AND provider!='PROVENANCE_UNKNOWN'
            ORDER BY raw_record_id DESC LIMIT 100""", (kind, symbol, day, value)).fetchall()
    found = []
    for raw_id, provider, upstream, digest, batch, basis in candidates:
        if not re.fullmatch(r"[a-f0-9]{64}", digest or "") or not re.fullmatch(r"[a-zA-Z0-9_-]+", batch or ""):
            continue
        folder = data_root / "raw" / "market" / batch
        for file in folder.glob(f"*-{digest[:16]}.bin"):
            if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
                continue
            found.append({"raw_record_id": raw_id, "provider": provider, "upstream_publisher": upstream,
                          "raw_sha256": digest, "price_basis": basis, "link_status": "CORROBORATING_NOT_SELECTED"})
            break
        if len(found) >= limit:
            break
    return found
