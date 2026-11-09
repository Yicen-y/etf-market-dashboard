from fastapi import APIRouter, HTTPException

from .service import load_payload, refresh

router = APIRouter(prefix="/api/bond-value", tags=["bond-value"])


@router.get("/hs300")
def hs300():
    return load_payload()


@router.post("/refresh")
def refresh_hs300():
    try:
        return refresh()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"股债性价比数据刷新失败：{exc}") from exc
