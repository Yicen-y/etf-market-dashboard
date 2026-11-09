import hashlib

import pandas as pd
import pytest

from scripts.dividend.catalog import catalog_status, normalize_catalog, sync_catalog
from scripts.dividend.db import connect, search


def frames():
    return {'STOCK': pd.DataFrame([{'代码': '600519', '名称': '贵州茅台'},
                                    {'代码': '000001', '名称': '平安银行'},
                                    {'代码': '920085', '名称': '北交所样例'}]),
            'ETF': pd.DataFrame([{'代码': '510880', '名称': '红利ETF'},
                                  {'代码': '520610', '名称': '跨境ETF'},
                                  {'代码': '159915', '名称': '创业板ETF'}])}


def test_catalog_import_is_searchable_typed_idempotent_and_auditable(tmp_path):
    db = tmp_path / 'catalog.sqlite'
    raw = tmp_path / 'raw'
    first = sync_catalog(db, raw, frames(), minimums={'STOCK': 3, 'ETF': 2})
    second = sync_catalog(db, raw, frames(), minimums={'STOCK': 3, 'ETF': 2})
    assert first['sha256'] == second['sha256']
    assert catalog_status(db)['stock_count'] == 3
    assert hashlib.sha256((raw / (first['sha256'] + '.json')).read_bytes()).hexdigest() == first['sha256']
    assert search(db, 'STOCK', '茅台')[0]['security_id'] == 'STOCK:600519'
    assert search(db, 'ETF', '510880')[0]['market'] == 'SH'
    assert search(db, 'STOCK', '510880') == []
    assert search(db, 'ETF', '520610')[0]['market'] == 'SH'
    with connect(db) as connection:
        assert connection.execute('SELECT COUNT(*) FROM dividend_securities').fetchone()[0] == 6
        assert connection.execute('SELECT COUNT(*) FROM dividend_catalog_batches').fetchone()[0] == 1


def test_short_or_ambiguous_catalog_does_not_mutate_database(tmp_path):
    db = tmp_path / 'catalog.sqlite'
    with pytest.raises(ValueError, match='低于完整性门槛'):
        sync_catalog(db, tmp_path / 'raw', frames(), minimums={'STOCK': 10, 'ETF': 2})
    assert not db.exists()
    ambiguous = pd.DataFrame([{'代码': '600519', '名称': 'A'}, {'代码': '600519', '名称': 'B'}])
    with pytest.raises(ValueError, match='不同名称'):
        normalize_catalog(ambiguous, 'STOCK')
