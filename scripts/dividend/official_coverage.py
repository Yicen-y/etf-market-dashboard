"""Auditable, narrowly scoped CNINFO coverage proof for 600519's 2026-11-06 TTM."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import requests
from pypdf import PdfReader

from .db import connect, init_schema


CATALOG_URL = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
START, END = '2025-11-06', '2026-11-06'
RELEVANT = {
    '1225379934': '贵州茅台2025年年度权益分派实施公告',
    '1225347653': '贵州茅台关于调整2025年年度利润分配方案每股分红金额的公告',
    '1225333825': '贵州茅台关于回购股份实施结果暨股份变动的公告',
    '1225114720': '贵州茅台关于2025年年度利润分配方案及2026年中期利润分配安排的公告',
    '1224896531': '贵州茅台关于实施2025年中期权益分派后调整回购股份价格上限的公告',
    '1224867074': '贵州茅台2025年中期权益分派实施公告',
    '1224789659': '贵州茅台关于2025年中期利润分配方案暨贯彻落实“提质增效重回报”专项行动方案的公告',
}
RELEVANT_WORDS = ('分红', '分派', '分配', '送转', '股本', '拆股', '股份变动',
                  '配股', '增发', '股权激励', '资本公积')
PDF_HASHES = {
    '1225379934': '6b082b6a00db748f23b6dea166b0296cd69d8c10542d352e23d2e2c344ea516e',
    '1224867074': 'ad2f4548490a203bbcada1181341d9dc90b19a64a0ecf14ff1c8e6b9d4b71673',
    '1225347653': 'f51131858f82005c9ed36dcb78ecca961f3f10cff71dc54039c4a37804ed5412',
    '1225333825': 'c3d2cf8322ad4b8d8b69c914a0afd265bf0f85cdaa1f023d00109caa0a9721c1',
}


def fetch_cninfo_catalog(*, session=None) -> tuple[list[dict], int]:
    http = session or requests.Session()
    if session is None:
        http.trust_env = False
    rows, total = [], None
    for page in range(1, 21):
        response = http.post(CATALOG_URL, data={
            'tabName': 'fulltext', 'pageSize': 30, 'pageNum': page,
            'column': 'sse', 'seDate': f'{START}~{END}', 'searchkey': '贵州茅台',
        }, timeout=25)
        response.raise_for_status()
        payload = response.json()
        page_total = payload.get('totalAnnouncement')
        batch = payload.get('announcements')
        if not isinstance(page_total, int) or not isinstance(batch, list) or page_total <= 0:
            raise ValueError('CNINFO公告目录响应不完整')
        if total is not None and page_total != total:
            raise ValueError('CNINFO公告目录分页总数变化')
        total = page_total
        rows.extend(batch)
        if len(rows) >= total:
            break
        if not batch:
            raise ValueError('CNINFO公告目录提前出现空页')
    if len(rows) != total:
        raise ValueError('CNINFO公告目录未取齐全部分页')
    return rows, total


def validate_catalog(rows: list[dict], total: int) -> dict[str, dict]:
    if len(rows) != total or total <= 0:
        raise ValueError('公告目录条数与分页总数不一致')
    by_id = {}
    for row in rows:
        identifier = str(row.get('announcementId', ''))
        title = row.get('announcementTitle')
        url = row.get('adjunctUrl')
        timestamp = row.get('announcementTime')
        if (not re.fullmatch(r'\d+', identifier) or identifier in by_id
                or row.get('secCode') != '600519' or not isinstance(title, str)
                or not re.fullmatch(r'finalpage/\d{4}-\d{2}-\d{2}/\d+\.PDF', str(url))
                or not isinstance(timestamp, int)):
            raise ValueError('CNINFO公告目录存在混入、重复或无效记录')
        day = datetime.fromtimestamp(timestamp / 1000, tz=timezone(timedelta(hours=8))).date().isoformat()
        if not START <= day <= END:
            raise ValueError('CNINFO公告日期超出核验窗口')
        by_id[identifier] = row
    actual = {key: row['announcementTitle'] for key, row in by_id.items()
              if any(word in row['announcementTitle'] for word in RELEVANT_WORDS)}
    if actual != RELEVANT:
        raise ValueError('出现未核验分红或权益变动公告，不能签发覆盖证明')
    return by_id


def _verified_pdf(path: Path, expected_hash: str) -> str:
    payload = path.read_bytes()
    if not payload.startswith(b'%PDF-') or hashlib.sha256(payload).hexdigest() != expected_hash:
        raise ValueError(f'官方PDF缺失或SHA-256不一致: {path.name}')
    return re.sub(r'\s+', '', ''.join(page.extract_text() or '' for page in PdfReader(path).pages))


def certify_600519_ttm(path: Path, evidence_root: Path, catalog_rows: list[dict],
                       catalog_total: int) -> dict:
    """Certify exactly one observed TTM window after checking archive and four original PDFs."""
    by_id = validate_catalog(catalog_rows, catalog_total)
    pdf_paths = {
        '1225379934': evidence_root / '600519_20260622_CNINFO.pdf',
        '1224867074': evidence_root / '600519_20251211_CNINFO.pdf',
        '1225347653': evidence_root / 'official_catalog' / '1225347653.pdf',
        '1225333825': evidence_root / 'official_catalog' / '1225333825.pdf',
    }
    texts = {key: _verified_pdf(pdf_paths[key], digest) for key, digest in PDF_HASHES.items()}
    adjustment = texts['1225347653']
    buyback = texts['1225333825']
    if ('由27.993元（含税）调整为28.02423元' not in adjustment
            or '2,188,614股' not in adjustment or '1,250,081,601股' not in adjustment
            or '2026年5月28日' not in adjustment):
        raise ValueError('每股金额调整公告未通过原文核对')
    if ('√减少注册资本' not in buyback or '全部用于注销并减少公司注册资本' not in buyback
            or '2,188,614股' not in buyback or '1,250,081,601' not in buyback):
        raise ValueError('回购注销公告未通过原文核对')
    for key in PDF_HASHES:
        expected_url = f'finalpage/{"2026-06-22" if key=="1225379934" else "2025-12-11" if key=="1224867074" else "2026-06-03" if key=="1225347653" else "2026-05-28"}/{key}.PDF'
        if by_id[key]['adjunctUrl'] != expected_url:
            raise ValueError('官方目录链接与本地PDF不符')
    normalized = {'provider': 'CNINFO', 'query': {'security_id': 'STOCK:600519',
        'start_date': START, 'end_date': END, 'searchkey': '贵州茅台'},
        'totalAnnouncement': catalog_total, 'announcements': sorted(({
            'announcementId': key, 'announcementTitle': row['announcementTitle'],
            'announcementTime': row['announcementTime'], 'adjunctUrl': row['adjunctUrl']}
            for key, row in by_id.items()), key=lambda row: row['announcementId']),
        'verified_pdf_sha256': PDF_HASHES}
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    init_schema(path)
    checked_at = datetime.now(timezone.utc).isoformat()
    with connect(path) as db:
        official = {}
        for day, key, amount in [('2025-12-19', '1224867074', '23.95700'),
                                 ('2026-06-26', '1225379934', '28.02423')]:
            event = db.execute('''SELECT e.event_id,e.current_revision_id,e.amount_per_unit,
                e.state,r.source_document_id,d.sha256,d.verification_level,d.url
                FROM dividend_events e JOIN dividend_revisions r ON r.revision_id=e.current_revision_id
                JOIN source_documents d ON d.id=r.source_document_id
                WHERE e.event_id=?''', (f'STOCK:600519:{day}',)).fetchone()
            if (event is None or event['state'] != 'PAID' or Decimal(event['amount_per_unit']) != Decimal(amount)
                    or event['sha256'] != PDF_HASHES[key] or event['verification_level'] != 'OFFICIAL_VERIFIED'
                    or event['url'] != 'https://static.cninfo.com.cn/' + by_id[key]['adjunctUrl']):
                raise ValueError('正式分红事件与官方公告不一致')
            official[day] = event
        candidates = db.execute('''SELECT e.event_id,e.ex_date,e.amount_per_unit,e.current_revision_id,
            r.source_document_id FROM dividend_events e JOIN dividend_revisions r
            ON r.revision_id=e.current_revision_id WHERE e.security_id='STOCK:600519'
            AND e.ex_date>? AND e.ex_date<=? AND e.event_id NOT IN (?,?)''',
            (START, END, official['2025-12-19']['event_id'], official['2026-06-26']['event_id'])).fetchall()
        for row in candidates:
            match = official.get(row['ex_date'])
            if (match is None or row['source_document_id'] is not None
                    or abs(Decimal(row['amount_per_unit']) - Decimal(match['amount_per_unit'])) > Decimal('0.00005')):
                raise ValueError('存在无法与官方公告对账的旧候选事件')
        db.execute('INSERT OR IGNORE INTO raw_source_records(payload,sha256) VALUES (?,?)', (payload, digest))
        document_id = db.execute('''INSERT INTO source_documents
            (source_id,title,publisher,url,sha256,published_at,parser_version,verification_level)
            VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(sha256) DO UPDATE SET sha256=excluded.sha256
            RETURNING id''', ('cninfo:600519:archive:2025-11-06:2026-11-06',
            '贵州茅台公告目录完整分页核验', '巨潮资讯网', CATALOG_URL, digest,
            END, 'cninfo-catalog-audit-v1', 'OFFICIAL_VERIFIED')).fetchone()[0]
        buyback_id = db.execute('''INSERT INTO source_documents
            (source_id,title,publisher,url,sha256,published_at,parser_version,verification_level)
            VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(sha256) DO UPDATE SET sha256=excluded.sha256
            RETURNING id''', ('cninfo:600519:2026-05-28:021', RELEVANT['1225333825'],
            '贵州茅台 / 巨潮资讯网', 'https://static.cninfo.com.cn/'+by_id['1225333825']['adjunctUrl'],
            PDF_HASHES['1225333825'], '2026-05-28', 'pdf-field-match-v1', 'OFFICIAL_VERIFIED')).fetchone()[0]
        db.execute('''INSERT INTO dividend_corporate_actions
            (action_id,security_id,effective_date,ratio,action_type,source_document_id)
            VALUES (?,?,?,?,?,?) ON CONFLICT(action_id) DO UPDATE SET source_document_id=excluded.source_document_id''',
            ('STOCK:600519:2026-05-28:buyback-cancellation', 'STOCK:600519', '2026-05-28',
             '1', 'BUYBACK_CANCELLATION', buyback_id))
        for row in candidates:
            target = official[row['ex_date']]
            db.execute('''INSERT INTO dividend_event_reconciliations
                (candidate_event_id,official_event_id,candidate_revision_id,official_revision_id,
                 evidence_sha256,checked_at,amount_difference) VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(candidate_event_id) DO UPDATE SET
                official_event_id=excluded.official_event_id,
                candidate_revision_id=excluded.candidate_revision_id,
                official_revision_id=excluded.official_revision_id,
                evidence_sha256=excluded.evidence_sha256,checked_at=excluded.checked_at,
                amount_difference=excluded.amount_difference''',
                (row['event_id'], target['event_id'], row['current_revision_id'],
                 target['current_revision_id'], digest, checked_at,
                 str(Decimal(row['amount_per_unit'])-Decimal(target['amount_per_unit']))))
        db.execute('''INSERT INTO dividend_coverage
            (security_id,start_date,end_date,evidence_sha256,verified_at,dividends_complete,
             actions_verified,quote_calendar_verified,query_mode) VALUES (?,?,?,?,?,1,1,0,'latest_verified')
            ON CONFLICT(security_id,start_date,end_date,evidence_sha256)
            DO UPDATE SET verified_at=excluded.verified_at''',
            ('STOCK:600519', START, END, digest, checked_at))
    return {'security_id': 'STOCK:600519', 'start_date': START, 'end_date': END,
            'catalog_count': catalog_total, 'official_event_count': 2,
            'reconciled_candidate_count': len(candidates), 'catalog_sha256': digest,
            'buyback_per_share_ratio': '1', 'status': 'COVERAGE_CERTIFIED'}


if __name__ == '__main__':
    from scripts.config import DATABASE_PATH, ROOT
    rows, total = fetch_cninfo_catalog()
    print(json.dumps(certify_600519_ttm(DATABASE_PATH, ROOT / 'data' / 'raw' / 'dividend', rows, total),
                     ensure_ascii=False))
