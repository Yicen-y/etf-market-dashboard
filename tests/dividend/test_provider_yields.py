from copy import deepcopy
from datetime import date

from scripts.dividend.db import connect, upsert_security
from scripts.dividend.provider_yields import (
    ETF_LABEL, ETF_PROVIDER, STOCK_LABEL, STOCK_PROVIDER,
    parse_htbr_etf_yield, parse_wind_stock_yield, provider_yield_detail,
    record_wind_stock_yield_observation, sync_provider_yield,
)


def _stock_payloads():
    snapshot = {'data': {'columns': [{'name': '最新交易日'}, {'name': 'Wind代码'}],
                         'rows': [['20261106', '600519.SH']]}, 'error': None}
    fundamentals = {'data': {'data': [{'columns': [
        {'name': 'Wind代码'}, {'name': '2026年11月6日股息率', 'unit': '%'}],
        'rows': [['600519.SH', 1.9287]]}]}, 'error': None}
    return snapshot, fundamentals


def test_wind_stock_yield_requires_dated_percent_unit_and_matching_security():
    snapshot, fundamentals = _stock_payloads()
    result = parse_wind_stock_yield(snapshot, fundamentals, '600519.SH')
    assert result['value_pct'] == '1.9287'
    assert result['as_of_date'] == '2026-11-06'
    bad = deepcopy(fundamentals)
    bad['data']['data'][0]['columns'][1].pop('unit')
    import pytest
    with pytest.raises(ValueError, match='百分比单位'):
        parse_wind_stock_yield(snapshot, bad, '600519.SH')
    bad = deepcopy(fundamentals)
    bad['data']['data'][0]['rows'][0][0] = '600000.SH'
    with pytest.raises(ValueError, match='标的'):
        parse_wind_stock_yield(snapshot, bad, '600519.SH')


def test_htbr_duplicate_report_date_conflict_is_not_silently_chosen():
    resolved = {'data': {'matchCount': 1, 'candidates': [
        {'secuCode': '510880', 'innerCode': '4787'}]}}
    valuation = {'data': {'innerCode': 4787, 'records': [
        {'fundcode': '510880', 'fundobject': 4787, 'reportdate': '2026-09-30',
         'dividendratio': 0.5694528359096013}]}}
    assert parse_htbr_etf_yield(resolved, valuation, '510880')['value_pct'] == '0.5694528359096013'
    valuation['data']['records'].append({**valuation['data']['records'][0], 'dividendratio': 1.0})
    import pytest
    with pytest.raises(ValueError, match='冲突'):
        parse_htbr_etf_yield(resolved, valuation, '510880')


def test_provider_sync_preserves_source_identity_and_failure_reason(tmp_path):
    path = tmp_path / 'providers.sqlite'
    upsert_security(path, {'security_id': 'STOCK:600519', 'code': '600519', 'name': '贵州茅台',
                           'market': 'SH', 'security_type': 'STOCK', 'aliases': ''})
    upsert_security(path, {'security_id': 'ETF:510880', 'code': '510880', 'name': '红利ETF',
                           'market': 'SH', 'security_type': 'ETF', 'aliases': ''})
    snapshot, fundamentals = _stock_payloads()
    stock_sample = parse_wind_stock_yield(snapshot, fundamentals, '600519.SH')
    stock_sample['as_of_date'] = date.today().isoformat()
    stock = sync_provider_yield(path, 'STOCK:600519', stock_fetcher=lambda *_: stock_sample)
    assert stock['status'] == 'READY' and stock['value_pct'] == '1.9287'
    assert stock['metric_label'] == STOCK_LABEL and stock['provider'] == STOCK_PROVIDER
    etf = sync_provider_yield(path, 'ETF:510880', etf_fetcher=lambda *_: {
        'value_pct': '0.5694528359096013', 'as_of_date': date.today().isoformat(),
        'provider': ETF_PROVIDER, 'metric_label': ETF_LABEL, 'raw': {'source': 'offline fixture'}})
    assert etf['status'] == 'READY' and etf['metric_label'] == ETF_LABEL
    failure = sync_provider_yield(path, 'ETF:510880', etf_fetcher=lambda *_: (_ for _ in ()).throw(
        RuntimeError('上游不可用')))
    assert failure['status'] == 'UNAVAILABLE' and failure['value_pct'] is None
    assert '上游不可用' in failure['reason']
    with connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM raw_source_records').fetchone()[0] == 2
        db.execute("UPDATE dividend_provider_yields SET as_of_date='2000-01-01' WHERE security_id='STOCK:600519'")
    stale = provider_yield_detail(path, 'STOCK:600519')
    assert stale['status'] == 'STALE' and stale['value_pct'] is None
    with connect(path) as db:
        db.execute('UPDATE dividend_provider_yields SET as_of_date=? WHERE security_id=?',
                   (date.today().isoformat(), 'STOCK:600519'))
    assert provider_yield_detail(path, 'STOCK:600519')['as_of_date'] == date.today().isoformat()


def test_wind_failure_preserves_existing_ready_provider_value(tmp_path):
    path = tmp_path / 'provider-failure.sqlite'
    upsert_security(path, {'security_id': 'STOCK:600519', 'code': '600519', 'name': '贵州茅台',
                           'market': 'SH', 'security_type': 'STOCK', 'aliases': ''})
    initial = sync_provider_yield(path, 'STOCK:600519', stock_fetcher=lambda *_: {
        'value_pct': '2.35', 'as_of_date': '2026-11-09',
        'provider': STOCK_PROVIDER, 'metric_label': STOCK_LABEL, 'raw': {'source': 'fixture'}})
    assert initial['status'] == 'READY'

    failed = sync_provider_yield(path, 'STOCK:600519', stock_fetcher=lambda *_: (_ for _ in ()).throw(
        RuntimeError('Wind暂时不可用')))

    assert failed['status'] == 'READY'
    assert failed['value_pct'] == '2.35'
    assert failed['as_of_date'] == '2026-11-09'
    assert failed['last_refresh_status'] == 'UNAVAILABLE'
    assert failed['last_refresh_reason'] == 'Wind暂时不可用'


def test_wind_failure_preserves_last_successful_fetch_timestamp(tmp_path):
    path = tmp_path / 'provider-failure-timestamp.sqlite'
    upsert_security(path, {'security_id': 'STOCK:600519', 'code': '600519', 'name': '贵州茅台',
                           'market': 'SH', 'security_type': 'STOCK', 'aliases': ''})
    with connect(path) as db:
        db.execute('''INSERT INTO dividend_provider_yields
            (security_id,value_pct,as_of_date,fetched_at,provider,metric_label,source_sha256,status,reason)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            ('STOCK:600519', '2.35', '2026-11-09', '2026-11-09T08:00:00+00:00',
             STOCK_PROVIDER, STOCK_LABEL, 'old-hash', 'READY', None))

    failed = sync_provider_yield(path, 'STOCK:600519', stock_fetcher=lambda *_: (_ for _ in ()).throw(
        RuntimeError('Wind暂时不可用')))

    assert failed['status'] == 'READY'
    with connect(path) as db:
        row = db.execute('''SELECT fetched_at,last_refresh_status,last_refresh_reason
            FROM dividend_provider_yields WHERE security_id=?''', ('STOCK:600519',)).fetchone()
    assert row['fetched_at'] == '2026-11-09T08:00:00+00:00'
    assert row['last_refresh_status'] == 'UNAVAILABLE'
    assert row['last_refresh_reason'] == 'Wind暂时不可用'


def test_successful_observation_repairs_failed_same_day_history(tmp_path):
    path = tmp_path / 'provider-history-repair.sqlite'
    upsert_security(path, {'security_id': 'STOCK:600519', 'code': '600519', 'name': '贵州茅台',
                           'market': 'SH', 'security_type': 'STOCK', 'aliases': ''})
    with connect(path) as db:
        db.execute('''INSERT INTO dividend_provider_yield_history
            (security_id,trade_date,value_pct,provider,metric_label,source_sha256,
             fetched_at,status,reason) VALUES (?,?,?,?,?,?,?,?,?)''',
            ('STOCK:600519', '2026-11-09', None, STOCK_PROVIDER, STOCK_LABEL,
             None, '2026-11-09T08:00:00+00:00', 'FAILED', 'Wind超时'))

    result = record_wind_stock_yield_observation(path, 'STOCK:600519', {
        'value_pct': '2.35', 'as_of_date': '2026-11-09',
        'provider': STOCK_PROVIDER, 'metric_label': STOCK_LABEL,
        'raw': {'source': 'fixture'},
    })

    assert result['status'] == 'READY'
    with connect(path) as db:
        row = db.execute('''SELECT value_pct,provider,metric_label,source_sha256,
            status,reason FROM dividend_provider_yield_history
            WHERE security_id=? AND trade_date=?''', ('STOCK:600519', '2026-11-09')).fetchone()
    assert row['value_pct'] == '2.35'
    assert row['provider'] == STOCK_PROVIDER
    assert row['metric_label'] == STOCK_LABEL
    assert row['source_sha256']
    assert row['status'] == 'READY'
    assert row['reason'] is None


def test_ready_same_day_observation_remains_idempotent(tmp_path):
    path = tmp_path / 'provider-history-idempotent.sqlite'
    upsert_security(path, {'security_id': 'STOCK:600519', 'code': '600519', 'name': '贵州茅台',
                           'market': 'SH', 'security_type': 'STOCK', 'aliases': ''})
    first = {'value_pct': '2.35', 'as_of_date': '2026-11-09',
             'provider': STOCK_PROVIDER, 'metric_label': STOCK_LABEL,
             'raw': {'source': 'first'}}
    second = {**first, 'value_pct': '9.99', 'raw': {'source': 'second'}}
    record_wind_stock_yield_observation(path, 'STOCK:600519', first)
    record_wind_stock_yield_observation(path, 'STOCK:600519', second)

    with connect(path) as db:
        row = db.execute('''SELECT value_pct,source_sha256,status,reason
            FROM dividend_provider_yield_history WHERE security_id=? AND trade_date=?''',
                         ('STOCK:600519', '2026-11-09')).fetchone()
    assert row['value_pct'] == '2.35'
    assert row['source_sha256']
    assert row['status'] == 'READY'
    assert row['reason'] is None
