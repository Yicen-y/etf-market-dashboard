from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from scripts.config import DATA_PATH, INDEX_DATA_PATH
from scripts.update_data import update_dataset


ROOT = Path(__file__).resolve().parent
app = FastAPI(title="ETF Market Dashboard Local Data Service")
app.mount("/web", StaticFiles(directory=ROOT / "web", html=True), name="web")
app.mount("/data", StaticFiles(directory=ROOT / "data"), name="data")
update_lock = threading.Lock()
status = {"state": "idle", "message": "尚未刷新", "updatedAt": None, "summary": None}


@app.get("/")
def home():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/health")
def health():
    return {"state": status["state"], "message": status["message"], "updatedAt": status["updatedAt"], "summary": status["summary"], "dataExists": DATA_PATH.exists() and INDEX_DATA_PATH.exists()}


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
