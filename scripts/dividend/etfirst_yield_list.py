"""Paged ETFirst ETF index-dividend-yield list with source and date checks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from .db import connect, init_schema


PROVIDER = 'etfirst:index-base:list-etf'


def _day(value) -> str | None:
    if value is None:
        return None
    if not re.fullmatch(r'\d{8}', str(value)):
        raise ValueError('ETFirst估值日期格式无效')
    return datetime.strptime(str(value), '%Y%m%d').date().isoformat()


def parse_etfirst_page(payload: dict, page: int, page_size: int) -> dict:
    if payload.get('code') not in {'00000', '0000', '000000'}:
        raise ValueError('ETFirst列表接口返回错误')
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('totalRows'), int):
        raise ValueError('ETFirst列表缺少总数')
    rows = data.get('dataList')
    if not isinstance(rows, list) or len(rows) > page_size or data['totalRows'] < 0:
        raise ValueError('ETFirst列表分页无效')
    if data['totalRows'] > 0 and not rows and (page - 1) * page_size < data['totalRows']:
        raise ValueError('ETFirst列表在有效分页内返回空记录')
    items = []
    for row in rows:
        code = str(row.get('prodCd') or '')
        index_code = str(row.get('indexCd') or '')
        name = row.get('prodName')
        if not re.fullmatch(r'\d{6}', code) or not isinstance(name, str) or not name.strip():
            raise ValueError('ETFirst列表含无效ETF身份')
        value = row.get('dp')
        day = _day(row.get('peDate'))
        if value is None or day is None:
            pct, status, reason = None, 'UNAVAILABLE', '该ETF没有可用的跟踪指数股息率或估值日期'
        else:
            pct_decimal = Decimal(str(value))
            if not pct_decimal.is_finite() or not Decimal('0') <= pct_decimal <= Decimal('100'):
                raise ValueError('ETFirst股息率数值无效')
            if date.fromisoformat(day) > date.today():
                raise ValueError('ETFirst股息率日期晚于当前日期')
            pct, status, reason = str(pct_decimal), 'READY', None
        items.append({'security_id': f'ETF:{code}', 'code': code, 'name': name.strip(),
                      'index_code': index_code or None, 'index_name': row.get('indexName') or None,
                      'value_pct': pct, 'as_of_date': day, 'status': status,
                      'reason': reason, 'metric_label': '跟踪指数股息率', 'provider': PROVIDER})
    return {'page': page, 'page_size': page_size, 'total_rows': data['totalRows'],
            'items': items, 'status': 'READY', 'provider': PROVIDER,
            'metric_label': '跟踪指数股息率'}


def fetch_etfirst_page(page: int, page_size: int) -> dict:
    environment = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    result = subprocess.run(['etfirst', '--json', 'index-base', 'list-etf', '--type', '2',
                             '--page-no', str(page), '--page-size', str(page_size)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=45, check=False, env=environment)
    if result.returncode != 0:
        raise RuntimeError(f'ETFirst列表调用失败（退出码{result.returncode}）')
    return json.loads(result.stdout)


def etfirst_yield_page(path: Path, page: int, page_size: int = 20, *, fetcher=None) -> dict:
    if page < 1 or page_size < 1 or page_size > 100:
        raise ValueError('分页参数超出范围')
    try:
        raw = (fetcher or fetch_etfirst_page)(page, page_size)
        parsed = parse_etfirst_page(raw, page, page_size)
        canonical = json.dumps({'page': page, 'page_size': page_size, 'response': raw},
                               ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        init_schema(path)
        with connect(path) as db:
            db.execute('INSERT OR IGNORE INTO raw_source_records(payload,sha256) VALUES (?,?)',
                       (canonical, digest))
            known = {row[0] for row in db.execute('''SELECT security_id FROM dividend_securities
                WHERE security_type='ETF' AND security_id IN (%s)''' % ','.join('?' * len(parsed['items'])),
                [row['security_id'] for row in parsed['items']])} if parsed['items'] else set()
        for item in parsed['items']:
            item['in_local_catalog'] = item['security_id'] in known
        return {**parsed, 'source_sha256': digest,
                'fetched_at': datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        return {'page': page, 'page_size': page_size, 'total_rows': None, 'items': [],
                'status': 'UNAVAILABLE', 'provider': PROVIDER,
                'metric_label': '跟踪指数股息率', 'reason': str(exc),
                'source_sha256': None, 'fetched_at': None}
