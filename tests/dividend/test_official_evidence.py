import json
import shutil

import pytest

from scripts.config import ROOT
from scripts.dividend.db import connect
from scripts.dividend.official_evidence import ingest_510880_notice, ingest_600519_notice
from scripts.dividend.db import upsert_security
from scripts.dividend.service import yield_detail


def test_510880_pdf_fields_hash_and_revision_are_idempotent(tmp_path):
    source = ROOT / 'data' / 'raw' / 'dividend'
    db = tmp_path / 'evidence.sqlite'
    first = ingest_510880_notice(db, source)
    second = ingest_510880_notice(db, source)
    assert first == second
    assert first['amount_per_unit'] == '0.14300'
    with connect(db) as connection:
        assert connection.execute('SELECT COUNT(*) FROM dividend_events').fetchone()[0] == 1
        assert connection.execute('SELECT COUNT(*) FROM dividend_revisions').fetchone()[0] == 1
        assert connection.execute("SELECT verification_level FROM source_documents").fetchone()[0] == 'OFFICIAL_VERIFIED'


def test_tampered_manifest_cannot_promote_pdf(tmp_path):
    source = ROOT / 'data' / 'raw' / 'dividend'
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    shutil.copy2(source / '510880_20260116_DSHH.pdf', evidence)
    manifest = json.loads((source / 'evidence_manifest.json').read_text(encoding='utf-8'))
    manifest['records'][0]['fields']['raw_amount'] = '9.9999'
    (evidence / 'evidence_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ValueError, match='amount or unit'):
        ingest_510880_notice(tmp_path / 'never.sqlite', evidence)


def test_ttm_requires_verified_quote_and_full_coverage_certificate(tmp_path):
    source = ROOT / 'data' / 'raw' / 'dividend'
    db = tmp_path / 'yield.sqlite'
    upsert_security(db, {'security_id': 'ETF:510880', 'code': '510880', 'name': '红利ETF',
                         'market': 'SH', 'security_type': 'ETF', 'aliases': ''})
    evidence = ingest_510880_notice(db, source)
    with connect(db) as connection:
        connection.execute("INSERT INTO dividend_quotes(security_id,trade_date,price,source_id) VALUES (?,?,?,?)",
                           ('ETF:510880', '2026-10-23', '2.00', 'fixture'))
    assert yield_detail(db, 'ETF:510880')['ttm']['value_pct'] is None
    with connect(db) as connection:
        connection.execute("UPDATE dividend_quotes SET verification_level='VERIFIED_UNADJUSTED'")
    assert yield_detail(db, 'ETF:510880')['ttm']['value_pct'] is None
    with connect(db) as connection:
        connection.execute("""INSERT INTO dividend_coverage
            (security_id,start_date,end_date,evidence_sha256,verified_at,dividends_complete,actions_verified)
            VALUES (?,?,?,?,?,?,?)""",
                           ('ETF:510880', '2025-10-23', '2026-10-23', evidence['source_sha256'],
                            '2026-10-24', 1, 1))
    detail = yield_detail(db, 'ETF:510880')
    assert detail['ttm']['value_pct'] == '7.1500'
    assert detail['annual_reference']['value_pct'] is None
    with connect(db) as connection:
        connection.execute('''INSERT INTO dividend_corporate_actions
            (action_id,security_id,effective_date,ratio,action_type)
            VALUES (?,?,?,?,?)''', ('split', 'ETF:510880', '2026-06-01', '2', 'SPLIT'))
    blocked = yield_detail(db, 'ETF:510880')['ttm']
    assert blocked['value_pct'] is None
    assert '权益变动' in blocked['reason']


def test_600519_cninfo_notice_is_verified_and_idempotent(tmp_path):
    source = ROOT / 'data' / 'raw' / 'dividend'
    db = tmp_path / 'stock.sqlite'
    first = ingest_600519_notice(db, source)
    assert first == ingest_600519_notice(db, source)
    assert first['amount_per_unit'] == '28.02423'
    with connect(db) as connection:
        row = connection.execute('''SELECT e.fiscal_year,e.ex_date,r.raw_unit,d.verification_level,d.url
            FROM dividend_events e JOIN dividend_revisions r ON r.revision_id=e.current_revision_id
            JOIN source_documents d ON d.id=r.source_document_id''').fetchone()
        assert (row['fiscal_year'], row['ex_date'], row['raw_unit'], row['verification_level']) == (
            2025, '2026-06-26', 'PER_UNIT', 'OFFICIAL_VERIFIED')
        assert row['url'].startswith('https://static.cninfo.com.cn/')
        assert connection.execute('SELECT COUNT(*) FROM dividend_revisions').fetchone()[0] == 1


def test_600519_two_official_notices_remain_distinct(tmp_path):
    source = ROOT / 'data' / 'raw' / 'dividend'
    db = tmp_path / 'stock.sqlite'
    interim = ingest_600519_notice(db, source, '2025-12-11')
    annual = ingest_600519_notice(db, source)
    assert interim == ingest_600519_notice(db, source, '2025-12-11')
    assert interim['amount_per_unit'] == '23.95700'
    assert interim['event_id'] == 'STOCK:600519:2025-12-19'
    assert interim['source_sha256'] != annual['source_sha256']
    with connect(db) as connection:
        assert connection.execute('SELECT COUNT(*) FROM dividend_events').fetchone()[0] == 2
        assert connection.execute('SELECT COUNT(*) FROM dividend_revisions').fetchone()[0] == 2


def test_600519_tampered_interim_amount_is_rejected(tmp_path):
    source = ROOT / 'data' / 'raw' / 'dividend'
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    shutil.copy2(source / '600519_20251211_CNINFO.pdf', evidence)
    manifest = json.loads((source / 'evidence_manifest.json').read_text(encoding='utf-8'))
    interim = next(r for r in manifest['records'] if r['source_id'].endswith('2025-12-11:053'))
    interim['fields']['amount_per_share'] = '99.999'
    (evidence / 'evidence_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ValueError, match='cash amount'):
        ingest_600519_notice(tmp_path / 'never.sqlite', evidence, '2025-12-11')
