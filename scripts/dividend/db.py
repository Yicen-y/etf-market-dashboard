from __future__ import annotations

import sqlite3
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
CREATE TABLE IF NOT EXISTS dividend_events (
 event_id TEXT PRIMARY KEY, security_id TEXT NOT NULL, fiscal_year INTEGER, ex_date TEXT, amount_per_unit TEXT, state TEXT NOT NULL, current_revision_id TEXT
);
CREATE TABLE IF NOT EXISTS dividend_revisions (
 revision_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES dividend_events(event_id), disclosed_at TEXT, known_at TEXT, raw_amount TEXT, raw_unit TEXT, status TEXT NOT NULL, source_document_id TEXT
);
CREATE TABLE IF NOT EXISTS source_documents (
 id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL, title TEXT, publisher TEXT, url TEXT, sha256 TEXT NOT NULL UNIQUE, published_at TEXT, parser_version TEXT
);
CREATE TABLE IF NOT EXISTS raw_source_records (
 id INTEGER PRIMARY KEY AUTOINCREMENT, source_document_id INTEGER REFERENCES source_documents(id), observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, payload TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS dividend_corporate_actions (action_id TEXT PRIMARY KEY, security_id TEXT NOT NULL, effective_date TEXT NOT NULL, ratio TEXT NOT NULL, action_type TEXT NOT NULL, source_document_id INTEGER);
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
