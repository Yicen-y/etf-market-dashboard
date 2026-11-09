from datetime import date

import pytest

from scripts.dividend.db import upsert_security
from scripts.dividend.etfirst_yield_list import etfirst_yield_page, parse_etfirst_page


def _response():
    day = date.today().strftime('%Y%m%d')
    return {'code': '00000', 'message': 'success', 'data': {'totalRows': 2, 'dataList': [
        {'prodCd': '510880', 'prodName': '红利ETF', 'indexCd': '000015',
         'indexName': '上证红利指数', 'dp': 3.95, 'peDate': day},
        {'prodCd': '511380', 'prodName': '可转债ETF', 'indexCd': '931078',
         'indexName': '中证转债及可交换债', 'dp': None, 'peDate': None}]}}


def test_etfirst_list_retains_index_identity_and_missing_value(tmp_path):
    path = tmp_path / 'list.sqlite'
    upsert_security(path, {'security_id': 'ETF:510880', 'code': '510880', 'name': '红利ETF',
                           'market': 'SH', 'security_type': 'ETF', 'aliases': ''})
    result = etfirst_yield_page(path, 1, 20, fetcher=lambda *_: _response())
    assert result['status'] == 'READY' and result['total_rows'] == 2
    assert result['items'][0]['value_pct'] == '3.95'
    assert result['items'][0]['index_code'] == '000015'
    assert result['items'][0]['in_local_catalog'] is True
    assert result['items'][1]['value_pct'] is None
    assert result['items'][1]['in_local_catalog'] is False
    assert result['items'][1]['reason']
    assert len(result['source_sha256']) == 64


def test_etfirst_rejects_bad_dates_and_provider_errors(tmp_path):
    payload = _response()
    payload['data']['dataList'][0]['peDate'] = 'not-a-day'
    with pytest.raises(ValueError, match='日期'):
        parse_etfirst_page(payload, 1, 20)
    result = etfirst_yield_page(tmp_path / 'db.sqlite', 1, 20,
                                fetcher=lambda *_: {'code': 'AUTH_ERROR', 'message': 'error'})
    assert result['status'] == 'UNAVAILABLE' and result['items'] == []
    assert result['reason']
