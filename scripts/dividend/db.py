from __future__ import annotations

import sqlite3
import hashlib
import json
from pathlib import Path
from typing import Mapping


SCHEMA = """
CREATE TABLE IF NOT EXISTS dividend_securities (
 security_id TEXT PRIMARY KEY, code TEXT NOT NULL, name TEXT NOT NULL, market TEXT NOT NULL,
 security_type TEXT NOT NULL CHECK (security_type IN ('ETF','STOCK')), aliases TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS dividend_watchlist (
 security_id TEXT PRIMARY KEY REFERENCES dividend_securities(security_id), added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, sort_order INTEGER
);
CREATE TABLE IF NOT EXISTS dividend_quotes (security_id TEXT NOT NULL, trade_date TEXT NOT NULL, price TEXT, source_id TEXT, PRIMARY KEY(security_id, trade_date));
CREATE TABLE IF NOT EXISTS dividend_quote_verifications (
 security_id TEXT NOT NULL, trade_date TEXT NOT NULL, wind_price TEXT, akshare_price TEXT,
 wind_sha256 TEXT NOT NULL, akshare_sha256 TEXT NOT NULL, checked_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK (status IN ('MATCH','MISMATCH','WIND_ONLY','AKSHARE_ONLY')),
 PRIMARY KEY(security_id,trade_date,wind_sha256,akshare_sha256)
);
CREATE TABLE IF NOT EXISTS dividend_provider_yields (
 security_id TEXT PRIMARY KEY REFERENCES dividend_securities(security_id),
 value_pct TEXT, as_of_date TEXT, fetched_at TEXT NOT NULL,
 provider TEXT NOT NULL, metric_label TEXT NOT NULL,
 source_sha256 TEXT, status TEXT NOT NULL, reason TEXT
);
CREATE TABLE IF NOT EXISTS dividend_provider_yield_history (
 security_id TEXT NOT NULL REFERENCES dividend_securities(security_id),
 trade_date TEXT NOT NULL,
 value_pct TEXT,
 provider TEXT NOT NULL,
 metric_label TEXT NOT NULL,
 source_sha256 TEXT,
 fetched_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK (status IN ('READY','FAILED')),
 reason TEXT,
 PRIMARY KEY (security_id, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_dividend_provider_yield_history_date
 ON dividend_provider_yield_history(security_id, trade_date);
CREATE TABLE IF NOT EXISTS dividend_coverage (
 security_id TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
 evidence_sha256 TEXT NOT NULL, verified_at TEXT NOT NULL,
 dividends_complete INTEGER NOT NULL CHECK (dividends_complete IN (0,1)),
 actions_verified INTEGER NOT NULL CHECK (actions_verified IN (0,1)),
 quote_calendar_verified INTEGER NOT NULL DEFAULT 0 CHECK (quote_calendar_verified IN (0,1)),
 query_mode TEXT NOT NULL DEFAULT 'latest_verified',
 PRIMARY KEY(security_id,start_date,end_date,evidence_sha256)
);
CREATE TABLE IF NOT EXISTS dividend_events (
 event_id TEXT PRIMARY KEY, security_id TEXT NOT NULL, fiscal_year INTEGER, ex_date TEXT, amount_per_unit TEXT, state TEXT NOT NULL, current_revision_id TEXT
);
CREATE TABLE IF NOT EXISTS dividend_revisions (
 revision_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES dividend_events(event_id), disclosed_at TEXT, known_at TEXT, raw_amount TEXT, raw_unit TEXT, status TEXT NOT NULL, source_document_id TEXT,
 ex_date TEXT, fiscal_year INTEGER
);
CREATE TABLE IF NOT EXISTS source_documents (
 id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL, title TEXT, publisher TEXT, url TEXT, sha256 TEXT NOT NULL UNIQUE, published_at TEXT, parser_version TEXT,
 verification_level TEXT NOT NULL DEFAULT 'UNVERIFIED'
);
CREATE TABLE IF NOT EXISTS raw_source_records (
 id INTEGER PRIMARY KEY AUTOINCREMENT, source_document_id INTEGER REFERENCES source_documents(id), observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS dividend_corporate_actions (action_id TEXT PRIMARY KEY, security_id TEXT NOT NULL, effective_date TEXT NOT NULL, ratio TEXT NOT NULL, action_type TEXT NOT NULL, source_document_id INTEGER);
CREATE TABLE IF NOT EXISTS dividend_event_reconciliations (
 candidate_event_id TEXT PRIMARY KEY REFERENCES dividend_events(event_id),
 official_event_id TEXT NOT NULL REFERENCES dividend_events(event_id),
 candidate_revision_id TEXT NOT NULL, official_revision_id TEXT NOT NULL,
 evidence_sha256 TEXT NOT NULL, checked_at TEXT NOT NULL,
 amount_difference TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dividend_verification_runs (run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL, report TEXT);
"""


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as connection:
        connection.executescript(SCHEMA)
        columns = {row['name'] for row in connection.execute('PRAGMA table_info(source_documents)')}
        if 'verification_level' not in columns:
            connection.execute("ALTER TABLE source_documents ADD COLUMN verification_level TEXT NOT NULL DEFAULT 'UNVERIFIED'")
        quote_columns = {row['name'] for row in connection.execute('PRAGMA table_info(dividend_quotes)')}
        if 'verification_level' not in quote_columns:
            connection.execute("ALTER TABLE dividend_quotes ADD COLUMN verification_level TEXT NOT NULL DEFAULT 'UNVERIFIED'")
        revision_columns = {row['name'] for row in connection.execute('PRAGMA table_info(dividend_revisions)')}
        if 'ex_date' not in revision_columns:
            connection.execute('ALTER TABLE dividend_revisions ADD COLUMN ex_date TEXT')
        if 'fiscal_year' not in revision_columns:
            connection.execute('ALTER TABLE dividend_revisions ADD COLUMN fiscal_year INTEGER')
        coverage_columns = {row['name'] for row in connection.execute('PRAGMA table_info(dividend_coverage)')}
        if 'quote_calendar_verified' not in coverage_columns:
            connection.execute('ALTER TABLE dividend_coverage ADD COLUMN quote_calendar_verified INTEGER NOT NULL DEFAULT 0')
        if 'query_mode' not in coverage_columns:
            connection.execute("ALTER TABLE dividend_coverage ADD COLUMN query_mode TEXT NOT NULL DEFAULT 'latest_verified'")


def upsert_security(path: Path, item: Mapping[str, str]) -> None:
    init_schema(path)
    with connect(path) as connection:
        connection.execute("""INSERT INTO dividend_securities(security_id,code,name,market,security_type,aliases)
            VALUES (:security_id,:code,:name,:market,:security_type,:aliases)
            ON CONFLICT(security_id) DO UPDATE SET code=excluded.code,name=excluded.name,market=excluded.market,security_type=excluded.security_type,aliases=excluded.aliases""", item)


def add_watchlist(path: Path, security_id: str) -> None:
    init_schema(path)
    with connect(path) as connection:
        connection.execute("INSERT OR IGNORE INTO dividend_watchlist(security_id) VALUES (?)", (security_id,))


def remove_watchlist(path: Path, security_id: str) -> None:
    with connect(path) as connection:
        connection.execute("DELETE FROM dividend_watchlist WHERE security_id=?", (security_id,))


def list_watchlist(path: Path, security_type: str):
    init_schema(path)
    with connect(path) as connection:
        return connection.execute("""SELECT s.* FROM dividend_watchlist w JOIN dividend_securities s ON s.security_id=w.security_id
            WHERE s.security_type=? ORDER BY COALESCE(w.sort_order, 2147483647), w.added_at""", (security_type,)).fetchall()


def search(path: Path, security_type: str, query: str):
    init_schema(path)
    term = f"%{query.strip().lower()}%"
    with connect(path) as connection:
        return connection.execute("""SELECT * FROM dividend_securities WHERE security_type=? AND active=1
            AND (lower(code) LIKE ? OR lower(name) LIKE ? OR lower(aliases) LIKE ?) ORDER BY code LIMIT 20""", (security_type, term, term, term)).fetchall()


def persist_snapshot(path: Path, security_id: str, quotes, dividends) -> None:
    init_schema(path)
    with connect(path) as connection:
        for _, trade_date, price in quotes:
            connection.execute("INSERT OR REPLACE INTO dividend_quotes(security_id,trade_date,price,source_id) VALUES (?,?,?,?)", (security_id, trade_date.isoformat(), str(price), 'akshare'))
        for row in dividends:
            event_id = row['event_id']
            connection.execute("""INSERT INTO dividend_events(event_id,security_id,fiscal_year,ex_date,amount_per_unit,state,current_revision_id)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET fiscal_year=excluded.fiscal_year,ex_date=excluded.ex_date,amount_per_unit=excluded.amount_per_unit,state=excluded.state""", (event_id, security_id, row.get('fiscal_year'), row['ex_date'].isoformat(), str(row['amount_per_unit']), row['status'], event_id + ':r1'))
            connection.execute("""INSERT OR IGNORE INTO dividend_revisions(revision_id,event_id,disclosed_at,known_at,raw_amount,raw_unit,status)
                VALUES (?,?,?,?,?,?,?)""", (event_id + ':r1', event_id, row.get('announced_at').isoformat() if row.get('announced_at') else None, row.get('announced_at').isoformat() if row.get('announced_at') else None, str(row.get('raw_amount')), row.get('raw_unit'), row['status']))


def record_candidate_snapshot(path: Path, security_id: str, snapshot: dict) -> str:
    """Keep a normalized provider candidate for audit without promoting facts."""
    init_schema(path)
    payload = json.dumps({'security_id': security_id, 'snapshot': snapshot},
                         ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    with connect(path) as connection:
        connection.execute("INSERT OR IGNORE INTO raw_source_records(payload,sha256) VALUES (?,?)",
                           (payload, digest))
    return digest
