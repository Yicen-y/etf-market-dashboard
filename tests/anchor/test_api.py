from fastapi.testclient import TestClient
from server import app
from scripts.anchor.api import load_snapshot
import hashlib
import json
import pytest
import sqlite3


def test_invalid_code_is_rejected():
    assert TestClient(app).get('/api/anchor/metrics?index_code=930903').status_code == 422


def test_events_rejects_invalid_mode():
    response = TestClient(app).get('/api/anchor/events?index_code=H20903&mode=unknown')
    assert response.status_code == 422


def test_published_snapshot_produces_separate_index_series():
    response = TestClient(app).get('/api/anchor/metrics?index_code=all')
    assert response.status_code == 200
    data = response.json()
    assert set(data['indexes']) == {'H20903', 'H00922'}
    assert data['indexes']['H20903']['rows'][-1]['tradeDate'] == data['indexes']['H00922']['rows'][-1]['tradeDate']
    assert data['indexes']['H20903']['provenance'] == 'LEGACY_UNVERIFIED'


def test_nikkei_anchor_is_labeled_as_price_index_not_total_return(monkeypatch):
    monkeypatch.setattr('scripts.anchor.api.read_nikkei_anchor_records', lambda _path: [
        {'tradeDate': '20261105', 'close': 51000.0, 'updatedAt': '2026-11-06T09:00:00'},
        {'tradeDate': '20261106', 'close': 51200.0, 'updatedAt': '2026-11-06T09:00:00'},
    ])
    response = TestClient(app).get('/api/anchor/metrics?index_code=nikkei225&ma_window=1250')
    assert response.status_code == 200
    data = response.json()
    item = data['indexes']['NKY225_TEMP']
    assert item['name'] == '日经225指数点位（Wind临时数据）'
    assert item['return_type'] == 'price_index'
    assert item['provenance'] == 'WIND_MCP_NAME_LOOKUP_UNVERIFIED_CODE'
    assert '不是日经全收益指数' in data['data_note']
    assert item['rows'][-1]['close'] > 10000


def test_backtest_pins_snapshot_and_rejects_unverified_tradeable_asset(monkeypatch, tmp_path):
    monkeypatch.setattr('scripts.anchor.api.DATABASE_PATH', tmp_path / 'test.db')
    snapshot, _ = load_snapshot()
    request = {'index_code':'H20903','strategy_mode':'DCA_ALWAYS','data_snapshot_id':snapshot['snapshot_id'], 'start_date':'2019-01-01','end_date':'2019-06-30','commission_rate':0.0,'slippage_rate':0.0}
    client = TestClient(app)
    first = client.post('/api/anchor/backtest', json=request)
    second = client.post('/api/anchor/backtest', json=request)
    assert first.status_code == 200
    assert first.json()['run_id'] == second.json()['run_id']
    assert first.json()['valuations'] == second.json()['valuations']
    saved = client.get('/api/anchor/backtest/' + first.json()['run_id'])
    assert saved.status_code == 200 and saved.json()['is_current_snapshot'] is True
    request['asset_mode'] = 'tradable_asset'
    assert client.post('/api/anchor/backtest', json=request).status_code == 422


def test_robustness_reports_training_and_testing_boundaries(monkeypatch, tmp_path):
    monkeypatch.setattr('scripts.anchor.api.DATABASE_PATH',tmp_path/'research.db')
    snapshot, _ = load_snapshot()
    request = {'index_code':'H00922','strategy_mode':'DCA_ANCHOR','data_snapshot_id':snapshot['snapshot_id'], 'start_date':'2019-01-01','end_date':'2021-12-31','commission_rate':.0003,'slippage_rate':.0005}
    response = TestClient(app).post('/api/anchor/robustness',json={'backtest':request,'train_days':200,'test_days':100,'quantile_window':20,'thresholds':[.1,.15]})
    assert response.status_code == 200, response.text
    data=response.json()
    assert len(data['sensitivity'])==2 and len(data['costStress'])==3
    assert data['walkForward']
    assert all(f['trainEnd'] < f['testStart'] for f in data['walkForward'])
    assert data['quantileBacktest']['status']=='READY'
    saved=TestClient(app).get('/api/anchor/robustness/'+data['run_id'])
    assert saved.status_code==200 and saved.json()['is_current_snapshot'] is True


def test_unresolved_quality_conflict_blocks_affected_window(monkeypatch, tmp_path):
    db=tmp_path/'quality.db'
    with sqlite3.connect(db) as con:
        con.execute('CREATE TABLE quality_issues(symbol TEXT, kind TEXT, trade_date TEXT, issue_code TEXT, severity TEXT, resolution_status TEXT)')
        con.execute("INSERT INTO quality_issues VALUES ('H20903','index','20200102','CONFLICT','BLOCKED','open')")
    monkeypatch.setattr('scripts.anchor.api.DATABASE_PATH',db)
    response=TestClient(app).get('/api/anchor/metrics?index_code=H20903')
    assert response.status_code==200
    result=response.json()['indexes']['H20903']
    assert '20200102' in result['blocked_dates']
    rows={r['tradeDate']:r for r in result['rows']}
    assert rows['20200102']['close'] is None
    assert rows['20200103']['ma'] is None and rows['20200103']['quality']=='BLOCKED'


@pytest.mark.parametrize('code,digest,price,ma,upper,lower', [
    ('H20903','de6e5e9ff43de48864d90d30d5680b7817a3dba023ff9ea52c5392d407131aeb',4775.04,4678.263688,5380.0032412,3976.5241348),
    ('H00922','1eb1a18812ee0c403fc6ca6a42cc22485883dd57710666d928b9babe9abf0065',12193.55,10174.499808,11700.6747792,8648.3248368),
])
def test_document_golden_values_only_when_input_hash_matches(code,digest,price,ma,upper,lower):
    response=TestClient(app).get('/api/anchor/metrics',params={'index_code':code})
    assert response.status_code == 200
    rows=response.json()['indexes'][code]['rows']
    history=[(r['tradeDate'],r['close']) for r in rows if r['tradeDate'] <= '20261030'][-1250:]
    actual=hashlib.sha256(json.dumps(history,separators=(',',':')).encode()).hexdigest()
    if actual != digest:
        pytest.skip('本地行情窗口已修订，旧黄金值不适用')
    row=next(r for r in rows if r['tradeDate']=='20261030')
    assert row['close'] == pytest.approx(price)
    assert row['ma'] == pytest.approx(ma)
    assert row['upper'] == pytest.approx(upper)
    assert row['lower'] == pytest.approx(lower)
