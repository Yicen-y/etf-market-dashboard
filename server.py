from __future__ import annotations

import threading
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from scripts.config import DATA_PATH, INDEX_DATA_PATH
from scripts.update_data import update_dataset
from scripts.fund_flow.api import router as fund_flow_router
from scripts.dividend.api import build_router as build_dividend_router
from scripts.fund_flow.config import DATABASE_PATH


ROOT = Path(__file__).resolve().parent
app = FastAPI(title="ETF Market Dashboard Local Data Service")
app.mount("/web", StaticFiles(directory=ROOT / "web", html=True), name="web")
app.include_router(fund_flow_router)
app.include_router(build_dividend_router(DATABASE_PATH))
update_lock = threading.Lock()
status = {"state": "idle", "message": "尚未刷新", "updatedAt": None, "summary": None}


@app.get("/")
def home():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/health")
def health():
    manifest = _current_manifest() if (ROOT / "data" / "current_manifest.json").exists() else {"snapshot_id": "legacy"}
    return {"state": status["state"], "message": status["message"], "updatedAt": status["updatedAt"], "summary": status["summary"], "snapshot_id": manifest["snapshot_id"], "dataExists": DATA_PATH.exists() and INDEX_DATA_PATH.exists()}


def _current_manifest() -> dict:
    manifest_path = ROOT / "data" / "current_manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"snapshot_id": "legacy", "status": "legacy", "files": {"etf": "etf_prices.json", "index": "index_prices.json"}}


@app.get("/api/snapshot")
def snapshot():
    manifest = _current_manifest()
    return {"snapshot_id": manifest["snapshot_id"], "status": manifest.get("status"), "files": manifest.get("files", {})}


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
        status.update(state="success", message=message, updatedAt=updated_at, summary=summary)
        return health()
    except Exception as error:
        status.update(state="error", message=str(error), summary=None)
        raise HTTPException(status_code=502, detail=str(error)) from error
    finally:
        update_lock.release()
