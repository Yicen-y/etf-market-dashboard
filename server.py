from __future__ import annotations

from functools import lru_cache
import threading
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from scripts.rotation_overview import build_overview
from scripts.config import DATA_PATH, INDEX_DATA_PATH
from scripts.update_data import update_dataset
from scripts.fund_flow.api import router as fund_flow_router
from scripts.dividend.api import build_router as build_dividend_router
from scripts.dividend.research_api import router as dividend_research_router
from scripts.anchor.api import router as anchor_router
from scripts.bond_value.api import router as bond_value_router
from scripts.fund_flow.config import DATABASE_PATH
from scripts.wind_credentials import get_authorization


ROOT = Path(__file__).resolve().parent
app = FastAPI(title="ETF Market Dashboard Local Data Service")
app.mount("/web", StaticFiles(directory=ROOT / "web", html=True), name="web")
app.include_router(fund_flow_router)
app.include_router(build_dividend_router(DATABASE_PATH))
app.include_router(dividend_research_router)
app.include_router(anchor_router)
app.include_router(bond_value_router)
update_lock = threading.Lock()
status = {"state": "idle", "message": "尚未刷新", "updatedAt": None, "summary": None}


@app.get("/")
def home():
    return RedirectResponse("/web/overview.html")


@app.get("/api/health")
def health():
    manifest = _current_manifest() if (ROOT / "data" / "current_manifest.json").exists() else {"snapshot_id": "legacy"}
    return {"state": status["state"], "message": status["message"], "updatedAt": status["updatedAt"], "summary": status["summary"], "snapshot_id": manifest["snapshot_id"], "dataExists": DATA_PATH.exists() and INDEX_DATA_PATH.exists()}


@app.get("/api/wind/status")
def wind_status():
    return {"configured": bool(get_authorization()), "endpoint": os.environ.get("WIND_MCP_URL", "https://mcp.wind.com.cn/vserver_wind_tools/mcp/"), "credentialValue": None}


def _current_manifest() -> dict:
    manifest_path = ROOT / "data" / "current_manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"snapshot_id": "legacy", "status": "legacy", "files": {"etf": "etf_prices.json", "index": "index_prices.json"}}


@app.get("/api/snapshot")
def snapshot():
    manifest = _current_manifest()
    return {"snapshot_id": manifest["snapshot_id"], "status": manifest.get("status"), "files": manifest.get("files", {})}


@lru_cache(maxsize=1)
def _rotation_overview(snapshot_id: str, index_file: str, etf_file: str):
    root = (ROOT / "data").resolve()
    payloads = []
    for filename in (index_file, etf_file):
        path = (root / filename).resolve()
        if not path.is_relative_to(root):
            raise ValueError("快照文件路径无效")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("snapshot_id") != snapshot_id:
            raise ValueError("快照数据版本不一致")
        payloads.append(payload)
    return build_overview(snapshot_id, *payloads)


@app.get("/api/rotation/overview")
def rotation_overview():
    try:
        manifest = _current_manifest()
        return _rotation_overview(manifest["snapshot_id"], manifest["files"]["index"], manifest["files"]["etf"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(503, detail="当前快照无法生成轮动总览") from error


@app.get("/api/snapshot/data/{dataset_name}")
def snapshot_data(dataset_name: str, snapshot_id: Optional[str] = None):
    if dataset_name not in {"etf_prices.json", "index_prices.json"}:
        raise HTTPException(status_code=404, detail="dataset not found")
    manifest = _current_manifest()
    requested = snapshot_id or manifest["snapshot_id"]
    if requested != manifest["snapshot_id"] and requested != "legacy":
        raise HTTPException(status_code=409, detail="snapshot is not the current published snapshot")
    if requested == "legacy":
        path = DATA_PATH if dataset_name.startswith("etf") else INDEX_DATA_PATH
    else:
        key = "etf" if dataset_name.startswith("etf") else "index"
        path = ROOT / "data" / manifest["files"][key]
        data_root = (ROOT / "data").resolve()
        if os.path.commonpath([str(data_root), str(path.resolve())]) != str(data_root):
            raise HTTPException(status_code=500, detail="invalid snapshot path")
    if not path.exists():
        raise HTTPException(status_code=404, detail="snapshot dataset not found")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


@app.post("/api/update")
def update():
    if not update_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="数据正在更新，请稍候。")
    status.update(state="updating", message="正在刷新全部 ETF、指数和策略数据……", summary=None)
    try:
        summary = update_dataset()
        updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
        message = f"全部数据刷新成功：{summary['etfCount']} 个 ETF、{summary['indexCount']} 个指数，覆盖 {summary['strategyCount']} 个看板"
        nikkei = summary.get("nikkeiAnchor", {})
        if nikkei.get("status") == "UPDATED":
            message += f"；日经五年之锚新增 {nikkei.get('inserted', 0)} 个、复核更新 {nikkei.get('replaced', 0)} 个交易日"
        elif nikkei.get("status") == "SKIPPED_NO_CREDENTIAL":
            message += "；日经基准已存库，增量更新跳过（未配置Wind凭证）"
        elif nikkei.get("status") == "ERROR":
            message += "；日经增量更新失败，其他数据已正常发布"
        status.update(state="success", message=message, updatedAt=updated_at, summary=summary)
        return health()
    except Exception as error:
        status.update(state="error", message=str(error), summary=None)
        raise HTTPException(status_code=502, detail=str(error)) from error
    finally:
        update_lock.release()
