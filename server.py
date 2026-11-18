from __future__ import annotations

from contextlib import asynccontextmanager
import threading
import hashlib
import json
import os
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from scripts.rotation_overview import build_overview
from scripts.index_view import project_index_view
from scripts.config import DATA_ROOT, DATA_PATH, INDEX_DATA_PATH
from scripts.update_data import update_dataset
from scripts.daily_verified import run_daily
from scripts.fund_flow.api import router as fund_flow_router
from scripts.dividend.api import build_router as build_dividend_router
from scripts.dividend.research_api import router as dividend_research_router
from scripts.anchor.api import router as anchor_router
from scripts.bond_value.api import router as bond_value_router
from scripts.fund_flow.config import DATABASE_PATH
from scripts.wind_credentials import get_authorization
from scripts import credential_settings
from scripts.ifind import fetch_index_history as fetch_ifind_index_history
from scripts.industry_rotation import catalog as industry_rotation_catalog, prism as industry_rotation_prism
from scripts.snapshot import read_manifest, read_dataset
from scripts.storage import corroborating_raw_matches, recover_prepared_release
from scripts.data_center import build_data_center
from scripts.data_center_detail import read_index_detail
from scripts.index_verification import read_data_center_verification
from scripts.source_approvals import record_approval
from scripts.etf_corroboration import fetch_htbr_closes
from scripts.jobs import claim_job, get_job, get_job_detail, heartbeat_job, recent_jobs, record_dataset_result, set_job
import sqlite3
from functools import lru_cache
from scripts.snapshot import resolve_file


ROOT = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from scripts.update_data import _exclusive_update
    try:
        with _exclusive_update(DATA_ROOT):
            recover_prepared_release(DATA_ROOT, DATABASE_PATH)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        pass  # /api/ready reports an unresolved prepared release.
    yield


app = FastAPI(title="ETF Market Dashboard Local Data Service", lifespan=lifespan)
app.mount("/web", StaticFiles(directory=ROOT / "web", html=True), name="web")
app.include_router(fund_flow_router)
app.include_router(build_dividend_router(DATABASE_PATH))
app.include_router(dividend_research_router)
app.include_router(anchor_router)
app.include_router(bond_value_router)
update_lock = threading.Lock()
status = {"state": "idle", "message": "尚未刷新", "updatedAt": None, "summary": None}


def _local_admin(request: Request) -> None:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=403, detail="management endpoint requires local access")


@app.middleware("http")
async def protect_mutations(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        try:
            _local_admin(request)
        except HTTPException:
            return JSONResponse({"detail": "management endpoint requires local access"}, status_code=403)
    return await call_next(request)


@app.get("/api/data-center")
def data_center():
    return build_data_center(DATA_ROOT, DATABASE_PATH)


@app.get("/api/data-center/index-verification")
def index_verification_status():
    return read_data_center_verification(DATABASE_PATH)


@app.get("/api/data-center/indexes/{code}")
def data_center_index_detail(code: str, quality_status: Optional[str] = None, limit: int = 200):
    try:
        return read_index_detail(DATABASE_PATH, code, status=quality_status, limit=limit)
    except KeyError as exc:
        raise HTTPException(404, detail="未知指数代码") from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, detail="核验明细暂不可读") from exc


@app.get("/api/data-center/issues/{issue_id}")
def source_issue_detail(issue_id: int):
    with sqlite3.connect(DATABASE_PATH.as_uri() + "?mode=ro", uri=True) as connection:
        issue = connection.execute("""SELECT symbol,kind,batch_id,issue_code FROM quality_issues
            WHERE issue_id=? AND resolution_status='open'""", (issue_id,)).fetchone()
        if not issue or issue[1] != "etf":
            raise HTTPException(404, detail="未找到待审核 ETF 数据")
        symbol, _, batch, issue_code = issue
        candidates = connection.execute("""SELECT trade_date,value_raw FROM raw_observations
            WHERE symbol=? AND kind='etf' AND fetch_batch_id=? AND upstream_publisher='Sina'
            GROUP BY trade_date,value_raw ORDER BY trade_date""", (symbol, batch)).fetchall()
        published = dict(connection.execute("""SELECT trade_date,close_price FROM etf_prices
            WHERE product_code=? AND trade_date BETWEEN ? AND ?""",
            (symbol, candidates[0][0], candidates[-1][0])).fetchall()) if candidates else {}
    if not candidates:
        raise HTTPException(404, detail="候选数据已不可用")
    try:
        reference, _ = fetch_htbr_closes(symbol, candidates[0][0], candidates[-1][0])
        reference_status = "华泰柏瑞场内不复权收盘价已读取"
    except (RuntimeError, ValueError, KeyError, TypeError, OSError):
        reference, reference_status = {}, "华泰柏瑞当前无法读取；请稍后重试或人工核对其他可靠来源"
    rows = []
    for day, value in candidates:
        confirmed = reference.get(day)
        price = float(value)
        rows.append({"trade_date": day, "sina_price": price, "htbr_price": confirmed,
                     "published_price": published.get(day),
                     "difference_pct": round((price / confirmed - 1) * 100, 4) if confirmed else None})
    return {"symbol": symbol, "issue_code": issue_code, "reference_status": reference_status,
            "price_basis": "场内不复权收盘价（元/份）", "rows": rows}


class SourceApproval(BaseModel):
    issue_id: int
    evidence_id: str


@app.post("/api/data-center/source-approvals", dependencies=[Depends(_local_admin)])
def approve_source_candidate(decision: SourceApproval):
    if not decision.evidence_id.strip():
        raise HTTPException(400, detail="请填写人工核验依据")
    with sqlite3.connect(DATABASE_PATH) as connection:
        row = connection.execute("""SELECT q.symbol,q.kind,r.raw_sha256,r.fetch_batch_id FROM quality_issues q
            JOIN raw_observations r ON r.symbol=q.symbol AND r.kind=q.kind AND r.trade_date=q.trade_date
                AND r.fetch_batch_id=q.batch_id
            WHERE q.issue_id=? AND q.resolution_status='open' AND q.severity='BLOCKED'
                AND r.upstream_publisher='Sina'
            ORDER BY r.raw_record_id DESC LIMIT 1""", (decision.issue_id,)).fetchone()
    if not row or row[1] != "etf" or not row[2]:
        raise HTTPException(404, detail="未找到可审核的 ETF 候选原始记录")
    symbol, _, digest, batch = row
    archive = DATA_ROOT / "raw" / "market" / batch / f"etf-{symbol}-{digest[:16]}.bin"
    if not archive.is_file() or archive.is_symlink() or hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
        raise HTTPException(409, detail="候选原始数据归档缺失或校验失败")
    try:
        record_approval(DATA_ROOT, symbol, digest, decision.evidence_id)
    except ValueError as error:
        raise HTTPException(400, detail=str(error)) from error
    return {"symbol": symbol, "raw_sha256": digest, "status": "APPROVED_FOR_NEXT_REFRESH"}


def _run_update_job(job_id: str) -> None:
    set_job(DATA_ROOT, job_id, state="RUNNING", stage="VERIFY_REFERENCES")
    current_stage = "VERIFY_REFERENCES"

    def on_progress(stage: str) -> None:
        nonlocal current_stage
        if stage == current_stage:
            return
        current_stage = stage
        phases = {
            "FETCHING": ("RUNNING", None, None),
            "VALIDATING": ("FETCH_OK", "RUNNING", None),
            "VALIDATED": ("FETCH_OK", "VERIFIED", None),
            "STAGING": ("FETCH_OK", "VERIFIED", "RUNNING"),
            "PREPARED": ("FETCH_OK", "VERIFIED", "RUNNING"),
            "PUBLISHED": ("FETCH_OK", "VERIFIED", "PUBLISHED"),
        }
        fetched, validated, published = phases[stage]
        set_job(DATA_ROOT, job_id, state="RUNNING", stage=stage,
                fetch_status=fetched, validation_status=validated,
                publication_status=published)

    stop_heartbeat = threading.Event()

    def keep_alive():
        while not stop_heartbeat.wait(15):
            try:
                heartbeat_job(DATA_ROOT, job_id)
            except sqlite3.Error:
                continue

    heartbeat = threading.Thread(target=keep_alive, daemon=True)
    heartbeat.start()
    try:
        verification = run_daily(database=DATABASE_PATH, data_root=DATA_ROOT, publish=False)
        summary = update_dataset(progress=on_progress, require_reference_verification=True,
                                 end_date=verification["through"])
        snapshot_id = summary.get("snapshot_id")
        unchanged = summary.get("publicationStatus") == "UNCHANGED"
        source_issues = summary.get("sourceIssues") or []
        nikkei_status = summary.get("nikkeiAnchor", {}).get("status")
        etf_date = summary.get("etfLatestTradeDate")
        index_date = summary.get("indexLatestTradeDate")
        index_lags_etf = bool(etf_date and index_date and index_date < etf_date)
        expected_index_date = verification.get("latest_metrics", {}).get("expected_trade_date")
        index_lags_reference = bool(expected_index_date and index_date and index_date < expected_index_date)
        route_pending = [code for code in ("480080", "480081")
                         if verification.get("indexes", {}).get(code, {}).get("route_approval", {}).get("status") == "NO_TARGET_MATCH"]
        index_incomplete = index_lags_etf or index_lags_reference
        index_reason = ("CNI_ROUTE_PENDING" if route_pending else
                        "INDEX_BEHIND_ETF" if index_lags_etf else "INDEX_BEHIND_REFERENCE")
        partial = (bool(source_issues) or index_incomplete
                   or nikkei_status in {"ERROR", "SKIPPED_NO_CREDENTIAL", "NO_BASELINE"})
        if snapshot_id:
            record_dataset_result(DATA_ROOT, job_id, "etf_prices", "ETF 行情", "NO_NEW_ROWS" if unchanged else "PUBLISHED",
                                  "逐条来源见行情记录", latest_date=etf_date)
            record_dataset_result(DATA_ROOT, job_id, "index_prices", "指数行情",
                                  "PARTIAL" if index_incomplete else "NO_NEW_ROWS" if unchanged else "PUBLISHED",
                                  "逐条来源见行情记录",
                                  reason_code=index_reason if index_incomplete else None,
                                  latest_date=index_date)
        for issue in source_issues:
            record_dataset_result(DATA_ROOT, job_id, f"{issue['kind']}:{issue['symbol']}", issue["symbol"],
                                  "FAILED", reason_code=issue["issue_code"], latest_date=issue["trade_date"])
        for code in route_pending:
            published_day = (verification.get("latest_metrics", {}).get("indexes", {})
                             .get(code, {}).get("published_date"))
            record_dataset_result(DATA_ROOT, job_id, f"index:{code}", code, "FAILED",
                                  reason_code="CNI_ROUTE_PENDING", latest_date=published_day or index_date)
        _record_nikkei_result(job_id, summary.get("nikkeiAnchor", {}))
        stage = ("UNCHANGED_WITH_PARTIAL_FAILURE" if partial else "UNCHANGED") if unchanged else (
            "PUBLISHED_WITH_PARTIAL_FAILURE" if partial else "PUBLISHED" if snapshot_id else "COMPLETED_UNVERIFIED")
        set_job(DATA_ROOT, job_id, state="PARTIAL" if partial or not snapshot_id else "SUCCEEDED",
                stage=stage, snapshot_id=summary.get("snapshot_id"),
                fetch_status="PARTIAL" if source_issues else "FETCH_OK", validation_status="VERIFIED",
                publication_status="UNCHANGED" if unchanged else "PUBLISHED" if snapshot_id else "UNKNOWN")
    except Exception as error:
        detail = str(error)
        if "fallback" in detail and "quarantined" in detail:
            try:
                index_summary = update_dataset(index_only=True, progress=on_progress, require_reference_verification=True)
                record_dataset_result(DATA_ROOT, job_id, "index_prices", "指数行情", "PUBLISHED",
                                      "逐条来源见行情记录", latest_date=index_summary.get("indexLatestTradeDate"))
                record_dataset_result(DATA_ROOT, job_id, "etf_prices", "ETF 行情", "SKIPPED",
                                      reason_code="ETF_REVIEW_REQUIRED")
                _record_nikkei_result(job_id, index_summary.get("nikkeiAnchor", {}))
                set_job(DATA_ROOT, job_id, state="PARTIAL", stage="INDEX_PUBLISHED_ETF_PENDING",
                        snapshot_id=index_summary.get("snapshot_id"),
                        error="ETF 价格未通过校核，指数已单独更新；请到数据中心查看候选价并审核。",
                        fetch_status="FETCH_OK", validation_status="ETF_REVIEW_REQUIRED",
                        publication_status="INDEX_PUBLISHED")
                return
            except Exception:
                pass
        # The public diagnostic endpoint must not echo URLs or credential values.
        failure_phases = {
            "VERIFY_REFERENCES": ("RUNNING", "VERIFICATION_FAILED", "NOT_ATTEMPTED"),
            "FETCHING": ("FETCH_FAILED", "UNKNOWN", "NOT_ATTEMPTED"),
            "VALIDATING": ("FETCH_OK", "VALIDATION_FAILED", "NOT_ATTEMPTED"),
            "VALIDATED": ("FETCH_OK", "VERIFIED", "FAILED"),
            "STAGING": ("FETCH_OK", "VERIFIED", "FAILED"),
            "PREPARED": ("FETCH_OK", "VERIFIED", "FAILED"),
        }
        fetched, validated, published = failure_phases.get(current_stage, ("UNKNOWN", "UNKNOWN", "UNKNOWN"))
        reason = ("ETF 价格未通过来源校核；请到数据中心查看候选价。" if "quarantined" in detail
                  else "指数数据源尚未发布最新交易日；已保留旧版快照。" if "empty response for expected trading interval" in detail
                  else "数据校验或采集失败；已保留旧版快照，请查看数据中心。")
        record_dataset_result(DATA_ROOT, job_id, "all_prices", "ETF 与指数行情", "FAILED",
                              reason_code="ETF_SOURCE_QUARANTINED" if "quarantined" in detail
                              else "SOURCE_TRAILING_UNAVAILABLE" if "empty response for expected trading interval" in detail
                              else "FETCH_OR_VALIDATION_FAILED", error_type=type(error).__name__)
        set_job(DATA_ROOT, job_id, state="FAILED", stage=current_stage, error=reason,
                fetch_status=fetched, validation_status=validated, publication_status=published)
    finally:
        stop_heartbeat.set()
        heartbeat.join(timeout=1)


def _record_nikkei_result(job_id: str, result: dict) -> None:
    status = result.get("status")
    if not status:
        return
    message = str(result.get("message", "")).lower()
    reason = ("UPSTREAM_HTTP_429" if "429" in message else
              "UPSTREAM_HTTP_403" if "403" in message else
              "UPSTREAM_TIMEOUT" if "timeout" in message or "timed out" in message else
              "NIKKEI_SYNC_ERROR") if status == "ERROR" else (
              "NO_WIND_CREDENTIAL" if status == "SKIPPED_NO_CREDENTIAL" else
              "NO_BASELINE" if status == "NO_BASELINE" else None)
    state = ("FAILED" if status == "ERROR" else "SKIPPED" if status in
             {"SKIPPED_NO_CREDENTIAL", "NO_BASELINE"} else status if status in
             {"UPDATED", "NO_NEW_ROWS"} else "UNKNOWN")
    error_type = result.get("error_type")
    if error_type and not str(error_type).replace("_", "").isalnum():
        error_type = None
    record_dataset_result(DATA_ROOT, job_id, "nikkei225_anchor", "日经225临时基准（五年之锚）",
                          state, "Wind MCP", reason, error_type,
                          result.get("inserted"), result.get("replaced"), result.get("toDate"))


@app.post("/api/jobs/update", status_code=202, dependencies=[Depends(_local_admin)])
def queue_update(background_tasks: BackgroundTasks):
    window = date.today().isoformat()
    job, created = claim_job(DATA_ROOT, "all_prices", window, "manual", reuse_success=False)
    if created:
        background_tasks.add_task(_run_update_job, job["job_id"])
    return {"job_id": job["job_id"], "state": job["state"], "created": created,
            "status_url": f"/api/jobs/{job['job_id']}"}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = get_job(DATA_ROOT, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/api/jobs/{job_id}/details")
def job_details(job_id: str):
    detail = get_job_detail(DATA_ROOT, job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="job not found")
    return detail


class CredentialRequest(BaseModel):
    key: str


def _credential_provider(provider: str) -> str:
    try:
        return credential_settings.normalize_provider(provider).value
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="未知的凭证提供方") from exc


def _safe_credential_test_result(result: dict, provider: str) -> dict:
    status = str(result.get("status", "check_failed"))
    ok = bool(result.get("ok"))
    return {
        "provider": provider,
        "configured": bool(result.get("configured")),
        "ok": ok,
        "remote_verified": bool(result.get("remote_verified")),
        "status": status,
        "message": "连接成功" if ok else (
            "本地配置检查通过；未验证远程服务"
            if status == "not_verified" else "连接测试失败"
        ),
    }


@app.get("/api/settings/credentials")
def credential_status():
    try:
        return {"credentials": credential_settings.list_credential_status()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail="凭证状态查询失败") from exc


@app.put("/api/settings/credentials/{provider}", dependencies=[Depends(_local_admin)])
def save_credential(provider: str, request: CredentialRequest):
    normalized = _credential_provider(provider)
    if not request.key.strip():
        raise HTTPException(status_code=400, detail="凭证不能为空")
    try:
        credential_settings.set_credential(normalized, request.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="凭证不能为空") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="凭证保存失败") from exc
    return {"provider": normalized, "configured": True}


@app.delete("/api/settings/credentials/{provider}", dependencies=[Depends(_local_admin)])
def remove_credential(provider: str):
    normalized = _credential_provider(provider)
    try:
        credential_settings.delete_credential(normalized)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="凭证删除失败") from exc
    return {"provider": normalized, "configured": False}


@app.post("/api/settings/credentials/{provider}/test", dependencies=[Depends(_local_admin)])
def test_saved_credential(provider: str):
    normalized = _credential_provider(provider)
    try:
        result = _safe_credential_test_result(
            credential_settings.test_credential(normalized), normalized
        )
    except Exception as exc:
        result = {
            "provider": normalized,
            "configured": False,
            "ok": False,
            "remote_verified": False,
            "status": "check_failed",
            "message": "连接测试失败",
        }
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@app.get("/")
def home():
    return RedirectResponse("/web/overview.html")


@app.get("/api/health")
def health():
    checks = {}
    manifest = None
    latest_dates = {}
    try:
        with sqlite3.connect(DATABASE_PATH.as_uri() + "?mode=ro", uri=True) as connection:
            connection.execute("SELECT 1 FROM etf_prices LIMIT 1").fetchone()
            connection.execute("SELECT 1 FROM index_prices LIMIT 1").fetchone()
            pending = connection.execute("SELECT COUNT(*) FROM release_manifest WHERE status='prepared'").fetchone()[0]
        checks["sqlite"] = "UP"
        checks["release"] = "UNHEALTHY" if pending else "UP"
    except (OSError, sqlite3.Error):
        checks["sqlite"] = "UNHEALTHY"
    try:
        manifest = _current_manifest()
        if manifest.get("status") not in ("published", "legacy", None):
            raise ValueError("snapshot is not published")
        checks["manifest"] = "UP"
        for key in ("etf", "index"):
            payload = read_dataset(DATA_ROOT, manifest, key)
            if not payload["records"]:
                raise ValueError("empty snapshot")
            if key == "index" and (not isinstance(payload.get("strategyMetrics"), dict) or any(not rows for rows in payload["strategyMetrics"].values())):
                raise ValueError("strategy inputs unavailable")
            checks[key] = "UP"
            latest_dates[key] = payload.get("latestTradeDate")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        checks["snapshot"] = f"UNHEALTHY: {error}"
    ready = checks.get("sqlite") == checks.get("release") == "UP" and checks.get("etf") == checks.get("index") == "UP"
    state = "UP" if ready and status["state"] != "error" else ("DEGRADED" if ready else "UNHEALTHY")
    ages = []
    for value in latest_dates.values():
        try:
            ages.append((date.today() - datetime.strptime(value, "%Y%m%d").date()).days)
        except (TypeError, ValueError):
            pass
    freshness = "STALE" if ages and max(ages) > 7 else "CURRENT" if ages else "UNKNOWN"
    if ready and freshness == "STALE":
        state = "DEGRADED"
    try:
        last_job = recent_jobs(DATA_ROOT, 1)[0]
    except (IndexError, sqlite3.Error):
        last_job = None
    job_failed = last_job is not None and last_job["state"] in {"FAILED", "PARTIAL"}
    if job_failed and ready:
        state = "DEGRADED"
    effective_state = "error" if job_failed else status["state"]
    message = "最近更新任务未全部完成；仍使用上一有效发布版本" if job_failed else status["message"]
    return {"state": effective_state, "message": message, "updatedAt": status["updatedAt"], "summary": status["summary"], "snapshot_id": manifest.get("snapshot_id") if manifest else None, "dataExists": ready, "healthState": state, "checks": checks, "freshness": {**latest_dates, "status": freshness}, "lastJob": {"job_id": last_job["job_id"], "state": last_job["state"]} if last_job else None}


@app.get("/api/ready")
def ready():
    result = health()
    return JSONResponse(result, status_code=200 if result["dataExists"] else 503)


@app.get("/api/live")
def live():
    return {"state": "UP"}


@app.get("/api/freshness")
def freshness():
    return health()["freshness"]


class IFindIndexRequest(BaseModel):
    index_code: str
    ifind_code: str
    start_date: str
    end_date: str


@app.post("/api/ifind/index-history", dependencies=[Depends(_local_admin)])
def ifind_index_history(request: IFindIndexRequest):
    try:
        result = fetch_ifind_index_history(request.index_code, request.ifind_code,
                                           request.start_date, request.end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="iFinD 指数代码或日期无效") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="iFinD 历史行情获取失败") from exc
    return {"provider": result.provider, "indexCode": request.index_code,
            "ifindCode": request.ifind_code, "priceBasis": result.price_basis,
            "rawSha256": result.raw_sha256, "rows": result.rows}


@app.get("/api/industry-rotation/catalog")
def industry_rotation_catalog_api():
    return {"industries": industry_rotation_catalog(DATABASE_PATH)}


@app.get("/api/industry-rotation/prism")
def industry_rotation_prism_api(code: str):
    try:
        return industry_rotation_prism(code, DATABASE_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/wind/status")
def wind_status():
    return {"configured": bool(get_authorization()), "endpoint": os.environ.get("WIND_MCP_URL", "https://mcp.wind.com.cn/vserver_wind_tools/mcp/"), "credentialValue": None}


def _current_manifest() -> dict:
    return read_manifest(DATA_ROOT)


@app.get("/api/snapshot")
def snapshot():
    manifest = _current_manifest()
    return {"snapshot_id": manifest["snapshot_id"], "status": manifest.get("status"), "files": manifest.get("files", {})}


@app.get("/api/provenance/{kind}/{symbol}/{trade_date}")
def provenance(kind: str, symbol: str, trade_date: str):
    if kind not in ("etf", "index") or not symbol.isalnum() or len(trade_date) != 8 or not trade_date.isdigit():
        raise HTTPException(400, detail="invalid observation key")
    try:
        with sqlite3.connect(DATABASE_PATH.as_uri() + "?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("""SELECT c.*,r.provider,r.upstream_publisher,r.raw_sha256,r.fetch_batch_id,r.source_url
                FROM canonical_observations c LEFT JOIN raw_observations r ON r.raw_record_id=c.selected_raw_id
                WHERE c.kind=? AND c.symbol=? AND c.trade_date=?""", (kind, symbol, trade_date)).fetchone()
    except sqlite3.Error as error:
        raise HTTPException(503, detail="provenance registry unavailable") from error
    manifest = _current_manifest()
    matches = corroborating_raw_matches(DATABASE_PATH, DATA_ROOT, kind, symbol, trade_date,
                                        row["normalized_value"]) if row and row["selected_raw_id"] is None and row["normalized_value"] is not None else []
    return {"snapshot_id": manifest["snapshot_id"], "observation": dict(row) if row else None,
            "publishedSnapshotId": manifest["snapshot_id"] if row and manifest.get("fetch_batch_id") == row["batch_id"] else None,
            "sourceVerification": "UNVERIFIED" if row and row["selected_raw_id"] and row["provider"] not in (None, "PROVENANCE_UNKNOWN") else "UNKNOWN",
            "corroboratingRaw": matches}


def _verified_release_digest(manifest: dict, key: str) -> str:
    path = resolve_file(DATA_ROOT, manifest["files"][key])
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    expected = manifest.get("sha256", {}).get(key)
    if expected and actual != expected:
        raise ValueError("snapshot hash mismatch")
    return actual


@lru_cache(maxsize=4)
def _rotation_overview(data_root: str, snapshot_id: str, index_file: str, etf_file: str,
                       index_digest: str, etf_digest: str):
    manifest = _current_manifest()
    if (str(DATA_ROOT) != data_root or manifest["snapshot_id"] != snapshot_id
            or manifest["files"]["index"] != index_file or manifest["files"]["etf"] != etf_file):
        raise ValueError("snapshot pointer changed")
    return build_overview(snapshot_id, read_dataset(DATA_ROOT, manifest, "index"), read_dataset(DATA_ROOT, manifest, "etf"))


@app.get("/api/rotation/overview")
def rotation_overview():
    try:
        manifest = _current_manifest()
        index_digest = _verified_release_digest(manifest, "index")
        etf_digest = _verified_release_digest(manifest, "etf")
        result = _rotation_overview(str(DATA_ROOT), manifest["snapshot_id"], manifest["files"]["index"],
                                    manifest["files"]["etf"], index_digest, etf_digest)
        if _current_manifest() != manifest:
            raise ValueError("snapshot pointer changed")
        return result
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(503, detail="当前快照无法生成轮动总览") from error


@app.get("/api/snapshot/data/{dataset_name}")
def snapshot_data(dataset_name: str, snapshot_id: Optional[str] = None):
    if dataset_name not in {"etf_prices.json", "index_prices.json"}:
        raise HTTPException(status_code=404, detail="dataset not found")
    manifest = _current_manifest()
    requested = snapshot_id or manifest["snapshot_id"]
    if requested != manifest["snapshot_id"]:
        raise HTTPException(status_code=409, detail="snapshot is not the current published snapshot")
    key = "etf" if dataset_name.startswith("etf") else "index"
    try:
        return JSONResponse(read_dataset(DATA_ROOT, manifest, key))
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="snapshot dataset not found") from error
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=503, detail="snapshot dataset invalid") from error


@app.get("/api/snapshot/index-view")
def snapshot_index_view(strategy: Optional[str] = None, codes: Optional[str] = None,
                        start: Optional[str] = None, end: Optional[str] = None,
                        snapshot_id: Optional[str] = None):
    manifest = _current_manifest()
    if snapshot_id is not None and snapshot_id != manifest["snapshot_id"]:
        raise HTTPException(status_code=409, detail="snapshot is not the current published snapshot")
    for day in (start, end):
        if day is not None:
            try:
                datetime.strptime(day, "%Y%m%d")
                if len(day) != 8:
                    raise ValueError("invalid date length")
            except ValueError as error:
                raise HTTPException(status_code=422, detail="start and end must be YYYYMMDD") from error
    selected = tuple(codes.split(",")) if codes else ()
    try:
        payload = read_dataset(DATA_ROOT, manifest, "index")
        return JSONResponse(project_index_view(payload, strategy=strategy, codes=selected, start=start, end=end))
    except ValueError as error:
        if str(error) in {"start must not be later than end", "strategy and codes are mutually exclusive",
                          "unknown strategy", "provide valid index codes or strategy"}:
            raise HTTPException(status_code=422, detail=str(error)) from error
        raise HTTPException(status_code=503, detail="snapshot dataset invalid") from error
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=503, detail="snapshot dataset invalid") from error


@app.post("/api/update", dependencies=[Depends(_local_admin)])
def update():
    if not update_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="数据正在更新，请稍候。")
    status.update(state="updating", message="正在刷新全部 ETF、指数和策略数据……", summary=None)
    try:
        summary = update_dataset(require_reference_verification=True)
        updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
        message = f"全部数据刷新成功：{summary['etfCount']} 个 ETF、{summary['indexCount']} 个指数，覆盖 {summary['strategyCount']} 个看板；数据截至 {summary.get('effectiveEndDate', summary.get('indexLatestTradeDate', '未知'))}"
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
