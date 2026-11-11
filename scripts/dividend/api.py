from pathlib import Path
from fastapi import APIRouter, HTTPException, Query

from .db import add_watchlist, list_watchlist, remove_watchlist, search
from .catalog import catalog_status
from .announcement_sync import candidate_detail
from .provider_yields import (sync_provider_yield, provider_yield_history_detail,
                              record_wind_stock_yield_observation, STOCK_PROVIDER)
from .etfirst_yield_list import etfirst_yield_page
from .service import ensure_seed, yield_detail, event_detail, history_detail, calendar_detail, sync_watchlist, sync_security


def build_router(database_path: Path) -> APIRouter:
    ensure_seed(database_path)
    router = APIRouter(prefix='/api/dividend', tags=['dividend'])

    @router.get('/search')
    def dividend_search(type: str = Query(...), q: str = ''):
        if type not in {'ETF', 'STOCK'}:
            raise HTTPException(400, 'type must be ETF or STOCK')
        return {'items': [dict(row) for row in search(database_path, type, q)]}

    @router.get('/catalog-status')
    def dividend_catalog_status():
        return catalog_status(database_path)

    @router.get('/etfirst-yields')
    def etfirst_yields(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
        return etfirst_yield_page(database_path, page, page_size)

    @router.get('/watchlist')
    def dividend_watchlist(type: str = Query(...)):
        return {'items': [dict(row) for row in list_watchlist(database_path, type)]}

    @router.post('/watchlist')
    def add(item: dict):
        security_id = item.get('security_id', '')
        if not security_id or not yield_detail(database_path, security_id):
            raise HTTPException(404, '证券不存在')
        add_watchlist(database_path, security_id)
        return {'ok': True, 'security_id': security_id}

    @router.delete('/watchlist/{security_id}')
    def remove(security_id: str):
        remove_watchlist(database_path, security_id)
        return {'ok': True}

    @router.get('/yields/{security_id}')
    def yields(security_id: str):
        result = yield_detail(database_path, security_id)
        if result is None:
            raise HTTPException(404, '证券不存在')
        return result

    @router.post('/provider-yields/{security_id}/refresh')
    def refresh_provider_yield(security_id: str):
        if yield_detail(database_path, security_id) is None:
            raise HTTPException(404, '证券不存在')
        try:
            result = sync_provider_yield(database_path, security_id)
        except Exception as error:
            raise HTTPException(502, f'Wind股息率刷新失败：{error}') from error
        if (result.get('provider') == STOCK_PROVIDER and
                result.get('status') == 'READY' and
                result.get('value_pct') is not None and
                result.get('as_of_date')):
            result['history_observation'] = record_wind_stock_yield_observation(
                database_path, security_id, result)
        return result

    @router.get('/provider-yields/{security_id}/history')
    def provider_yield_history(security_id: str):
        result = provider_yield_history_detail(database_path, security_id)
        if result is None:
            raise HTTPException(404, '证券不存在')
        return result

    @router.get('/events/{security_id}')
    def events(security_id: str):
        result = yield_detail(database_path, security_id)
        if result is None:
            raise HTTPException(404, '证券不存在')
        return event_detail(database_path, security_id)

    @router.get('/announcement-candidates/{security_id}')
    def announcement_candidates(security_id: str):
        if yield_detail(database_path, security_id) is None:
            raise HTTPException(404, '证券不存在')
        return candidate_detail(database_path, security_id)

    @router.get('/calendar')
    def calendar(type: str = Query(...), days: int = Query(90, ge=1, le=90)):
        if type not in {'ETF', 'STOCK'}:
            raise HTTPException(400, 'type must be ETF or STOCK')
        return calendar_detail(database_path, type, days)

    @router.get('/history/{security_id}')
    def history(security_id: str, range: str = Query('1Y', pattern='^(1Y|3Y|5Y)$'), query_mode: str = Query('latest_verified')):
        if query_mode not in {'latest_verified', 'as_known'}:
            raise HTTPException(400, 'unsupported query_mode')
        result = history_detail(database_path, security_id, range, query_mode)
        if result is None:
            raise HTTPException(404, '证券不存在')
        return result

    @router.post('/sync-watchlist')
    def sync_batch(type: str = Query(...)):
        if type not in {'ETF', 'STOCK'}:
            raise HTTPException(400, 'type must be ETF or STOCK')
        return sync_watchlist(database_path, type)

    @router.post('/sync/{security_id}')
    def sync_one(security_id: str):
        result = sync_security(database_path, security_id)
        if result is None:
            raise HTTPException(404, '证券不存在')
        return result

    return router
