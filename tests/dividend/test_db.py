import sqlite3

from scripts.dividend.db import add_watchlist, connect, init_schema, list_watchlist, upsert_security


def test_schema_is_additive_and_watchlist_is_idempotent(tmp_path):
    path = tmp_path / "dividend.db"
    init_schema(path)
    upsert_security(path, {"security_id": "ETF:510880", "code": "510880", "name": "红利ETF", "market": "SH", "security_type": "ETF", "aliases": "红利"})
    add_watchlist(path, "ETF:510880")
    add_watchlist(path, "ETF:510880")
    assert [row["security_id"] for row in list_watchlist(path, "ETF")] == ["ETF:510880"]


def test_source_documents_are_hash_deduplicated(tmp_path):
    path = tmp_path / "dividend.db"
    init_schema(path)
    with connect(path) as db:
        first = db.execute("INSERT INTO source_documents(source_id, title, url, sha256) VALUES (?,?,?,?)", ("s1", "公告", "https://example.test/a", "abc")).lastrowid
        db.commit()
        second = db.execute("SELECT id FROM source_documents WHERE sha256=?", ("abc",)).fetchone()[0]
    assert first == second


def test_init_schema_migrates_old_provider_yields_table(tmp_path):
    path = tmp_path / 'legacy-dividend.db'
    connection = sqlite3.connect(path)
    connection.execute('''CREATE TABLE dividend_provider_yields (
        security_id TEXT PRIMARY KEY,
        value_pct TEXT,
        as_of_date TEXT,
        fetched_at TEXT NOT NULL,
        provider TEXT NOT NULL,
        metric_label TEXT NOT NULL,
        source_sha256 TEXT,
        status TEXT NOT NULL,
        reason TEXT
    )''')
    connection.execute('''INSERT INTO dividend_provider_yields
        (security_id,value_pct,as_of_date,fetched_at,provider,metric_label,source_sha256,status,reason)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        ('STOCK:600519', '2.35', '2026-11-09', 'old', 'wind:mcp:stock_fundamentals',
         'Wind股息率（提供方口径）', 'hash', 'READY', None))
    connection.commit()
    connection.close()

    init_schema(path)

    with connect(path) as db:
        columns = {row['name'] for row in db.execute('PRAGMA table_info(dividend_provider_yields)')}
        row = db.execute('''SELECT value_pct,last_refresh_status,last_refresh_reason
            FROM dividend_provider_yields WHERE security_id=?''', ('STOCK:600519',)).fetchone()
        db.execute('''UPDATE dividend_provider_yields
            SET last_refresh_status=?,last_refresh_reason=? WHERE security_id=?''',
                   ('UNAVAILABLE', 'timeout', 'STOCK:600519'))
    assert {'last_refresh_status', 'last_refresh_reason'} <= columns
    assert row['value_pct'] == '2.35'
    with connect(path) as db:
        migrated = db.execute('''SELECT last_refresh_status,last_refresh_reason
            FROM dividend_provider_yields WHERE security_id=?''', ('STOCK:600519',)).fetchone()
    assert migrated['last_refresh_status'] == 'UNAVAILABLE'
    assert migrated['last_refresh_reason'] == 'timeout'
