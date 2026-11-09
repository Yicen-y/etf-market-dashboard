"""Conservative importer for an already downloaded issuer/venue PDF."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from .db import connect, init_schema
from .domain import normalize_cash_amount


def ingest_510880_notice(path: Path, evidence_root: Path) -> dict:
    manifest = json.loads((evidence_root / 'evidence_manifest.json').read_text(encoding='utf-8'))
    records = [r for r in manifest['records'] if r['security_id'] == 'ETF:510880']
    if len(records) != 1:
        raise ValueError('510880 official evidence record is missing or ambiguous')
    record = records[0]
    if record['verification_status'] != 'official_source_downloaded' or not record['url'].startswith('https://www.sse.com.cn/'):
        raise ValueError('evidence is not the downloaded SSE notice')
    pdf = evidence_root / record['local_file']
    if pdf.resolve().parent != evidence_root.resolve():
        raise ValueError('invalid evidence path')
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if digest != record['sha256']:
        raise ValueError('official PDF SHA-256 mismatch')
    fields = record['fields']
    text = re.sub(r'\s+', '', ''.join(page.extract_text() or '' for page in PdfReader(pdf).pages))
    if '基金主代码510880' not in text or '分红公告' not in text:
        raise ValueError('PDF fund identity does not match')
    if fields['raw_unit'] != 'PER_10' or f"本次分红方案（单位：元/10份基金份额）{fields['raw_amount']}" not in text:
        raise ValueError('PDF distribution amount or unit does not match')
    for label, key in [('公告送出日期：', 'published_at'), ('权益登记日', 'record_date'), ('除息日', 'ex_date')]:
        day = date.fromisoformat(fields[key])
        if f'{label}{day.year}年{day.month}月{day.day}日' not in text:
            raise ValueError(f'PDF {key} does not match')
    amount = normalize_cash_amount(Decimal(fields['raw_amount']), fields['raw_unit'])
    event_id = f"ETF:510880:{fields['ex_date']}"
    revision_id = event_id + ':sse-' + digest[:12]
    state = 'PAID' if date.fromisoformat(fields['ex_date']) <= date.today() else 'CONFIRMED'
    init_schema(path)
    with connect(path) as db:
        doc = db.execute('SELECT id FROM source_documents WHERE sha256=?', (digest,)).fetchone()
        if doc:
            document_id = doc['id']
        else:
            document_id = db.execute('''INSERT INTO source_documents
                (source_id,title,publisher,url,sha256,published_at,parser_version,verification_level)
                VALUES (?,?,?,?,?,?,?,?)''',
                (record['source_id'], '上证红利ETF分红公告', record['publisher'], record['url'], digest,
                 fields['published_at'], 'pdf-field-match-v1', 'OFFICIAL_VERIFIED')).lastrowid
        db.execute('''INSERT INTO dividend_events
            (event_id,security_id,fiscal_year,ex_date,amount_per_unit,state,current_revision_id)
            VALUES (?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET
            ex_date=excluded.ex_date,amount_per_unit=excluded.amount_per_unit,
            state=excluded.state,current_revision_id=excluded.current_revision_id''',
            (event_id, 'ETF:510880', None, fields['ex_date'], str(amount), state, revision_id))
        db.execute('''INSERT OR IGNORE INTO dividend_revisions
            (revision_id,event_id,disclosed_at,known_at,raw_amount,raw_unit,status,source_document_id,ex_date)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (revision_id, event_id, fields['published_at'], fields['published_at'],
             fields['raw_amount'], fields['raw_unit'], state, document_id, fields['ex_date']))
        db.execute('UPDATE dividend_revisions SET ex_date=? WHERE revision_id=? AND ex_date IS NULL',
                   (fields['ex_date'], revision_id))
    return {'event_id': event_id, 'revision_id': revision_id, 'source_sha256': digest,
            'amount_per_unit': str(amount), 'state': state}


def ingest_600519_notice(path: Path, evidence_root: Path, notice_date: str = '2026-06-22') -> dict:
    """Ingest the issuer's implementation notice downloaded from CNINFO."""
    manifest = json.loads((evidence_root / 'evidence_manifest.json').read_text(encoding='utf-8'))
    records = [r for r in manifest['records'] if r['security_id'] == 'STOCK:600519'
               and r['fields']['published_at'] == notice_date]
    if len(records) != 1:
        raise ValueError('600519 official evidence record is missing or ambiguous')
    record = records[0]
    if (record['verification_status'] != 'official_source_downloaded'
            or not record['url'].startswith('https://static.cninfo.com.cn/finalpage/')):
        raise ValueError('evidence is not the downloaded CNINFO notice')
    pdf = evidence_root / record['local_file']
    if pdf.resolve().parent != evidence_root.resolve():
        raise ValueError('invalid evidence path')
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if digest != record['sha256']:
        raise ValueError('official PDF SHA-256 mismatch')
    fields = record['fields']
    text = re.sub(r'\s+', '', ''.join(page.extract_text() or '' for page in PdfReader(pdf).pages))
    if ('证券代码：600519' not in text or '贵州茅台酒股份有限公司' not in text
            or '权益分派实施公告' not in text or fields['announcement_no'] not in text
            or fields['distribution_label'] not in text):
        raise ValueError('PDF security or notice identity does not match')
    if f"A股每股现金红利{fields['amount_per_share']}元" not in text:
        raise ValueError('PDF cash amount does not match')
    for key in ('record_date', 'ex_date'):
        day = date.fromisoformat(fields[key])
        if f'{day.year}/{day.month}/{day.day}' not in text:
            raise ValueError(f'PDF {key} does not match')
    if fields['total_amount'].replace(',', '') not in text.replace(',', ''):
        raise ValueError('PDF total amount does not match')
    if fields['published_at'] != notice_date:
        raise ValueError('manifest notice version does not match')
    published = date.fromisoformat(fields['published_at'])
    if f'{published.year}年{published.month}月{published.day}日' not in text:
        raise ValueError('PDF publication date does not match')
    fiscal_year = int(fields['fiscal_year'])
    if not 2000 <= fiscal_year <= published.year:
        raise ValueError('invalid fiscal year')
    amount = normalize_cash_amount(Decimal(fields['amount_per_share']), 'PER_UNIT')
    event_id = f"STOCK:600519:{fields['ex_date']}"
    revision_id = event_id + ':cninfo-' + digest[:12]
    state = 'PAID' if date.fromisoformat(fields['ex_date']) <= date.today() else 'CONFIRMED'
    init_schema(path)
    with connect(path) as db:
        doc = db.execute('SELECT id FROM source_documents WHERE sha256=?', (digest,)).fetchone()
        document_id = doc['id'] if doc else db.execute('''INSERT INTO source_documents
            (source_id,title,publisher,url,sha256,published_at,parser_version,verification_level)
            VALUES (?,?,?,?,?,?,?,?)''',
            (record['source_id'], '贵州茅台' + fields['distribution_label'] + '权益分派实施公告', record['publisher'],
             record['url'], digest, fields['published_at'], 'pdf-field-match-v1',
             'OFFICIAL_VERIFIED')).lastrowid
        db.execute('''INSERT INTO dividend_events
            (event_id,security_id,fiscal_year,ex_date,amount_per_unit,state,current_revision_id)
            VALUES (?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET
            ex_date=excluded.ex_date,amount_per_unit=excluded.amount_per_unit,
            state=excluded.state,current_revision_id=excluded.current_revision_id''',
            (event_id, 'STOCK:600519', fiscal_year, fields['ex_date'], str(amount), state, revision_id))
        db.execute('''INSERT OR IGNORE INTO dividend_revisions
            (revision_id,event_id,disclosed_at,known_at,raw_amount,raw_unit,status,
             source_document_id,ex_date,fiscal_year) VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (revision_id, event_id, fields['published_at'], fields['published_at'],
             fields['amount_per_share'], 'PER_UNIT', state, document_id, fields['ex_date'], fiscal_year))
    return {'event_id': event_id, 'revision_id': revision_id, 'source_sha256': digest,
            'amount_per_unit': str(amount), 'state': state}
