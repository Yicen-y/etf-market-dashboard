from decimal import Decimal

import pytest

from scripts.dividend.db import connect, init_schema, upsert_security
from scripts.dividend.provider_yields import (
    calculate_provider_yield_summary,
    sync_wind_stock_yield_history,
)


def seed_stock(path):
    init_schema(path)
    upsert_security(path, {
        'security_id': 'STOCK:601318', 'code': '601318', 'name': '中国平安',
        'market': 'SH', 'security_type': 'STOCK', 'aliases': '平安',
    })


def test_summary_percentile_ignores_failed_and_missing_rows():
    result = calculate_provider_yield_summary([
        {'trade_date': '2026-01-01', 'value_pct': '2.0', 'status': 'READY'},
        {'trade_date': '2026-01-02', 'value_pct': None, 'status': 'FAILED'},
        {'trade_date': '2026-01-03', 'value_pct': '3.0', 'status': 'READY'},
        {'trade_date': '2026-01-04', 'value_pct': '4.0', 'status': 'READY'},
    ], current_value='3.0')

    assert result['sample_count'] == 3
    assert result['percentile'] == Decimal('66.6667')
    assert result['minimum'] == Decimal('2.0')
    assert result['maximum'] == Decimal('4.0')


def test_history_sync_is_idempotent_and_records_failed_dates(tmp_path):
    path = tmp_path / 'dividend.sqlite'
    seed_stock(path)
    dates = ['2026-01-01', '2026-01-02', '2026-01-03']
    calls = []

    def fetcher(code, market, trade_date):
        calls.append(trade_date)
        if trade_date == '2026-01-02':
            raise RuntimeError('Wind暂时无数据')
        return {
            'value_pct': '3.5' if trade_date == '2026-01-01' else '4.0',
            'as_of_date': trade_date,
            'metric_label': 'Wind股息率（提供方口径）',
            'provider': 'wind:mcp:stock_fundamentals',
            'raw': {'date': trade_date},
        }

    first = sync_wind_stock_yield_history(
        path, 'STOCK:601318', date_fetcher=lambda *_: dates,
        yield_fetcher=fetcher, retry_count=1,
    )
    assert first['ready_count'] == 2
    assert first['failed_dates'] == ['2026-01-02']
    assert calls == dates

    calls.clear()
    second = sync_wind_stock_yield_history(
        path, 'STOCK:601318', date_fetcher=lambda *_: dates,
        yield_fetcher=fetcher, retry_count=1,
    )
    assert second['ready_count'] == 2
    assert calls == ['2026-01-02']
    with connect(path) as db:
        rows = db.execute(
            'SELECT trade_date,status,value_pct FROM dividend_provider_yield_history '
            'WHERE security_id=? ORDER BY trade_date', ('STOCK:601318',)
        ).fetchall()
    assert [(r['trade_date'], r['status'], r['value_pct']) for r in rows] == [
        ('2026-01-01', 'READY', '3.5'),
        ('2026-01-02', 'FAILED', None),
        ('2026-01-03', 'READY', '4.0'),
    ]


def test_history_sync_only_queries_dates_after_last_successful_date(tmp_path):
    path = tmp_path / 'dividend.sqlite'
    seed_stock(path)
    dates = ['2026-01-01', '2026-01-02', '2026-01-03']
    with connect(path) as db:
        db.execute('''INSERT INTO dividend_provider_yield_history
            (security_id,trade_date,value_pct,provider,metric_label,source_sha256,
             fetched_at,status,reason)
            VALUES (?,?,?,?,?,?,?,?,?)''', (
                'STOCK:601318', '2026-01-01', '3.0',
                'wind:mcp:stock_fundamentals', 'Wind股息率（提供方口径）',
                'hash', '2026-01-02T00:00:00+00:00', 'READY', None,
        ))
    queried = []
    sync_wind_stock_yield_history(
        path, 'STOCK:601318', date_fetcher=lambda *_: dates,
        yield_fetcher=lambda code, market, trade_date: queried.append(trade_date) or {
            'value_pct': '4.0', 'as_of_date': trade_date,
            'metric_label': 'Wind股息率（提供方口径）',
            'provider': 'wind:mcp:stock_fundamentals', 'raw': {},
        }, retry_count=1,
    )
    assert queried == ['2026-01-02', '2026-01-03']
