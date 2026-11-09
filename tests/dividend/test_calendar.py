from datetime import date

from scripts.dividend.db import add_watchlist, connect, init_schema, upsert_security
from scripts.dividend.service import calendar_detail


def test_existing_source_document_schema_migrates_without_promoting_evidence(tmp_path):
    import sqlite3
    path = tmp_path / 'legacy.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE source_documents (id INTEGER PRIMARY KEY, source_id TEXT, title TEXT, publisher TEXT, url TEXT, sha256 TEXT UNIQUE, published_at TEXT, parser_version TEXT)')
        db.execute("INSERT INTO source_documents(source_id,sha256) VALUES ('old','hash')")
    init_schema(path)
    with connect(path) as db:
        assert db.execute("SELECT verification_level FROM source_documents WHERE sha256='hash'").fetchone()[0] == 'UNVERIFIED'


def test_calendar_only_exposes_verified_confirmed_watchlist_event_within_90_days(tmp_path):
    path = tmp_path / 'calendar.sqlite'
    init_schema(path)
    for code, kind in [('510880', 'ETF'), ('600519', 'STOCK')]:
        upsert_security(path, {'security_id': f'{kind}:{code}', 'code': code, 'name': code,
                               'market': 'SH', 'security_type': kind, 'aliases': ''})
        add_watchlist(path, f'{kind}:{code}')
    with connect(path) as db:
        for index, (day, state, level, security_id) in enumerate([
            ('2026-11-09', 'CONFIRMED', 'OFFICIAL_VERIFIED', 'ETF:510880'),
            ('2026-11-10', 'PROPOSAL', 'OFFICIAL_VERIFIED', 'ETF:510880'),
            ('2026-11-11', 'CONFIRMED', 'UNVERIFIED', 'ETF:510880'),
            ('2027-02-07', 'CONFIRMED', 'OFFICIAL_VERIFIED', 'ETF:510880'),
            ('2026-11-12', 'CONFIRMED', 'OFFICIAL_VERIFIED', 'STOCK:600519'),
        ]):
            doc = db.execute('INSERT INTO source_documents(source_id,title,publisher,url,sha256,verification_level) VALUES (?,?,?,?,?,?)',
                             (f'd{index}', 'fixture', 'official', f'https://example.test/{index}', f'h{index}', level)).lastrowid
            event_id = f'e{index}'
            db.execute('INSERT INTO dividend_events VALUES (?,?,?,?,?,?,?)',
                       (event_id, security_id, 2026, day, '0.1', state, f'r{index}'))
            db.execute('''INSERT INTO dividend_revisions
                (revision_id,event_id,disclosed_at,known_at,raw_amount,raw_unit,status,source_document_id)
                VALUES (?,?,?,?,?,?,?,?)''',
                       (f'r{index}', event_id, '2026-11-01', '2026-11-01', '0.1', 'PER_UNIT', state, doc))
    result = calendar_detail(path, 'ETF', 90, date(2026, 11, 8))
    assert [item['event_id'] for item in result['items']] == ['e0']
    assert result['status'] == 'READY'
