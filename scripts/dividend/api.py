from pathlib import Path
from fastapi import APIRouter, HTTPException, Query

from .db import add_watchlist, list_watchlist, remove_watchlist, search
from .service import ensure_seed, yield_detail, event_detail, history_detail, sync_watchlist, sync_security


def build_router(database_path: Path) -> APIRouter:
    ensure_seed(database_path)
    router = APIRouter(prefix='/api/dividend', tags=['dividend'])

    @router.get('/search')
    def dividend_search(type: str = Query(...), q: str = ''):
        if type not in {'ETF', 'STOCK'}:
            raise HTTPException(400, 'type must be ETF or STOCK')
        return {'items': [dict(row) for row in search(database_path, type, q)]}

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

    @router.get('/events/{security_id}')
    def events(security_id: str):
        result = yield_detail(database_path, security_id)
        if result is None:
            raise HTTPException(404, '证券不存在')
        return event_detail(database_path, security_id)

    @router.get('/calendar')
    def calendar(type: str = Query(...), days: int = 90):
        if type not in {'ETF', 'STOCK'}:
            raise HTTPException(400, 'type must be ETF or STOCK')
        return {'items': [], 'type': type, 'days': days, 'note': '仅返回已确认除息日期；预案日期不虚构'}

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
