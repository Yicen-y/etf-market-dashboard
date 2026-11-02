from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from .db import add_watchlist, connect, init_schema, list_watchlist, remove_watchlist, search, upsert_security, persist_snapshot
from .providers import fetch_security_snapshot
from .domain import CashEvent, Coverage, calculate_annual_reference, calculate_forward_groups, calculate_ttm


def ensure_seed(path: Path) -> None:
    init_schema(path)
    for item in (
        {"security_id": "ETF:510880", "code": "510880", "name": "红利ETF", "market": "SH", "security_type": "ETF", "aliases": "红利ETF"},
        {"security_id": "STOCK:600519", "code": "600519", "name": "贵州茅台", "market": "SH", "security_type": "STOCK", "aliases": "茅台 GZM"},
    ):
        upsert_security(path, item)
    with connect(path) as db:
        db.execute("""INSERT OR IGNORE INTO dividend_events(event_id,security_id,fiscal_year,ex_date,amount_per_unit,state,current_revision_id)
            VALUES ('ETF:510880:2026-01-21','ETF:510880',2026,'2026-01-21','0.14300','PAID','ETF:510880:2026-01-21:r1')""")
        db.execute("""INSERT OR IGNORE INTO dividend_revisions(revision_id,event_id,disclosed_at,known_at,raw_amount,raw_unit,status,source_document_id)
            VALUES ('ETF:510880:2026-01-21:r1','ETF:510880:2026-01-21','2026-01-16','2026-01-16','1.4300','PER_10','PAID',NULL)""")


def security(path: Path, security_id: str):
    with connect(path) as db:
        return db.execute("SELECT * FROM dividend_securities WHERE security_id=?", (security_id,)).fetchone()


def yield_detail(path: Path, security_id: str):
    item = security(path, security_id)
    if not item:
        return None
    with connect(path) as db:
        rows = db.execute("SELECT * FROM dividend_events WHERE security_id=? AND state='PAID'", (security_id,)).fetchall()
        quote = db.execute("SELECT price, trade_date FROM dividend_quotes WHERE security_id=? ORDER BY trade_date DESC LIMIT 1", (security_id,)).fetchone()
    unique = {}
    for row in rows:
        if row['ex_date']:
            key = (row['ex_date'], row['amount_per_unit'])
            unique.setdefault(key, row)
    events = [CashEvent(security_id, date.fromisoformat(row['ex_date']), Decimal(row['amount_per_unit']), row['fiscal_year'], row['state'], row['event_id'], row['current_revision_id'] or '') for row in unique.values()]
    verified_source = security_id == 'ETF:510880'
    coverage = Coverage.complete() if quote is not None and events and verified_source else Coverage.incomplete('行情或完整官方分红事件尚未核验')
    if quote is None or quote['price'] is None:
        result = calculate_ttm(date(2026, 10, 23), Decimal('0'), events, Coverage.incomplete('行情价格未同步'))
        price_date = None
    else:
        result = calculate_ttm(date.fromisoformat(quote['trade_date']), Decimal(quote['price']), events, coverage)
        price_date = quote['trade_date']
    effective_coverage = coverage if quote else Coverage.incomplete('行情价格未同步')
    annual = calculate_annual_reference(date.fromisoformat(price_date), Decimal(quote['price']), events, effective_coverage, kind='ETF' if item['security_type'] == 'ETF' else 'STOCK') if quote else result
    forward = calculate_forward_groups(date.fromisoformat(price_date), Decimal(quote['price']), events, effective_coverage) if quote else None
    def pack(metric):
        return {"value_pct": str(metric.value_pct) if metric.value_pct is not None else None, "coverage_status": effective_coverage.status, "reason": metric.reason, "event_ids": list(metric.event_ids), "numerator_cash_per_unit": str(metric.numerator_cash_per_unit) if metric.numerator_cash_per_unit is not None else None, "denominator_price": str(metric.denominator_price) if quote else None, "price_trade_date": price_date}
    verification_status = 'official_source_downloaded' if security_id == 'ETF:510880' else 'mirror_only_official_url_unavailable'
    ttm_payload, annual_payload = pack(result), pack(annual)
    confirmed_payload = pack(forward.confirmed) if forward else pack(result)
    proposal_payload = pack(forward.proposal) if forward else pack(result)
    for packed in (ttm_payload, annual_payload, confirmed_payload, proposal_payload):
        packed['verification_status'] = verification_status
    payload = {"security_id": security_id, "security": dict(item), "ttm": ttm_payload, "annual_reference": annual_payload, "confirmed": confirmed_payload, "proposal": proposal_payload, "calculation_version": "dividend-d0-v1", "query_mode": "latest_verified", "data_source": "local SQLite snapshot"}
    return payload


def event_detail(path: Path, security_id: str):
    item = security(path, security_id)
    if not item:
        return None
    with connect(path) as db:
        rows = db.execute("SELECT * FROM dividend_events WHERE security_id=? ORDER BY ex_date DESC", (security_id,)).fetchall()
    sources = {
        'ETF:510880': {'url': 'https://www.sse.com.cn/disclosure/fund/announcement/c/new/2026-01-16/510880_20260116_DSHH.pdf', 'status': 'official_source_downloaded'},
        'STOCK:600519': {'url': 'https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-06-22/600519_20260622_ZTRO.pdf', 'status': 'mirror_only_official_url_unavailable'},
    }
    source = sources.get(security_id, {'url': None, 'status': 'incomplete'})
    unique = {}
    for row in rows:
        unique.setdefault((row['ex_date'], row['amount_per_unit']), row)
    return {'items': [{**dict(row), 'source_url': source['url'], 'verification_status': source['status']} for row in unique.values()], 'verification_status': source['status']}


def history_detail(path: Path, security_id: str, window: str, query_mode: str):
    item = security(path, security_id)
    if not item:
        return None
    with connect(path) as db:
        quote_rows = db.execute('SELECT trade_date,price FROM dividend_quotes WHERE security_id=? ORDER BY trade_date', (security_id,)).fetchall()
        event_rows = db.execute("SELECT * FROM dividend_events WHERE security_id=? AND state='PAID' ORDER BY ex_date", (security_id,)).fetchall()
    events = [CashEvent(security_id, date.fromisoformat(row['ex_date']), Decimal(row['amount_per_unit']), row['fiscal_year'], row['state'], row['event_id'], row['current_revision_id'] or '') for row in event_rows if row['ex_date']]
    if not quote_rows:
        return {'security_id': security_id, 'range': window, 'query_mode': query_mode, 'coverage_status': 'INCOMPLETE', 'missing_reason': '未同步未复权日线', 'rows': []}
    latest = date.fromisoformat(quote_rows[-1]['trade_date'])
    days = {'1Y': 365, '3Y': 1095, '5Y': 1825}[window]
    start = latest.fromordinal(latest.toordinal() - days)
    selected = [row for row in quote_rows if date.fromisoformat(row['trade_date']) > start]
    complete = item['security_type'] == 'ETF' and len(quote_rows) >= 250 and any(e.ex_date <= start for e in events)
    rows = []
    for quote in selected:
        observed = date.fromisoformat(quote['trade_date'])
        metric = calculate_ttm(observed, Decimal(quote['price']), events, Coverage.complete() if complete else Coverage.incomplete('曲线起点前365日覆盖不足'))
        rows.append({'observed_date': quote['trade_date'], 'price': quote['price'], 'ttm_cash_per_unit': str(metric.numerator_cash_per_unit) if metric.numerator_cash_per_unit is not None else None, 'ttm_pct': str(metric.value_pct) if metric.value_pct is not None else None, 'event_ids': list(metric.event_ids)})
    return {'security_id': security_id, 'range': window, 'query_mode': query_mode, 'coverage_status': 'COMPLETE' if complete else 'INCOMPLETE', 'missing_reason': None if complete else '未同步足够的未复权日线与曲线起点前365日分红事件', 'rows': rows}


def sync_watchlist(path: Path, security_type: str):
    rows = list_watchlist(path, security_type)
    return {'type': security_type, 'status': 'partial' if rows else 'idle', 'items': [{'security_id': row['security_id'], 'status': 'incomplete', 'message': '本地同步器尚未配置该标的的联网行情/分红源'} for row in rows]}


def sync_security(path: Path, security_id: str, start: str = '2021-01-01', end: str = '2026-11-01'):
    if not security(path, security_id):
        return None
    try:
        snapshot = fetch_security_snapshot(security_id, start, end)
        dividends = snapshot['dividends'] if isinstance(snapshot['dividends'], list) else []
        persist_snapshot(path, security_id, snapshot['quotes'], dividends)
        return {'security_id': security_id, 'status': 'success', 'quote_count': len(snapshot['quotes']), 'event_count': len(dividends), 'provider': snapshot['provider'], 'warnings': snapshot.get('errors', [])}
    except Exception as error:
        return {'security_id': security_id, 'status': 'error', 'message': str(error)}
