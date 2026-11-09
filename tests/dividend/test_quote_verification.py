import json
from decimal import Decimal

import pytest

from scripts.dividend.db import connect, upsert_security
from scripts.dividend.quote_verification import parse_wind_kline, sync_verified_quotes


def security(path):
    upsert_security(path, {'security_id': 'ETF:510880', 'code': '510880', 'name': '红利ETF',
                           'market': 'SH', 'security_type': 'ETF', 'aliases': ''})


def test_wind_parser_requires_explicit_close_column_and_valid_dates():
    payload = {'data': {'columns': [{'name': 'TIME'}, {'name': 'MATCH'}],
                        'rows': [['2026-11-06T00:00:00.000+08:00', '3.371']]}, 'error': None}
    result = {'content': [{'type': 'text', 'text': json.dumps(payload)}]}
    from datetime import date
    assert parse_wind_kline(result, date(2026, 11, 6), date(2026, 11, 6)) == {
        '2026-11-06': Decimal('3.371')}
    payload['data']['columns'][1]['name'] = 'AVPRICE'
    with pytest.raises(ValueError, match='收盘价'):
        parse_wind_kline({'content': [{'type': 'text', 'text': json.dumps(payload)}]},
                         date(2026, 11, 6), date(2026, 11, 6))


def test_only_matching_unadjusted_quotes_are_promoted_and_source_failures_preserve_old_data(tmp_path):
    path = tmp_path / 'quotes.sqlite'
    security(path)
    wind = {'2026-11-05': Decimal('3.348'), '2026-11-06': Decimal('3.371')}
    akshare = {'2026-11-05': Decimal('3.34800'), '2026-11-06': Decimal('3.37000')}
    first = sync_verified_quotes(path, 'ETF:510880', '2026-11-05', '2026-11-06',
        wind_fetcher=lambda *_: wind, akshare_fetcher=lambda *_: akshare)
    assert first['counts'] == {'MATCH': 1, 'MISMATCH': 1, 'WIND_ONLY': 0, 'AKSHARE_ONLY': 0}
    with connect(path) as db:
        assert db.execute('SELECT trade_date,price,verification_level FROM dividend_quotes').fetchall()[0][:] == (
            '2026-11-05', '3.348', 'VERIFIED_UNADJUSTED')
        assert db.execute('SELECT COUNT(*) FROM dividend_quotes').fetchone()[0] == 1
    with pytest.raises(RuntimeError, match='offline'):
        sync_verified_quotes(path, 'ETF:510880', '2026-11-05', '2026-11-06',
            wind_fetcher=lambda *_: (_ for _ in ()).throw(RuntimeError('offline')),
            akshare_fetcher=lambda *_: akshare)
    with connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM dividend_quotes').fetchone()[0] == 1
    akshare['2026-11-06'] = Decimal('3.371')
    second = sync_verified_quotes(path, 'ETF:510880', '2026-11-05', '2026-11-06',
        wind_fetcher=lambda *_: wind, akshare_fetcher=lambda *_: akshare)
    assert second['status'] == 'VERIFIED'
    with connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM dividend_quotes').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM raw_source_records').fetchone()[0] == 3


def test_extra_source_date_is_not_promoted(tmp_path):
    path = tmp_path / 'calendar.sqlite'
    security(path)
    result = sync_verified_quotes(path, 'ETF:510880', '2026-11-05', '2026-11-06',
        wind_fetcher=lambda *_: {'2026-11-06': Decimal('3.371')},
        akshare_fetcher=lambda *_: {'2026-11-05': Decimal('3.348'), '2026-11-06': Decimal('3.371')})
    assert result['counts']['AKSHARE_ONLY'] == 1
    with connect(path) as db:
        assert db.execute('SELECT trade_date FROM dividend_quotes').fetchone()[0] == '2026-11-06'


def test_new_conflict_or_missing_source_revokes_prior_quote_verification(tmp_path):
    path = tmp_path / 'revocation.sqlite'
    security(path)
    wind = {'2026-11-05': Decimal('3.348'), '2026-11-06': Decimal('3.371')}
    akshare = dict(wind)
    sync_verified_quotes(path, 'ETF:510880', '2026-11-05', '2026-11-06',
        wind_fetcher=lambda *_: wind, akshare_fetcher=lambda *_: akshare)
    del akshare['2026-11-05']
    akshare['2026-11-06'] = Decimal('3.370')
    result = sync_verified_quotes(path, 'ETF:510880', '2026-11-05', '2026-11-06',
        wind_fetcher=lambda *_: wind, akshare_fetcher=lambda *_: akshare)
    assert result['counts'] == {'MATCH': 0, 'MISMATCH': 1, 'WIND_ONLY': 1, 'AKSHARE_ONLY': 0}
    with connect(path) as db:
        assert [r[0] for r in db.execute('SELECT verification_level FROM dividend_quotes ORDER BY trade_date')] == [
            'UNVERIFIED', 'UNVERIFIED']
