from fastapi.testclient import TestClient


def test_search_is_type_filtered():
    from server import app
    client = TestClient(app)
    assert client.get('/api/dividend/search', params={'type': 'ETF', 'q': '510880'}).json()['items'][0]['security_type'] == 'ETF'
    assert client.get('/api/dividend/search', params={'type': 'ETF', 'q': '600519'}).json()['items'] == []


def test_watchlist_is_idempotent_and_detail_blocks_unverified_stock_yield():
    from server import app
    client = TestClient(app)
    response = client.post('/api/dividend/watchlist', json={'security_id': 'ETF:510880'})
    assert response.status_code == 200
    client.post('/api/dividend/watchlist', json={'security_id': 'ETF:510880'})
    rows = client.get('/api/dividend/watchlist', params={'type': 'ETF'}).json()['items']
    assert [item['security_id'] for item in rows].count('ETF:510880') == 1
    detail = client.get('/api/dividend/yields/STOCK:600519').json()
    assert detail['ttm']['value_pct'] is None
    assert detail['ttm']['coverage_status'] == 'INCOMPLETE'
    assert detail['ttm']['verification_status'] == 'INCOMPLETE_EVIDENCE'


def test_events_include_traceable_source_and_history_reports_missing_coverage():
    from server import app
    client = TestClient(app)
    events = client.get('/api/dividend/events/ETF:510880').json()
    assert events['items'][0]['source_url'].startswith('https://www.sse.com.cn/')
    assert events['items'][0]['verification_status'] == 'OFFICIAL_VERIFIED'
    history = client.get('/api/dividend/history/ETF:510880?range=1Y').json()
    assert history['query_mode'] == 'latest_verified'
    assert history['coverage_status'] == 'INCOMPLETE'
    assert all(row['ttm_pct'] is None for row in history['rows'])


def test_akshare_announcement_candidates_are_separate_from_verified_events(tmp_path):
    from fastapi import FastAPI
    from scripts.dividend.api import build_router
    from scripts.dividend.db import upsert_security
    from scripts.dividend.announcement_sync import sync_candidates
    db = tmp_path / 'data' / 'test.sqlite'
    upsert_security(db, {'security_id': 'ETF:510880', 'code': '510880', 'name': '红利ETF',
                         'market': 'SH', 'security_type': 'ETF', 'aliases': ''})
    sync_candidates(db, 'ETF:510880', db.parent / 'raw' / 'dividend' / 'announcements',
                    download_etf_pdfs=False, fetcher=lambda _: [{
                        'report_id': 'AN202601151817055507', 'announced_at': '2026-01-16',
                        'title': '分红公告', 'verification_level': 'UNVERIFIED'}])
    app = FastAPI()
    app.include_router(build_router(db))
    client = TestClient(app)
    response = client.get('/api/dividend/announcement-candidates/ETF:510880')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'CANDIDATES_ONLY'
    assert data['items']
    assert all(row['verification_level'] == 'UNVERIFIED' for row in data['items'])
    assert all('local_file' not in row for row in data['items'])
    assert client.get('/api/dividend/yields/ETF:510880').json()['ttm']['value_pct'] is None


def test_yield_never_uses_placeholder_price():
    from server import app
    client = TestClient(app)
    detail = client.get('/api/dividend/yields/ETF:510880').json()
    assert detail['ttm']['denominator_price'] != '2.00000'
    assert detail['ttm']['price_trade_date'] is not None


def test_detail_exposes_three_metric_groups_and_deduplicated_events():
    from server import app
    client = TestClient(app)
    detail = client.get('/api/dividend/yields/ETF:510880').json()
    assert {'ttm', 'annual_reference', 'confirmed', 'proposal'} <= set(detail)
    events = client.get('/api/dividend/events/ETF:510880').json()['items']
    keys = [(item.get('ex_date'), item.get('amount_per_unit')) for item in events]
    assert len(keys) == len(set(keys))


def test_calendar_and_batch_sync_are_scoped_by_type(monkeypatch):
    from scripts.dividend import service
    monkeypatch.setattr(service, 'sync_security', lambda path, security_id: {
        'security_id': security_id, 'status': 'incomplete', 'reason': 'offline fixture'})
    from server import app
    client = TestClient(app)
    calendar = client.get('/api/dividend/calendar?type=ETF&days=90').json()
    assert calendar['type'] == 'ETF'
    assert calendar['items'] == []
    batch = client.post('/api/dividend/sync-watchlist?type=ETF').json()
    assert batch['type'] == 'ETF'
    assert isinstance(batch['items'], list)


def test_candidate_sync_does_not_promote_unverified_dividend(monkeypatch, tmp_path):
    from datetime import date
    from decimal import Decimal
    from scripts.dividend import service
    from scripts.dividend.db import upsert_security, connect

    db = tmp_path / 'candidate.sqlite'
    upsert_security(db, {'security_id': 'ETF:510880', 'code': '510880', 'name': '红利ETF',
                         'market': 'SH', 'security_type': 'ETF', 'aliases': ''})
    monkeypatch.setattr(service, 'fetch_security_snapshot', lambda *args: {
        'quotes': [('ETF:510880', date(2026, 11, 6), Decimal('2'))],
        'dividends': [{'event_id': 'candidate', 'status': 'PAID'}], 'provider': 'Wind candidate'})
    monkeypatch.setattr(service, 'sync_candidates', lambda *args: {
        'status': 'CANDIDATES_ONLY', 'count': 1, 'pdf_count': 1})
    monkeypatch.setattr(service, 'sync_provider_yield', lambda *args: {
        'status': 'UNAVAILABLE', 'value_pct': None, 'reason': 'offline fixture'})
    result = service.sync_security(db, 'ETF:510880')
    assert result['status'] == 'incomplete'
    assert result['candidate_event_count'] == 1
    assert result['announcement_pdf_count'] == 1
    with connect(db) as connection:
        assert connection.execute('SELECT COUNT(*) FROM dividend_events').fetchone()[0] == 0
        assert connection.execute('SELECT COUNT(*) FROM dividend_quotes').fetchone()[0] == 0


def test_provider_yield_refresh_is_scoped_to_known_security(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from scripts.dividend import api
    from scripts.dividend.db import upsert_security

    db = tmp_path / 'test.sqlite'
    upsert_security(db, {'security_id': 'STOCK:600519', 'code': '600519', 'name': '贵州茅台',
                         'market': 'SH', 'security_type': 'STOCK', 'aliases': ''})
    monkeypatch.setattr(api, 'sync_provider_yield', lambda path, security_id: {
        'security_id': security_id, 'status': 'READY', 'value_pct': '1.9287'})
    app = FastAPI()
    app.include_router(api.build_router(db))
    client = TestClient(app)
    assert client.post('/api/dividend/provider-yields/STOCK:600519/refresh').json()['value_pct'] == '1.9287'
    assert client.post('/api/dividend/provider-yields/STOCK:000001/refresh').status_code == 404


def test_provider_yield_history_endpoint_returns_percentile_and_rows(tmp_path):
    from fastapi import FastAPI
    from scripts.dividend.api import build_router
    from scripts.dividend.db import connect, upsert_security

    db = tmp_path / 'history.sqlite'
    upsert_security(db, {'security_id': 'STOCK:601318', 'code': '601318', 'name': '中国平安',
                         'market': 'SH', 'security_type': 'STOCK', 'aliases': '平安'})
    with connect(db) as connection:
        connection.executemany('''INSERT INTO dividend_provider_yield_history
            (security_id,trade_date,value_pct,provider,metric_label,source_sha256,
             fetched_at,status,reason) VALUES (?,?,?,?,?,?,?,?,?)''', [
            ('STOCK:601318', '2026-01-01', '2.0', 'wind:mcp:stock_fundamentals', 'Wind股息率（提供方口径）', 'a', 'now', 'READY', None),
            ('STOCK:601318', '2026-01-02', '4.0', 'wind:mcp:stock_fundamentals', 'Wind股息率（提供方口径）', 'b', 'now', 'READY', None),
            ('STOCK:601318', '2026-01-03', None, 'wind:mcp:stock_fundamentals', 'Wind股息率（提供方口径）', None, 'now', 'FAILED', 'timeout'),
        ])
    app = FastAPI()
    app.include_router(build_router(db))
    response = TestClient(app).get('/api/dividend/provider-yields/STOCK:601318/history')
    assert response.status_code == 200
    payload = response.json()
    assert payload['summary']['sample_count'] == 2
    assert payload['summary']['percentile'] == '100.0000'
    assert payload['missing_dates'] == ['2026-01-03']


def test_provider_refresh_returns_json_error_when_history_sync_crashes(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from scripts.dividend import api
    from scripts.dividend.api import build_router
    from scripts.dividend.db import upsert_security

    db = tmp_path / 'refresh-error.sqlite'
    upsert_security(db, {'security_id': 'STOCK:601318', 'code': '601318', 'name': '中国平安',
                         'market': 'SH', 'security_type': 'STOCK', 'aliases': ''})
    monkeypatch.setattr(api, 'sync_provider_yield', lambda *args: {
        'security_id': 'STOCK:601318', 'provider': 'wind:mcp:stock_fundamentals', 'status': 'READY'})
    monkeypatch.setattr(api, 'sync_wind_stock_yield_history',
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('Wind网关超时')))
    app = FastAPI()
    app.include_router(build_router(db))
    response = TestClient(app).post('/api/dividend/provider-yields/STOCK:601318/refresh')
    assert response.status_code == 502
    assert response.json()['detail'] == 'Wind历史股息率同步失败：Wind网关超时'
