"""Verify unadjusted daily closes by comparing Wind MCP with AkShare/Eastmoney."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from .db import connect, init_schema
from .providers import fetch_quotes_with_fallback
from scripts.wind_credentials import get_authorization
from scripts.wind_mcp_client import WindMcpClient


ENDPOINTS = {
    'ETF': ('https://mcp.wind.com.cn/vserver_fund_data/mcp/', 'get_fund_kline'),
    'STOCK': ('https://mcp.wind.com.cn/vserver_stock_data/mcp/', 'get_stock_kline'),
}


def parse_wind_kline(result: dict, start: date, end: date) -> dict[str, Decimal]:
    if result.get('isError'):
        raise ValueError('Wind K线工具返回错误')
    content = result.get('content') or []
    if not content or content[0].get('type') != 'text':
        raise ValueError('Wind K线响应缺少文本数据')
    payload = json.loads(content[0]['text'])
    if payload.get('error'):
        raise ValueError('Wind K线响应含业务错误')
    data = payload.get('data') or {}
    names = [column['name'] for column in data.get('columns', [])]
    if 'TIME' not in names or 'MATCH' not in names or not isinstance(data.get('rows'), list):
        raise ValueError('Wind K线响应缺少日期或收盘价列')
    time_col, close_col = names.index('TIME'), names.index('MATCH')
    quotes = {}
    for row in data['rows']:
        trade_date = date.fromisoformat(str(row[time_col])[:10])
        price = Decimal(str(row[close_col]))
        if not start <= trade_date <= end or not price.is_finite() or price <= 0:
            raise ValueError('Wind K线日期或收盘价无效')
        key = trade_date.isoformat()
        if key in quotes:
            raise ValueError('Wind K线出现重复交易日')
        quotes[key] = price
    return quotes


def fetch_wind_quotes(security_id: str, market: str, start: date, end: date) -> dict[str, Decimal]:
    kind, _, code = security_id.partition(':')
    if kind not in ENDPOINTS or market not in {'SH', 'SZ', 'BJ'}:
        raise ValueError('证券类型或市场不支持Wind报价核验')
    authorization = get_authorization()
    if not authorization:
        raise RuntimeError('Wind MCP凭证未配置，报价未核验')
    endpoint, tool = ENDPOINTS[kind]
    with WindMcpClient(endpoint, authorization, timeout=60) as client:
        client.initialize()
        result = client.call_tool(tool, {
            'windcode': f'{code}.{market}', 'begin_date': start.isoformat(),
            'end_date': end.isoformat(), 'period': '10', 'aftype': '2', 'issusp': '0',
        })
    return parse_wind_kline(result, start, end)


def fetch_akshare_quotes(security_id: str, start: date, end: date) -> dict[str, Decimal]:
    rows, provider, errors = fetch_quotes_with_fallback(security_id, start.isoformat(), end.isoformat())
    if provider != 'akshare:eastmoney' or errors:
        raise ValueError('AkShare/Eastmoney未复权日线不可用或发生来源切换')
    quotes = {}
    for row_security, trade_date, price in rows:
        key = trade_date.isoformat()
        if row_security != security_id or key in quotes or not price.is_finite() or price <= 0:
            raise ValueError('AkShare报价标的、日期或价格无效')
        quotes[key] = price
    return quotes


def _source_payload(security_id: str, provider: str, quotes: dict[str, Decimal],
                    start: date, end: date) -> str:
    return json.dumps({'security_id': security_id, 'provider': provider,
                       'start_date': start.isoformat(), 'end_date': end.isoformat(),
                       'adjustment': 'unadjusted', 'prices': {day: str(price) for day, price in sorted(quotes.items())}},
                      ensure_ascii=False, sort_keys=True)


def sync_verified_quotes(path: Path, security_id: str, start: str, end: str,
                         *, wind_fetcher=None, akshare_fetcher=None) -> dict:
    lower, upper = date.fromisoformat(start), date.fromisoformat(end)
    if lower > upper or (upper - lower).days > 366:
        raise ValueError('报价核验区间须为不超过366天的正序日期')
    init_schema(path)
    with connect(path) as db:
        security = db.execute('SELECT market FROM dividend_securities WHERE security_id=?',
                              (security_id,)).fetchone()
    if security is None:
        raise ValueError('证券不存在')
    wind = (wind_fetcher or fetch_wind_quotes)(security_id, security['market'], lower, upper)
    akshare = (akshare_fetcher or fetch_akshare_quotes)(security_id, lower, upper)
    if not wind or not akshare:
        raise ValueError('至少一个报价源为空，未核验任何报价')
    for source in (wind, akshare):
        for key, price in source.items():
            day = date.fromisoformat(key)
            if not lower <= day <= upper or not isinstance(price, Decimal) or not price.is_finite() or price <= 0:
                raise ValueError('报价源包含无效日期或价格')
    wind_payload = _source_payload(security_id, 'wind:mcp:kline:unadjusted', wind, lower, upper)
    ak_payload = _source_payload(security_id, 'akshare:eastmoney:unadjusted', akshare, lower, upper)
    wind_sha = hashlib.sha256(wind_payload.encode('utf-8')).hexdigest()
    ak_sha = hashlib.sha256(ak_payload.encode('utf-8')).hexdigest()
    checked_at = datetime.now(timezone.utc).isoformat()
    counts = {'MATCH': 0, 'MISMATCH': 0, 'WIND_ONLY': 0, 'AKSHARE_ONLY': 0}
    with connect(path) as db:
        db.execute('INSERT OR IGNORE INTO raw_source_records(payload,sha256) VALUES (?,?)', (wind_payload, wind_sha))
        db.execute('INSERT OR IGNORE INTO raw_source_records(payload,sha256) VALUES (?,?)', (ak_payload, ak_sha))
        for day in sorted(set(wind) | set(akshare)):
            if day not in wind:
                status = 'AKSHARE_ONLY'
            elif day not in akshare:
                status = 'WIND_ONLY'
            else:
                status = 'MATCH' if wind[day] == akshare[day] else 'MISMATCH'
            counts[status] += 1
            db.execute('''INSERT INTO dividend_quote_verifications
                (security_id,trade_date,wind_price,akshare_price,wind_sha256,akshare_sha256,checked_at,status)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(security_id,trade_date,wind_sha256,akshare_sha256)
                DO UPDATE SET checked_at=excluded.checked_at,status=excluded.status''',
                (security_id, day, str(wind[day]) if day in wind else None,
                 str(akshare[day]) if day in akshare else None, wind_sha, ak_sha, checked_at, status))
            if status == 'MATCH':
                db.execute('''INSERT INTO dividend_quotes
                    (security_id,trade_date,price,source_id,verification_level)
                    VALUES (?,?,?,?,?) ON CONFLICT(security_id,trade_date) DO UPDATE SET
                    price=excluded.price,source_id=excluded.source_id,
                    verification_level=excluded.verification_level''',
                    (security_id, day, str(wind[day]), 'wind+akshare:eastmoney', 'VERIFIED_UNADJUSTED'))
            else:
                db.execute('''UPDATE dividend_quotes SET verification_level='UNVERIFIED'
                    WHERE security_id=? AND trade_date=?''', (security_id, day))
    return {'security_id': security_id, 'start_date': start, 'end_date': end,
            'status': 'VERIFIED' if counts['MATCH'] and not any(counts[key] for key in ('MISMATCH','WIND_ONLY','AKSHARE_ONLY')) else 'PARTIAL',
            'counts': counts, 'wind_sha256': wind_sha, 'akshare_sha256': ak_sha,
            'reason': None if counts['MATCH'] and not any(counts[key] for key in ('MISMATCH','WIND_ONLY','AKSHARE_ONLY'))
                      else '仅逐日价格完全一致的报价被标为已核验；差异与缺日保持未核验'}


if __name__ == '__main__':
    import argparse
    from scripts.config import DATABASE_PATH

    parser = argparse.ArgumentParser()
    parser.add_argument('security_id')
    parser.add_argument('start')
    parser.add_argument('end')
    args = parser.parse_args()
    print(json.dumps(sync_verified_quotes(DATABASE_PATH, args.security_id, args.start, args.end), ensure_ascii=False))
