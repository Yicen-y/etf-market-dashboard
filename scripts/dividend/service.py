from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from .db import connect, init_schema, list_watchlist, record_candidate_snapshot
from .providers import fetch_security_snapshot
from .announcement_sync import sync_candidates
from .provider_yields import (provider_yield_detail, provider_yield_history_detail,
                              record_wind_stock_yield_observation, sync_provider_yield,
                              STOCK_PROVIDER)
from .domain import CashEvent, Coverage, calculate_annual_reference, calculate_forward_groups, calculate_ttm, normalize_cash_amount, select_as_known_revision


def ensure_seed(path: Path) -> None:
    """Initialize the schema. Historical sample rows are never production facts."""
    init_schema(path)


def security(path: Path, security_id: str):
    with connect(path) as db:
        return db.execute("SELECT * FROM dividend_securities WHERE security_id=?", (security_id,)).fetchone()


def _calculation_coverage(db, security_id: str, observed: date, quote, *, history: bool = False,
                          query_mode: str = 'latest_verified') -> Coverage:
    if quote is None or quote['price'] is None:
        return Coverage.incomplete('行情价格未同步')
    if quote['verification_level'] != 'VERIFIED_UNADJUSTED':
        return Coverage.incomplete('观察日未复权收盘价尚未核验')
    start = (observed - timedelta(days=365)).isoformat()
    certificate = db.execute('''SELECT 1 FROM dividend_coverage c
        JOIN source_documents d ON d.sha256=c.evidence_sha256 AND d.verification_level='OFFICIAL_VERIFIED'
        WHERE c.security_id=? AND c.start_date<=? AND c.end_date>=?
        AND c.dividends_complete=1 AND c.actions_verified=1
        AND c.query_mode=? AND (?=0 OR c.quote_calendar_verified=1) LIMIT 1''',
        (security_id, start, observed.isoformat(), query_mode, int(history))).fetchone()
    if certificate is None:
        return Coverage.incomplete('缺少覆盖整段365天的官方分红与权益变动核验证明')
    action = db.execute('''SELECT 1 FROM dividend_corporate_actions
        WHERE security_id=? AND effective_date>? AND effective_date<=?
        AND NOT (action_type='BUYBACK_CANCELLATION' AND ratio='1') LIMIT 1''',
        (security_id, start, observed.isoformat())).fetchone()
    if action:
        return Coverage.incomplete('窗口内存在权益变动，尚未完成现金分红单位调整核验')
    if query_mode == 'as_known':
        return Coverage.complete()
    unresolved = db.execute('''SELECT e.event_id FROM dividend_events e
        LEFT JOIN dividend_revisions r ON r.revision_id=e.current_revision_id
        LEFT JOIN source_documents d ON d.id=r.source_document_id
        WHERE e.security_id=? AND e.ex_date>? AND e.ex_date<=?
        AND (e.state!='PAID' OR r.status!='PAID' OR d.verification_level IS NULL
             OR d.verification_level!='OFFICIAL_VERIFIED')
        AND NOT EXISTS (SELECT 1 FROM dividend_event_reconciliations x
            JOIN dividend_events official ON official.event_id=x.official_event_id
            JOIN dividend_revisions vr ON vr.revision_id=official.current_revision_id
            JOIN source_documents vd ON vd.id=vr.source_document_id
            WHERE x.candidate_event_id=e.event_id AND x.candidate_revision_id=e.current_revision_id
            AND x.official_revision_id=official.current_revision_id
            AND official.ex_date=e.ex_date AND vd.verification_level='OFFICIAL_VERIFIED') LIMIT 1''',
        (security_id, start, observed.isoformat())).fetchone()
    if unresolved:
        return Coverage.incomplete('TTM窗口内存在未核验或状态不一致的分红事件')
    return Coverage.complete()


def _annual_coverage(db, security_id: str, observed: date, quote, kind: str, events) -> Coverage:
    if quote is None or quote['price'] is None or quote['verification_level'] != 'VERIFIED_UNADJUSTED':
        return Coverage.incomplete('观察日未复权收盘价尚未核验')
    year = observed.year - 1 if kind == 'ETF' else max((e.fiscal_year for e in events if e.fiscal_year is not None), default=None)
    if year is None:
        return Coverage.incomplete('股票分红所属财年尚未核验')
    certificate = db.execute('''SELECT 1 FROM dividend_coverage c
        JOIN source_documents d ON d.sha256=c.evidence_sha256 AND d.verification_level='OFFICIAL_VERIFIED'
        WHERE c.security_id=? AND c.start_date<=? AND c.end_date>=?
        AND c.dividends_complete=1 AND c.actions_verified=1 LIMIT 1''',
        (security_id, f'{year}-01-01', f'{year}-12-31')).fetchone()
    if certificate is None:
        return Coverage.incomplete(f'{year}年度官方分红覆盖未核验')
    action = db.execute('''SELECT 1 FROM dividend_corporate_actions
        WHERE security_id=? AND effective_date>=? AND effective_date<=?
        AND NOT (action_type='BUYBACK_CANCELLATION' AND ratio='1') LIMIT 1''',
        (security_id, f'{year}-01-01', observed.isoformat())).fetchone()
    if action:
        return Coverage.incomplete('年度分红涉及权益变动，尚未完成单位调整核验')
    unresolved = db.execute('''SELECT 1 FROM dividend_events e
        LEFT JOIN dividend_revisions r ON r.revision_id=e.current_revision_id
        LEFT JOIN source_documents d ON d.id=r.source_document_id
        WHERE e.security_id=? AND e.ex_date>=? AND e.ex_date<=?
        AND (e.state!='PAID' OR r.status!='PAID' OR d.verification_level IS NULL
             OR d.verification_level!='OFFICIAL_VERIFIED')
        AND NOT EXISTS (SELECT 1 FROM dividend_event_reconciliations x
            JOIN dividend_events official ON official.event_id=x.official_event_id
            JOIN dividend_revisions vr ON vr.revision_id=official.current_revision_id
            JOIN source_documents vd ON vd.id=vr.source_document_id
            WHERE x.candidate_event_id=e.event_id AND x.candidate_revision_id=e.current_revision_id
            AND x.official_revision_id=official.current_revision_id
            AND official.ex_date=e.ex_date AND vd.verification_level='OFFICIAL_VERIFIED') LIMIT 1''',
        (security_id, f'{year}-01-01', f'{year}-12-31')).fetchone()
    if unresolved:
        return Coverage.incomplete(f'{year}年度存在未核验或状态不一致的分红事件')
    return Coverage.complete()


def yield_detail(path: Path, security_id: str):
    item = security(path, security_id)
    if not item:
        return None
    with connect(path) as db:
        rows = db.execute("""SELECT e.*, d.verification_level AS document_level,
                                  r.status AS revision_status
                           FROM dividend_events e
                           LEFT JOIN dividend_revisions r ON r.revision_id=e.current_revision_id
                           LEFT JOIN source_documents d ON d.id=r.source_document_id
                           WHERE e.security_id=?""", (security_id,)).fetchall()
        quote = db.execute("SELECT price, trade_date, verification_level FROM dividend_quotes WHERE security_id=? ORDER BY trade_date DESC LIMIT 1", (security_id,)).fetchone()
        observed = date.fromisoformat(quote['trade_date']) if quote else date.today()
        coverage = _calculation_coverage(db, security_id, observed, quote)
        kind = item['security_type']
        verified_rows = [row for row in rows if row['document_level'] == 'OFFICIAL_VERIFIED'
                         and row['revision_status'] == row['state']]
        verified_events = [CashEvent(security_id, date.fromisoformat(row['ex_date']), Decimal(row['amount_per_unit']),
                                     row['fiscal_year'], row['state'], row['event_id'], row['current_revision_id'] or '')
                           for row in verified_rows if row['ex_date'] and row['amount_per_unit']]
        annual_coverage = _annual_coverage(db, security_id, observed, quote, kind, verified_events)
    unique = {}
    for row in verified_rows:
        if row['ex_date']:
            key = (row['ex_date'], row['amount_per_unit'])
            unique.setdefault(key, row)
    events = [CashEvent(security_id, date.fromisoformat(row['ex_date']), Decimal(row['amount_per_unit']), row['fiscal_year'], row['state'], row['event_id'], row['current_revision_id'] or '') for row in unique.values()]
    if quote is None or quote['price'] is None:
        result = calculate_ttm(date.today(), Decimal('0'), events, Coverage.incomplete('行情价格未同步'))
        price_date = None
    else:
        result = calculate_ttm(date.fromisoformat(quote['trade_date']), Decimal(quote['price']), events, coverage)
        price_date = quote['trade_date']
    effective_coverage = coverage
    annual = calculate_annual_reference(date.fromisoformat(price_date), Decimal(quote['price']), events, annual_coverage, kind=kind) if quote else result
    forward = calculate_forward_groups(date.fromisoformat(price_date), Decimal(quote['price']), events, effective_coverage) if quote else None
    def pack(metric, metric_coverage=effective_coverage):
        return {"value_pct": str(metric.value_pct) if metric.value_pct is not None else None, "coverage_status": metric_coverage.status, "reason": metric.reason, "event_ids": list(metric.event_ids), "numerator_cash_per_unit": str(metric.numerator_cash_per_unit) if metric.numerator_cash_per_unit is not None else None, "denominator_price": str(metric.denominator_price) if quote and quote['verification_level'] == 'VERIFIED_UNADJUSTED' else None, "price_trade_date": price_date}
    ttm_payload, annual_payload = pack(result), pack(annual, annual_coverage)
    confirmed_payload = pack(forward.confirmed) if forward else pack(result)
    proposal_payload = pack(forward.proposal) if forward else pack(result)
    for packed in (ttm_payload, annual_payload, confirmed_payload, proposal_payload):
        packed['verification_status'] = 'VERIFIED' if packed['value_pct'] is not None else 'INCOMPLETE_EVIDENCE'
        packed['quality_status'] = 'READY' if packed['value_pct'] is not None else 'DATA_INCOMPLETE'
    payload = {"security_id": security_id, "security": dict(item), "ttm": ttm_payload, "annual_reference": annual_payload, "confirmed": confirmed_payload, "proposal": proposal_payload, "provider_yield": provider_yield_detail(path, security_id), "calculation_version": "dividend-d0-v1", "query_mode": "latest_verified", "data_source": "local SQLite snapshot"}
    return payload


def event_detail(path: Path, security_id: str):
    item = security(path, security_id)
    if not item:
        return None
    with connect(path) as db:
        rows = db.execute("""SELECT e.*, r.disclosed_at, r.known_at, r.raw_amount, r.raw_unit,
                                  r.status AS revision_status, d.url AS source_url,
                                  d.sha256 AS source_sha256, d.publisher AS source_publisher,
                                  d.verification_level AS source_verification_level
                           FROM dividend_events e
                           LEFT JOIN dividend_revisions r ON r.revision_id=e.current_revision_id
                           LEFT JOIN source_documents d ON d.id=r.source_document_id
                           WHERE e.security_id=?
                           ORDER BY (d.verification_level='OFFICIAL_VERIFIED') DESC, e.ex_date DESC""", (security_id,)).fetchall()
    unique = {}
    for row in rows:
        unique.setdefault((row['ex_date'], row['amount_per_unit']), row)
    return {'items': [{**dict(row), 'verification_status': row['source_verification_level'] if row['source_sha256'] else 'INCOMPLETE_EVIDENCE',
                       'reason': None if row['source_verification_level'] == 'OFFICIAL_VERIFIED' else '事件尚未关联已核验的官方公告版本'} for row in unique.values()],
            'verification_status': 'INCOMPLETE_EVIDENCE'}


def calendar_detail(path: Path, security_type: str, days: int, as_of: date | None = None):
    today = as_of or date.today()
    end = today + timedelta(days=days)
    with connect(path) as db:
        rows = db.execute("""SELECT e.event_id, e.security_id, e.ex_date, e.amount_per_unit,
                                   e.current_revision_id, s.name, s.code, s.market,
                                   r.known_at, r.status, d.url AS source_url, d.sha256 AS source_sha256
                            FROM dividend_events e
                            JOIN dividend_watchlist w ON w.security_id=e.security_id
                            JOIN dividend_securities s ON s.security_id=e.security_id
                            JOIN dividend_revisions r ON r.revision_id=e.current_revision_id
                            JOIN source_documents d ON d.id=r.source_document_id
                            WHERE s.security_type=? AND e.ex_date>? AND e.ex_date<=?
                              AND e.state='CONFIRMED' AND r.status='CONFIRMED'
                              AND r.known_at<=? AND d.verification_level='OFFICIAL_VERIFIED'
                              AND d.url IS NOT NULL AND d.sha256 IS NOT NULL
                            ORDER BY e.ex_date, e.event_id""",
                          (security_type, today.isoformat(), end.isoformat(), today.isoformat())).fetchall()
    return {'items': [dict(row) for row in rows], 'type': security_type, 'days': days,
            'as_of': today.isoformat(), 'status': 'READY' if rows else 'NO_VERIFIED_EVENTS',
            'reason': None if rows else '未来区间暂无已核验官方公告且日期确定的自选除息事件'}


def history_detail(path: Path, security_id: str, window: str, query_mode: str):
    item = security(path, security_id)
    if not item:
        return None
    with connect(path) as db:
        quote_rows = db.execute('SELECT trade_date,price,verification_level FROM dividend_quotes WHERE security_id=? ORDER BY trade_date', (security_id,)).fetchall()
        event_rows = db.execute('''SELECT e.*, r.status AS revision_status, d.verification_level AS document_level
            FROM dividend_events e LEFT JOIN dividend_revisions r ON r.revision_id=e.current_revision_id
            LEFT JOIN source_documents d ON d.id=r.source_document_id WHERE e.security_id=?''',
            (security_id,)).fetchall()
        revision_rows = db.execute('''SELECT r.*, d.verification_level AS document_level
            FROM dividend_revisions r JOIN dividend_events e ON e.event_id=r.event_id
            LEFT JOIN source_documents d ON d.id=r.source_document_id
            WHERE e.security_id=?''', (security_id,)).fetchall()
    if not quote_rows:
        return {'security_id': security_id, 'range': window, 'query_mode': query_mode, 'coverage_status': 'INCOMPLETE', 'missing_reason': '未同步未复权日线', 'rows': []}
    latest = date.fromisoformat(quote_rows[-1]['trade_date'])
    days = {'1Y': 365, '3Y': 1095, '5Y': 1825}[window]
    start = latest.fromordinal(latest.toordinal() - days)
    selected = [row for row in quote_rows if date.fromisoformat(row['trade_date']) > start]
    verified_events = [CashEvent(security_id, date.fromisoformat(row['ex_date']), Decimal(row['amount_per_unit']),
                                 row['fiscal_year'], row['state'], row['event_id'], row['current_revision_id'] or '')
                       for row in event_rows if row['ex_date'] and row['amount_per_unit']
                       and row['document_level'] == 'OFFICIAL_VERIFIED' and row['revision_status'] == row['state']]
    revisions_by_event = {}
    for revision in revision_rows:
        revisions_by_event.setdefault(revision['event_id'], []).append(dict(revision))
    rows = []
    with connect(path) as db:
        for quote in selected:
            observed = date.fromisoformat(quote['trade_date'])
            if quote['price'] is None:
                rows.append({'observed_date': quote['trade_date'], 'price': None,
                             'ttm_cash_per_unit': None, 'ttm_pct': None,
                             'reason': '观察日未复权收盘价缺失', 'event_ids': []})
                continue
            coverage = _calculation_coverage(db, security_id, observed, quote, history=True, query_mode=query_mode)
            if query_mode == 'as_known':
                point_events = []
                for event_id, revisions in revisions_by_event.items():
                    revision = select_as_known_revision(revisions, observed)
                    if revision and revision['status'] == 'PAID':
                        point_events.append(CashEvent(
                            security_id, date.fromisoformat(revision['ex_date']),
                            normalize_cash_amount(Decimal(revision['raw_amount']), revision['raw_unit']),
                            revision['fiscal_year'], revision['status'], event_id, revision['revision_id']))
            else:
                point_events = verified_events
            metric = calculate_ttm(observed, Decimal(quote['price']), point_events, coverage)
            rows.append({'observed_date': quote['trade_date'],
                         'price': quote['price'] if quote['verification_level'] == 'VERIFIED_UNADJUSTED' else None,
                         'ttm_cash_per_unit': str(metric.numerator_cash_per_unit) if metric.numerator_cash_per_unit is not None else None,
                         'ttm_pct': str(metric.value_pct) if metric.value_pct is not None else None,
                         'reason': metric.reason, 'event_ids': list(metric.event_ids) if metric.value_pct is not None else []})
    minimum_rows = {'1Y': 200, '3Y': 600, '5Y': 1000}[window]
    start_covered = bool(selected) and (date.fromisoformat(selected[0]['trade_date']) - start).days <= 14
    complete = start_covered and len(rows) >= minimum_rows and all(row['ttm_pct'] is not None for row in rows)
    return {'security_id': security_id, 'range': window, 'query_mode': query_mode,
            'coverage_status': 'COMPLETE' if complete else 'INCOMPLETE',
            'missing_reason': None if complete else '未取得覆盖全部所选交易日的行情、公告及权益变动核验证明', 'rows': rows}


def sync_watchlist(path: Path, security_type: str):
    rows = list_watchlist(path, security_type)
    results = [sync_security(path, row['security_id']) for row in rows]
    return {'type': security_type, 'status': 'incomplete' if results else 'idle', 'items': results}


def sync_security(path: Path, security_id: str, start: str = '2021-01-01', end: str | None = None):
    if not security(path, security_id):
        return None
    provider_result = sync_provider_yield(path, security_id)
    history_result = None
    if (provider_result.get('provider') == STOCK_PROVIDER and
            provider_result.get('status') == 'READY' and
            provider_result.get('value_pct') is not None and
            provider_result.get('as_of_date')):
        history_result = record_wind_stock_yield_observation(
            path, security_id, provider_result)
    try:
        snapshot = fetch_security_snapshot(security_id, start, end or date.today().isoformat())
        dividends = snapshot['dividends'] if isinstance(snapshot['dividends'], list) else []
        candidate_hash = record_candidate_snapshot(path, security_id, snapshot)
        try:
            announcement_sync = sync_candidates(path, security_id,
                path.parent / 'raw' / 'dividend' / 'announcements')
        except Exception as error:
            announcement_sync = {'status': 'ERROR', 'reason': str(error), 'count': 0, 'pdf_count': 0}
        return {'security_id': security_id, 'status': 'incomplete', 'quote_count': len(snapshot['quotes']),
                'provider_yield': provider_result, 'provider_yield_history': history_result,
                'candidate_event_count': len(dividends), 'provider': snapshot['provider'],
                'candidate_sha256': candidate_hash,
                'announcement_count': announcement_sync['count'],
                'announcement_pdf_count': announcement_sync.get('pdf_count', 0),
                'announcement_status': announcement_sync['status'],
                'reason': ('提供方股息率：' + provider_result['status'] + '；行情与分红候选尚未逐笔关联官方公告'),
                'warnings': snapshot.get('errors', []) +
                    ([announcement_sync['reason']] if announcement_sync['status'] == 'ERROR' else [])}
    except Exception as error:
        return {'security_id': security_id, 'status': 'error', 'message': str(error),
                'provider_yield': provider_result, 'provider_yield_history': history_result}
