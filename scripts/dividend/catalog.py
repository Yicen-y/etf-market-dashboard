"""Eastmoney security universe, accessed through AkShare and stored as a dated batch."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .db import connect, init_schema


def _market(code: str, kind: str) -> str | None:
    if len(code) != 6 or not code.isdigit():
        return None
    if kind == 'STOCK':
        return 'SH' if code.startswith(('60', '68')) else 'SZ' if code.startswith(('00', '30')) else 'BJ' if code.startswith(('4', '8', '92')) else None
    return 'SH' if code.startswith('5') else 'SZ' if code.startswith('1') else None


def normalize_catalog(frame, kind: str) -> list[dict]:
    if kind not in {'STOCK', 'ETF'} or not {'代码', '名称'}.issubset(frame.columns):
        raise ValueError('证券列表缺少代码或名称字段')
    result = {}
    for _, row in frame.iterrows():
        code, name = str(row['代码']).strip(), str(row['名称']).strip()
        market = _market(code, kind)
        if not market or not name or name.lower() in {'nan', 'none'}:
            continue
        security_id = f'{kind}:{code}'
        if security_id in result and result[security_id]['name'] != name:
            raise ValueError(f'同一证券代码出现不同名称: {security_id}')
        result[security_id] = {'security_id': security_id, 'code': code, 'name': name,
                               'market': market, 'security_type': kind, 'aliases': ''}
    return sorted(result.values(), key=lambda item: item['security_id'])


def fetch_catalog():
    import akshare as ak
    # The workstation's inherited 127.0.0.1 proxy rejects Eastmoney requests.
    # This flag affects only the current catalog refresh process.
    if os.getenv('ETF_DIRECT') == '1':
        os.environ['NO_PROXY'] = '*'
        os.environ['no_proxy'] = '*'
    return {'STOCK': ak.stock_zh_a_spot_em(), 'ETF': ak.fund_etf_spot_em()}


def sync_catalog(path: Path, raw_root: Path, frames=None, *, minimums=None) -> dict:
    frames = frames if frames is not None else fetch_catalog()
    minimums = minimums or {'STOCK': 5000, 'ETF': 1000}
    if set(frames) != {'STOCK', 'ETF'}:
        raise ValueError('A股和ETF列表必须同时可用')
    records = {kind: normalize_catalog(frames[kind], kind) for kind in ('STOCK', 'ETF')}
    for kind, rows in records.items():
        if len(rows) < minimums[kind]:
            raise ValueError(f'{kind}列表仅{len(rows)}条，低于完整性门槛{minimums[kind]}')
    payload = json.dumps({'provider': 'AkShare/Eastmoney', 'records': records},
                         ensure_ascii=False, sort_keys=True).encode('utf-8')
    digest = hashlib.sha256(payload).hexdigest()
    fetched_at = datetime.now(timezone.utc).isoformat()
    raw_root.mkdir(parents=True, exist_ok=True)
    raw_path = raw_root / f'{digest}.json'
    if not raw_path.exists():
        raw_path.write_bytes(payload)
    init_schema(path)
    with connect(path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS dividend_catalog_batches
                      (sha256 TEXT PRIMARY KEY, provider TEXT NOT NULL, fetched_at TEXT NOT NULL,
                       stock_count INTEGER NOT NULL, etf_count INTEGER NOT NULL)''')
        for kind in ('STOCK', 'ETF'):
            db.executemany('''INSERT INTO dividend_securities(security_id,code,name,market,security_type,aliases,active)
                              VALUES (:security_id,:code,:name,:market,:security_type,:aliases,1)
                              ON CONFLICT(security_id) DO UPDATE SET
                              name=excluded.name,market=excluded.market,active=1''', records[kind])
        db.execute('INSERT OR IGNORE INTO dividend_catalog_batches VALUES (?,?,?,?,?)',
                   (digest, 'AkShare/Eastmoney', fetched_at, len(records['STOCK']), len(records['ETF'])))
    return {'status': 'UPDATED', 'provider': 'AkShare/Eastmoney', 'sha256': digest,
            'fetched_at': fetched_at, 'stock_count': len(records['STOCK']),
            'etf_count': len(records['ETF']), 'raw_path': str(raw_path)}


def catalog_status(path: Path) -> dict:
    init_schema(path)
    with connect(path) as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dividend_catalog_batches'").fetchone()
        row = db.execute('SELECT * FROM dividend_catalog_batches ORDER BY fetched_at DESC LIMIT 1').fetchone() if exists else None
    if row is None:
        return {'status': 'NOT_SYNCED', 'provider': None, 'reason': '证券基础表尚未成功同步'}
    return {'status': 'READY', 'provider': row['provider'], 'fetched_at': row['fetched_at'],
            'stock_count': row['stock_count'], 'etf_count': row['etf_count'], 'sha256': row['sha256']}


if __name__ == '__main__':
    from scripts.config import DATABASE_PATH, ROOT
    print(json.dumps(sync_catalog(DATABASE_PATH, ROOT / 'data' / 'raw' / 'dividend' / 'catalog'), ensure_ascii=False))
