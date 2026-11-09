"""Archive AkShare dividend announcements as candidates, never as verified events."""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from pypdf import PdfReader

from .db import record_candidate_snapshot
from .providers import _as_date


REPORT_ID = re.compile(r'^AN\d{18}$')
MAX_PDF_BYTES = 20_000_000


def normalize_etf_announcements(frame, security_id: str) -> list[dict]:
    required = {'基金代码', '公告标题', '公告日期', '报告ID'}
    if not required.issubset(frame.columns):
        raise ValueError(f'ETF公告目录字段不完整: {sorted(required - set(frame.columns))}')
    code = security_id.partition(':')[2]
    if not security_id.startswith('ETF:') or len(code) != 6 or not code.isdigit():
        raise ValueError('invalid ETF security ID')
    result = {}
    for _, row in frame.iterrows():
        if str(row['基金代码']) != code:
            raise ValueError('ETF公告目录混入其他基金代码')
        report_id = str(row['报告ID']).strip()
        title = str(row['公告标题']).strip()
        day = _as_date(row['公告日期'])
        if not REPORT_ID.fullmatch(report_id) or not title or day is None:
            raise ValueError('ETF公告目录存在无效报告ID、标题或日期')
        candidate = {
            'security_id': security_id, 'report_id': report_id,
            'title': title, 'announced_at': day.isoformat(),
            'source_id': 'akshare:eastmoney:fund_announcement_dividend_em',
            'archive_url': f'https://pdf.dfcfw.com/pdf/H2_{report_id}_1.pdf',
            'verification_level': 'UNVERIFIED',
        }
        if report_id in result and result[report_id] != candidate:
            raise ValueError('同一报告ID对应不同公告')
        result[report_id] = candidate
    return sorted(result.values(), key=lambda row: (row['announced_at'], row['report_id']))


def normalize_stock_dividends(frame, security_id: str) -> list[dict]:
    required = {'实施方案公告日期', '派息比例', '除权日', '实施方案分红说明', '报告时间'}
    if not required.issubset(frame.columns):
        raise ValueError(f'股票分红记录字段不完整: {sorted(required - set(frame.columns))}')
    if not re.fullmatch(r'STOCK:\d{6}', security_id):
        raise ValueError('invalid stock security ID')
    result = []
    for _, row in frame.iterrows():
        amount = row['派息比例']
        if amount != amount:
            continue
        announced = _as_date(row['实施方案公告日期'])
        ex_date = _as_date(row['除权日'])
        if not announced or not ex_date:
            continue
        result.append({
            'security_id': security_id, 'announced_at': announced.isoformat(),
            'ex_date': ex_date.isoformat(), 'raw_cash_per_10': str(amount),
            'raw_description': str(row['实施方案分红说明']),
            'report_period': str(row['报告时间']),
            'source_id': 'akshare:cninfo:stock_dividend_cninfo',
            'source_document_url': None, 'verification_level': 'UNVERIFIED',
        })
    return sorted(result, key=lambda row: (row['ex_date'], row['announced_at']))


def fetch_candidates(security_id: str) -> list[dict]:
    import akshare as ak

    if os.getenv('ETF_DIRECT') == '1':
        os.environ['NO_PROXY'] = '*'
        os.environ['no_proxy'] = '*'
    kind, _, code = security_id.partition(':')
    if kind == 'ETF':
        return normalize_etf_announcements(ak.fund_announcement_dividend_em(code), security_id)
    if kind == 'STOCK':
        return normalize_stock_dividends(ak.stock_dividend_cninfo(code), security_id)
    raise ValueError('unsupported security ID')


def archive_etf_pdf(candidate: dict, raw_root: Path, *, session=None) -> dict:
    report_id = candidate['report_id']
    if not REPORT_ID.fullmatch(report_id) or candidate['archive_url'] != f'https://pdf.dfcfw.com/pdf/H2_{report_id}_1.pdf':
        raise ValueError('invalid Eastmoney PDF URL')
    http = session or requests.Session()
    if os.getenv('ETF_DIRECT') == '1' and session is None:
        http.trust_env = False
    response = http.get(candidate['archive_url'], timeout=20)
    response.raise_for_status()
    payload = response.content
    if not payload.startswith(b'%PDF-') or len(payload) > MAX_PDF_BYTES:
        raise ValueError('公告下载结果不是有效大小的PDF')
    try:
        if not PdfReader(BytesIO(payload)).pages:
            raise ValueError('公告PDF没有页面')
    except Exception as error:
        raise ValueError('公告下载结果无法解析为PDF') from error
    digest = hashlib.sha256(payload).hexdigest()
    root = raw_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f'{digest}.pdf'
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise ValueError('本地公告文件哈希冲突')
    if not target.exists():
        target.write_bytes(payload)
    return {**candidate, 'pdf_sha256': digest, 'local_file': target.name,
            'fetched_at': datetime.now(timezone.utc).isoformat()}


def sync_candidates(database_path: Path, security_id: str, raw_root: Path, *, download_etf_pdfs: bool = True,
                    fetcher=fetch_candidates, session=None) -> dict:
    if not re.fullmatch(r'(ETF|STOCK):\d{6}', security_id):
        raise ValueError('invalid security ID')
    candidates = fetcher(security_id)
    if not candidates:
        return {'security_id': security_id, 'status': 'EMPTY_UNVERIFIED',
                'reason': '候选源无记录，不能据此认定从未分红', 'count': 0}
    security_root = raw_root / security_id.replace(':', '_')
    previous = {}
    if security_root.exists():
        for snapshot_file in security_root.glob('*.json'):
            try:
                saved = json.loads(snapshot_file.read_text(encoding='utf-8'))
                for row in saved.get('announcements', []):
                    if row.get('report_id') and row.get('pdf_sha256'):
                        previous[row['report_id']] = row
            except (OSError, ValueError):
                continue
    archived, errors = [], []
    for candidate in candidates:
        try:
            prior = previous.get(candidate.get('report_id'))
            cached = security_root / prior['local_file'] if prior else None
            if (prior and cached.is_file() and
                    hashlib.sha256(cached.read_bytes()).hexdigest() == prior['pdf_sha256']):
                row = {**candidate, 'pdf_sha256': prior['pdf_sha256'],
                       'local_file': cached.name, 'fetched_at': prior.get('fetched_at')}
            else:
                row = (archive_etf_pdf(candidate, security_root, session=session)
                       if download_etf_pdfs and security_id.startswith('ETF:') else candidate)
            archived.append(row)
        except Exception as error:
            errors.append({'report_id': candidate.get('report_id'), 'reason': str(error)})
            archived.append(candidate)
    snapshot = {'provider': 'AkShare', 'announcements': archived, 'errors': errors}
    digest = record_candidate_snapshot(database_path, security_id, snapshot)
    security_root.mkdir(parents=True, exist_ok=True)
    (security_root / f'{digest}.json').write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2), encoding='utf-8')
    return {'security_id': security_id, 'status': 'CANDIDATES_ONLY',
            'count': len(archived), 'pdf_count': sum('pdf_sha256' in row for row in archived),
            'errors': errors, 'snapshot_sha256': digest,
            'reason': '公告目录和下载PDF仅作候选；未与发布机构原件核验，不进入收益率账本'}


def candidate_detail(database_path: Path, security_id: str) -> dict:
    if not re.fullmatch(r'(ETF|STOCK):\d{6}', security_id):
        raise ValueError('invalid security ID')
    root = database_path.parent / 'raw' / 'dividend' / 'announcements' / security_id.replace(':', '_')
    files = list(root.glob('*.json')) if root.exists() else []
    if not files:
        return {'security_id': security_id, 'status': 'NOT_SYNCED', 'items': [],
                'reason': '尚未通过AkShare同步公告候选'}
    latest = max(files, key=lambda path: path.stat().st_mtime_ns)
    snapshot = json.loads(latest.read_text(encoding='utf-8'))
    allowed = {'title', 'announced_at', 'ex_date', 'raw_cash_per_10', 'raw_description',
               'report_period', 'source_id', 'archive_url', 'pdf_sha256',
               'verification_level', 'report_id'}
    items = [{key: value for key, value in row.items() if key in allowed}
             for row in snapshot['announcements']]
    return {'security_id': security_id, 'status': 'CANDIDATES_ONLY', 'items': items,
            'errors': snapshot.get('errors', []),
            'reason': 'AkShare目录与PDF为候选数据，尚需逐份核对发布机构原件'}


if __name__ == '__main__':
    import argparse
    from scripts.config import DATABASE_PATH, ROOT

    parser = argparse.ArgumentParser()
    parser.add_argument('security_id')
    options = parser.parse_args()
    print(json.dumps(sync_candidates(DATABASE_PATH, options.security_id,
                                     ROOT / 'data' / 'raw' / 'dividend' / 'announcements'), ensure_ascii=False))
