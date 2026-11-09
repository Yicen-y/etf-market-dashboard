from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from typing import Any


def _column(frame, candidates, fallback):
    for column in frame.columns:
        if any(candidate in str(column) for candidate in candidates):
            return column
    return frame.columns[fallback]


def _as_date(value):
    if value is None or str(value) in {'NaT', 'nan', 'None'}:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    return date.fromisoformat(text[:10].replace('/', '-'))


def normalize_etf_quotes(frame, security_id: str):
    date_col = _column(frame, ('日期', 'date', '时间'), 0)
    close_col = _column(frame, ('收盘', 'close', '收盘价'), 1)
    return [(security_id, _as_date(row[date_col]), Decimal(str(row[close_col])).quantize(Decimal('0.00001'))) for _, row in frame.iterrows() if _as_date(row[date_col]) and row[close_col] == row[close_col]]


def normalize_etf_dividends(frame, security_id: str):
    date_col = _column(frame, ('日期', 'date'), 0)
    cumulative_col = _column(frame, ('累计分红', '累计', '分红'), 1)
    rows = []
    previous = Decimal('0')
    for index, row in frame.sort_values(date_col).iterrows():
        event_date = _as_date(row[date_col])
        current = Decimal(str(row[cumulative_col]))
        amount = (current - previous).quantize(Decimal('0.00001'))
        previous = current
        if event_date and amount > 0:
            rows.append({'event_id': f'{security_id}:{event_date.isoformat()}:{index}', 'security_id': security_id,
                         'reported_date': event_date, 'ex_date': None, 'amount_per_unit': amount,
                         'raw_amount': current, 'raw_unit': 'CUMULATIVE_PER_UNIT', 'status': 'CANDIDATE',
                         'reason': '累计分红差额不是已核验的单次除息公告'})
    return rows


def normalize_stock_dividends(frame, security_id: str):
    date_col = _column(frame, ('公告日期', '实施公告', 'date'), 0)
    amount_col = _column(frame, ('派息', '现金红利', '现金'), 3 if len(frame.columns) > 3 else 1)
    status_col = _column(frame, ('方案', '状态', '进度'), 2 if len(frame.columns) > 2 else 0)
    ex_col = _column(frame, ('除权除息', '除息'), 3 if len(frame.columns) > 3 else 0)
    record_col = _column(frame, ('股权登记', '登记'), 4 if len(frame.columns) > 4 else 0)
    rows = []
    for index, row in frame.iterrows():
        ex_date = _as_date(row[ex_col])
        raw = row[amount_col]
        if ex_date is None or raw != raw:
            continue
        status_text = str(row[status_col])
        status = 'CANDIDATE'
        announced_at = _as_date(row[date_col])
        rows.append({'event_id': f'{security_id}:{ex_date.isoformat()}:{index}', 'security_id': security_id,
                     'announced_at': announced_at, 'fiscal_year': None, 'record_date': _as_date(row[record_col]),
                     'ex_date': ex_date, 'amount_per_unit': (Decimal(str(raw)) / Decimal('10')).quantize(Decimal('0.00001')),
                     'raw_amount': Decimal(str(raw)), 'raw_unit': 'PER_10', 'status': status,
                     'source_status_text': status_text,
                     'reason': '所属财年与实施状态须按正式公告核验'})
    return rows


def fetch_quotes_with_fallback(security_id: str, start: str, end: str):
    import akshare as ak
    errors = []
    start_text, end_text = start.replace('-', ''), end.replace('-', '')
    kind, separator, code = security_id.partition(':')
    if not separator or len(code) != 6 or not code.isdigit() or kind not in {'ETF', 'STOCK'}:
        raise ValueError(f'invalid security_id: {security_id}')
    if os.getenv('ETF_DIRECT') == '1':
        os.environ['NO_PROXY'] = '*'
        os.environ['no_proxy'] = '*'
    if kind == 'ETF':
        try:
            rows = normalize_etf_quotes(ak.fund_etf_hist_em(code, 'daily', start_text, end_text, ''), security_id)
            if not rows:
                raise ValueError('empty quote interval')
            return rows, 'akshare:eastmoney', errors
        except Exception as error:
            errors.append(f'eastmoney: {error}')
        try:
            market = 'sh' if code.startswith('5') else 'sz'
            rows = normalize_etf_quotes(ak.fund_etf_hist_sina(market + code), security_id)
            lower, upper = _as_date(start), _as_date(end)
            rows = [row for row in rows if lower <= row[1] <= upper]
            if rows:
                return rows, 'akshare:sina', errors
            errors.append('sina: no rows in requested date window')
        except Exception as error:
            errors.append(f'sina: {error}')
    else:
        try:
            rows = normalize_etf_quotes(ak.stock_zh_a_hist(code, 'daily', start_text, end_text, ''), security_id)
            if not rows:
                raise ValueError('empty quote interval')
            return rows, 'akshare:eastmoney', errors
        except Exception as error:
            errors.append(f'eastmoney: {error}')
    raise RuntimeError('; '.join(errors))


def fetch_security_snapshot(security_id: str, start: str, end: str):
    import akshare as ak
    kind, _, code = security_id.partition(':')
    if kind == 'ETF':
        quotes, quote_provider, quote_errors = fetch_quotes_with_fallback(security_id, start, end)
        market = 'sh' if code.startswith('5') else 'sz'
        try:
            dividends = normalize_etf_dividends(ak.fund_etf_dividend_sina(market + code), security_id)
        except Exception as error:
            dividends = []
            quote_errors.append(f'dividend candidate source unavailable: {error}')
        return {'quotes': quotes, 'dividends': dividends, 'provider': quote_provider, 'errors': quote_errors}
    if kind == 'STOCK':
        quotes, quote_provider, quote_errors = fetch_quotes_with_fallback(security_id, start, end)
        try:
            dividends = normalize_stock_dividends(ak.stock_history_dividend_detail(code), security_id)
        except Exception as error:
            dividends = []
            quote_errors.append(f'dividend candidate source unavailable: {error}')
        return {'quotes': quotes, 'dividends': dividends, 'provider': quote_provider, 'errors': quote_errors}
    raise ValueError(f'unsupported security: {security_id}')
