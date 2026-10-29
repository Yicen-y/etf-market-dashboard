import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS etf_prices (
    trade_date TEXT NOT NULL,
    product_code TEXT NOT NULL,
    close_price REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'akshare',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (trade_date, product_code)
);
CREATE INDEX IF NOT EXISTS idx_etf_prices_code_date
ON etf_prices(product_code, trade_date);
CREATE TABLE IF NOT EXISTS index_prices (
    trade_date TEXT NOT NULL,
    index_code TEXT NOT NULL,
    close_value REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'akshare',
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


def upsert_records(path: Path, records: list[dict], updated_at: str) -> None:
    init_database(path)
    with sqlite3.connect(path) as connection:
        connection.executemany(
            """INSERT INTO etf_prices(trade_date, product_code, close_price, source, updated_at)
               VALUES (?, ?, ?, 'akshare', ?)
               ON CONFLICT(trade_date, product_code) DO UPDATE SET
                 close_price=excluded.close_price,
                 source=excluded.source,
                 updated_at=excluded.updated_at""",
            [(r["tradeDate"], r["productCode"], r["closePrice"], updated_at) for r in records],
        )


def read_records(path: Path) -> list[dict]:
    init_database(path)
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT trade_date, product_code, close_price FROM etf_prices ORDER BY trade_date, product_code"
        ).fetchall()
    return [{"tradeDate": d, "productCode": c, "closePrice": float(p)} for d, c, p in rows]


def upsert_index_records(path: Path, records: list[dict], updated_at: str) -> None:
    init_database(path)
    with sqlite3.connect(path) as connection:
        connection.executemany(
            """INSERT INTO index_prices(trade_date, index_code, close_value, source, updated_at)
               VALUES (?, ?, ?, 'akshare', ?)
               ON CONFLICT(trade_date, index_code) DO UPDATE SET
                 close_value=excluded.close_value, source=excluded.source, updated_at=excluded.updated_at""",
            [(r["tradeDate"], r["indexCode"], r["closeValue"], updated_at) for r in records],
        )


def read_index_records(path: Path) -> list[dict]:
    init_database(path)
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT trade_date, index_code, close_value FROM index_prices ORDER BY trade_date, index_code").fetchall()
    return [{"tradeDate": d, "indexCode": c, "closeValue": float(v)} for d, c, v in rows]
