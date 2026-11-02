"""Additive SQLite boundary. Callers own connections returned by open()."""

from contextlib import closing
from pathlib import Path
import sqlite3

from .config import ETF_UNIVERSE

SCHEMA = """
CREATE TABLE IF NOT EXISTS fund_master (
    etf_code TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    fund_group TEXT NOT NULL CHECK (fund_group IN ('core', 'extended'))
);
CREATE TABLE IF NOT EXISTS fund_flow_data_sources (
    source_id TEXT PRIMARY KEY NOT NULL,
    url TEXT,
    retrieved_at TEXT,
    checksum TEXT,
    field_mapping TEXT,
    request_params TEXT,
    row_count INTEGER,
    error_message TEXT
);
CREATE TABLE IF NOT EXISTS fund_flow_import_jobs (
    import_batch_id TEXT PRIMARY KEY NOT NULL,
    source_id TEXT NOT NULL REFERENCES fund_flow_data_sources(source_id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    started_at TEXT,
    finished_at TEXT,
    error_message TEXT
);
CREATE TABLE IF NOT EXISTS fund_flow_etf_daily_raw (
    etf_code TEXT NOT NULL REFERENCES fund_master(etf_code),
    record_date TEXT NOT NULL,
    effective_trade_date TEXT NOT NULL,
    published_at TEXT,
    total_share REAL,
    share_unit TEXT NOT NULL,
    share_scope TEXT NOT NULL,
    share_date_basis TEXT NOT NULL,
    nav REAL,
    close REAL,
    total_size REAL,
    source_id TEXT NOT NULL REFERENCES fund_flow_data_sources(source_id),
    source_version TEXT NOT NULL,
    import_batch_id TEXT NOT NULL REFERENCES fund_flow_import_jobs(import_batch_id),
    PRIMARY KEY (etf_code, record_date, share_scope, source_id, source_version, import_batch_id)
);
CREATE TABLE IF NOT EXISTS fund_flow_nav_daily_raw (
    etf_code TEXT NOT NULL REFERENCES fund_master(etf_code),
    nav_date TEXT NOT NULL,
    nav REAL NOT NULL CHECK (nav >= 0),
    cumulative_nav REAL CHECK (cumulative_nav >= 0),
    unit TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES fund_flow_data_sources(source_id),
    source_version TEXT NOT NULL,
    PRIMARY KEY (etf_code, nav_date, source_id, source_version)
);
CREATE TABLE IF NOT EXISTS fund_flow_index_daily_raw (
    index_code TEXT NOT NULL,
    record_date TEXT NOT NULL,
    effective_trade_date TEXT NOT NULL,
    published_at TEXT,
    close REAL,
    source_id TEXT NOT NULL REFERENCES fund_flow_data_sources(source_id),
    source_version TEXT NOT NULL,
    import_batch_id TEXT NOT NULL REFERENCES fund_flow_import_jobs(import_batch_id),
    PRIMARY KEY (index_code, record_date, source_id, source_version, import_batch_id)
);
CREATE TABLE IF NOT EXISTS fund_flow_corporate_actions (
    etf_code TEXT NOT NULL REFERENCES fund_master(etf_code),
    ex_date TEXT NOT NULL,
    action_type TEXT NOT NULL,
    event_date TEXT,
    ratio REAL CHECK (ratio > 0),
    first_post_record_date TEXT,
    status TEXT NOT NULL DEFAULT 'discovered'
        CHECK (status IN ('discovered', 'source_verified', 'basis_verified', 'applied', 'rejected')),
    value REAL,
    source_id TEXT REFERENCES fund_flow_data_sources(source_id),
    PRIMARY KEY (etf_code, ex_date, action_type)
);
CREATE TABLE IF NOT EXISTS fund_flow_etf_daily_clean (
    etf_code TEXT NOT NULL REFERENCES fund_master(etf_code),
    trade_date TEXT NOT NULL,
    shares_wan REAL CHECK (shares_wan >= 0),
    nav REAL CHECK (nav >= 0),
    size_yi REAL CHECK (size_yi >= 0),
    share_scope TEXT NOT NULL,
    validation_status TEXT NOT NULL CHECK (validation_status IN ('PASS', 'WARNING', 'BLOCKED')),
    error_codes TEXT NOT NULL DEFAULT '[]',
    source_id TEXT NOT NULL REFERENCES fund_flow_data_sources(source_id),
    PRIMARY KEY (etf_code, trade_date, share_scope)
);
CREATE TABLE IF NOT EXISTS fund_flow_etf_daily_metrics (
    etf_code TEXT NOT NULL REFERENCES fund_master(etf_code),
    trade_date TEXT NOT NULL,
    shares_adj_wan REAL CHECK (shares_adj_wan >= 0),
    nav_adj REAL CHECK (nav_adj >= 0),
    delta_shares_wan REAL,
    net_flow_yi REAL,
    cum_flow_yi REAL,
    intensity_pct REAL,
    calc_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PASS', 'WARNING', 'BLOCKED', 'INCOMPLETE')),
    PRIMARY KEY (etf_code, trade_date, calc_version)
);
"""


def open_fund_flow_connection(path: Path) -> sqlite3.Connection:
    """Open the shared file with FK enforcement; the caller must close it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_fund_flow_schema(path: Path) -> None:
    """Create only missing tables in a transaction, preserving existing data."""
    with closing(open_fund_flow_connection(path)) as connection:
        with connection:
            connection.executescript("BEGIN;\n" + SCHEMA)


def seed_default_fund_master(path: Path) -> None:
    """Insert missing defaults without overwriting locally maintained metadata."""
    init_fund_flow_schema(path)
    with closing(open_fund_flow_connection(path)) as connection:
        with connection:
            connection.executemany(
                """INSERT INTO fund_master(etf_code, name, fund_group)
                   VALUES (?, ?, ?) ON CONFLICT(etf_code) DO NOTHING""",
                [(code, fund["name"], fund["group"]) for code, fund in ETF_UNIVERSE.items()],
            )
