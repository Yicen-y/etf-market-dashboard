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
    assert detail['ttm']['verification_status'] == 'mirror_only_official_url_unavailable'


def test_events_include_traceable_source_and_history_reports_missing_coverage():
    from server import app
    client = TestClient(app)
    events = client.get('/api/dividend/events/ETF:510880').json()
    assert events['items'][0]['source_url'].startswith('https://www.sse.com.cn/')
    history = client.get('/api/dividend/history/ETF:510880?range=1Y').json()
    assert history['query_mode'] == 'latest_verified'
    assert history['coverage_status'] == 'COMPLETE'
    assert history['rows']


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


def test_calendar_and_batch_sync_are_scoped_by_type():
    from server import app
    client = TestClient(app)
    calendar = client.get('/api/dividend/calendar?type=ETF&days=90').json()
    assert calendar['type'] == 'ETF'
    assert calendar['items'] == []
    batch = client.post('/api/dividend/sync-watchlist?type=ETF').json()
    assert batch['type'] == 'ETF'
    assert isinstance(batch['items'], list)
