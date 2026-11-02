from __future__ import annotations

from datetime import date
from decimal import Decimal
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
            rows.append({'event_id': f'{security_id}:{event_date.isoformat()}:{index}', 'security_id': security_id, 'ex_date': event_date, 'amount_per_unit': amount, 'raw_amount': amount, 'raw_unit': 'PER_UNIT', 'status': 'PAID'})
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
        status = 'PAID' if ('实施' in status_text or '已实施' in status_text) else 'PROPOSAL'
        announced_at = _as_date(row[date_col])
        rows.append({'event_id': f'{security_id}:{ex_date.isoformat()}:{index}', 'security_id': security_id, 'announced_at': announced_at, 'fiscal_year': announced_at.year - 1 if announced_at else None, 'record_date': _as_date(row[record_col]), 'ex_date': ex_date, 'amount_per_unit': (Decimal(str(raw)) / Decimal('10')).quantize(Decimal('0.00001')), 'raw_amount': Decimal(str(raw)), 'raw_unit': 'PER_10', 'status': status})
    return rows


def fetch_quotes_with_fallback(security_id: str, start: str, end: str):
    import akshare as ak
    errors = []
    start_text, end_text = start.replace('-', ''), end.replace('-', '')
    if security_id == 'ETF:510880':
        try:
            return normalize_etf_quotes(ak.fund_etf_hist_em('510880', 'daily', start_text, end_text, ''), security_id), 'akshare:eastmoney', errors
        except Exception as error:
            errors.append(f'eastmoney: {error}')
        try:
            rows = normalize_etf_quotes(ak.fund_etf_hist_sina('sh510880'), security_id)
            lower, upper = _as_date(start), _as_date(end)
            rows = [row for row in rows if lower <= row[1] <= upper]
            if rows:
                return rows, 'akshare:sina', errors
            errors.append('sina: no rows in requested date window')
        except Exception as error:
            errors.append(f'sina: {error}')
        try:
            frame = ak.stock_zh_a_hist_tx('sh510880', start_text, end_text, '')
            return normalize_etf_quotes(frame.rename(columns={frame.columns[0]: '日期', frame.columns[4]: '收盘'}), security_id), 'akshare:tencent', errors
        except Exception as error:
            errors.append(f'tencent: {error}')
    elif security_id == 'STOCK:600519':
        try:
            frame = ak.stock_zh_a_hist('600519', 'daily', start_text, end_text, '')
            return normalize_etf_quotes(frame.rename(columns={frame.columns[0]: '日期', frame.columns[2]: '收盘'}), security_id), 'akshare:eastmoney', errors
        except Exception as error:
            errors.append(f'eastmoney: {error}')
        try:
            frame = ak.stock_zh_a_hist_tx('sh600519', start_text, end_text, '')
            return normalize_etf_quotes(frame.rename(columns={frame.columns[0]: '日期', frame.columns[4]: '收盘'}), security_id), 'akshare:tencent', errors
        except Exception as error:
            errors.append(f'tencent: {error}')
    else:
        raise ValueError(f'unsupported security: {security_id}')
    raise RuntimeError('; '.join(errors))


def fetch_security_snapshot(security_id: str, start: str, end: str):
    import akshare as ak
    if security_id == 'ETF:510880':
        quotes, quote_provider, quote_errors = fetch_quotes_with_fallback(security_id, start, end)
        dividends = normalize_etf_dividends(ak.fund_etf_dividend_sina('sh510880'), security_id)
        return {'quotes': quotes, 'dividends': dividends, 'provider': quote_provider, 'errors': quote_errors}
    if security_id == 'STOCK:600519':
        quotes, quote_provider, quote_errors = fetch_quotes_with_fallback(security_id, start, end)
        dividends = ak.stock_history_dividend_detail('600519')
        return {'quotes': quotes, 'dividends': normalize_stock_dividends(dividends, security_id), 'provider': quote_provider, 'errors': quote_errors}
    raise ValueError(f'unsupported security: {security_id}')
