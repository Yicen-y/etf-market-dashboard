"""FastAPI routes for the local ETF fund-flow dashboard."""

from __future__ import annotations

from datetime import date, timedelta
import csv
import io
from pathlib import Path
import threading
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from .config import DATABASE_PATH, ETF_UNIVERSE, PRESET_GROUPS
from .db import init_fund_flow_schema, open_fund_flow_connection, seed_default_fund_master
from .providers.csv_provider import ImportPreview, commit_import, parse_csv
from .providers.nav_provider import AkshareNavProvider
from .providers.sse_provider import AkshareSSEProvider
from .providers.szse_provider import AkshareSZSEProvider
from .services.persistence import rebuild_materialized
from .services.sync import sync_recent


router = APIRouter(prefix="/api/fund-flow", tags=["fund-flow"])
_sync_lock = threading.Lock()
_previews: dict[str, ImportPreview] = {}
HISTORY_START = date(2023, 12, 29)


@router.get("/sync-status")
def fund_flow_sync_status():
    return {"updating": _sync_lock.locked()}


def _db() -> Path:
    return DATABASE_PATH


def _codes(preset: str, codes: Optional[str]) -> list[str]:
    if codes:
        selected = [code.strip().upper() for code in codes.split(",") if code.strip()]
        unknown = [code for code in selected if code not in ETF_UNIVERSE]
        if unknown:
            raise HTTPException(400, f"未知ETF代码：{', '.join(unknown)}")
        return selected
    if preset not in PRESET_GROUPS:
        raise HTTPException(400, f"未知ETF组合：{preset}")
    return list(PRESET_GROUPS[preset])


def _date_or_default(value: Optional[str], default: date) -> date:
    if not value or value == "latest":
        return default
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, f"日期格式应为 YYYY-MM-DD：{value}") from exc


def _metric_rows(codes: list[str], start: date, end: date) -> list[dict]:
    init_fund_flow_schema(_db())
    placeholders = ",".join("?" for _ in codes)
    with open_fund_flow_connection(_db()) as connection:
        rows = connection.execute(
            f"""SELECT etf_code,trade_date,shares_adj_wan,nav_adj,delta_shares_wan,
                       net_flow_yi,cum_flow_yi,intensity_pct,calc_version,status
                FROM fund_flow_etf_daily_metrics
                WHERE etf_code IN ({placeholders}) AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date,etf_code""",
            [*codes, start.isoformat(), end.isoformat()],
        ).fetchall()
    fields = ("etf_code", "trade_date", "shares_adj_wan", "nav_adj", "delta_shares_wan", "net_flow_yi", "cum_flow_yi", "intensity_pct", "calc_version", "status")
    return [dict(zip(fields, row)) for row in rows]


@router.get("/health")
def fund_flow_health():
    init_fund_flow_schema(_db())
    with open_fund_flow_connection(_db()) as connection:
        count = connection.execute("SELECT COUNT(*) FROM fund_flow_etf_daily_metrics").fetchone()[0]
        earliest = connection.execute("SELECT MIN(trade_date) FROM fund_flow_etf_daily_metrics").fetchone()[0]
        latest = connection.execute("SELECT MAX(trade_date) FROM fund_flow_etf_daily_metrics").fetchone()[0]
        blocked = connection.execute("SELECT COUNT(*) FROM fund_flow_etf_daily_metrics WHERE status IN ('BLOCKED','INCOMPLETE')").fetchone()[0]
    history_complete = bool(earliest and date.fromisoformat(earliest) <= HISTORY_START)
    return {"dataExists": bool(count), "earliestTradeDate": earliest, "latestTradeDate": latest, "historyComplete": history_complete, "qualityState": "BLOCKED" if blocked else "PASS", "blockedCount": blocked, "metricCount": count}


@router.get("/overview")
def fund_flow_overview(preset: str = "core_four", start: Optional[str] = None, end: str = "latest"):
    codes = _codes(preset, None)
    return _overview_for_codes(codes, start, end, preset)


def _overview_for_codes(codes: list[str], start: Optional[str], end: str, preset: Optional[str] = None):
    init_fund_flow_schema(_db())
    with open_fund_flow_connection(_db()) as connection:
        latest_text = connection.execute("SELECT MAX(trade_date) FROM fund_flow_etf_daily_metrics").fetchone()[0]
        earliest_text = connection.execute("SELECT MIN(trade_date) FROM fund_flow_etf_daily_metrics").fetchone()[0]
    latest = date.fromisoformat(latest_text) if latest_text else date.today()
    end_date = _date_or_default(end, latest)
    start_date = _date_or_default(start, HISTORY_START)
    rows = _metric_rows(codes, start_date, end_date)
    names = {code: ETF_UNIVERSE[code]["name"] for code in codes}
    history_complete = bool(earliest_text and date.fromisoformat(earliest_text) <= HISTORY_START)
    return {"preset": preset, "codes": codes, "names": names, "earliestTradeDate": earliest_text, "latestTradeDate": latest_text, "historyComplete": history_complete, "start": start_date.isoformat(), "end": end_date.isoformat(), "rows": rows, "dataExists": bool(rows)}


def _needs_history_backfill() -> bool:
    init_fund_flow_schema(_db())
    with open_fund_flow_connection(_db()) as connection:
        earliest = connection.execute("SELECT MIN(trade_date) FROM fund_flow_etf_daily_metrics").fetchone()[0]
    return earliest is None or date.fromisoformat(earliest) > HISTORY_START


def _incremental_start(end: date, overlap_days: int) -> date:
    """Resume from the oldest ETF tail, with a short correction overlap."""
    with open_fund_flow_connection(_db()) as connection:
        latest_by_code = dict(connection.execute(
            "SELECT etf_code, MAX(record_date) FROM fund_flow_etf_daily_raw GROUP BY etf_code"
        ).fetchall())
    if any(code not in latest_by_code for code in ETF_UNIVERSE):
        return HISTORY_START
    oldest_tail = min(date.fromisoformat(latest_by_code[code]) for code in ETF_UNIVERSE)
    return max(HISTORY_START, oldest_tail - timedelta(days=overlap_days * 2))


@router.get("/series")
def fund_flow_series(codes: str, start: Optional[str] = None, end: str = "latest", frequency: str = "daily"):
    if frequency not in {"daily", "weekly", "monthly"}:
        raise HTTPException(400, "frequency must be daily, weekly or monthly")
    selected = _codes("all_six", codes)
    payload = _overview_for_codes(selected, start, end)
    if frequency != "daily":
        grouped: dict[str, dict] = {}
        for row in payload["rows"]:
            key = row["trade_date"][:7] if frequency == "monthly" else f"{date.fromisoformat(row['trade_date']).isocalendar().year}-W{date.fromisoformat(row['trade_date']).isocalendar().week:02d}"
            item = grouped.setdefault(key, {"period": key, "by_code": {code: [] for code in selected}, "dates": set()})
            item["by_code"].setdefault(row["etf_code"], []).append(row)
        compact = []
        for item in grouped.values():
            missing = []
            valid_codes = []
            quality = []
            total = 0.0
            period_dates = {row["trade_date"] for code_rows in item["by_code"].values() for row in code_rows}
            for code in selected:
                code_rows = item["by_code"].get(code, [])
                code_dates = {row["trade_date"] for row in code_rows}
                if not code_rows or code_dates != period_dates or any(row["net_flow_yi"] is None for row in code_rows):
                    missing.append(code)
                    quality.append({"code": code, "reason": "missing_or_blocked_daily_flow", "missingDates": sorted(period_dates - code_dates)})
                else:
                    valid_codes.append(code)
                    total += sum(row["net_flow_yi"] for row in code_rows)
            compact.append({"period": item["period"], "net_flow_yi": total if not missing else None, "coverage_codes": valid_codes, "missing_codes": missing, "coverage_ratio": len(valid_codes) / len(selected) if selected else 0, "qualityIssues": quality, "status": "PASS" if not missing else "INCOMPLETE"})
        payload["rows"] = compact
    return payload


@router.get("/quality")
def fund_flow_quality(start: Optional[str] = None, end: str = "latest"):
    payload = _overview_for_codes(list(ETF_UNIVERSE), start, end)
    return {"start": payload["start"], "end": payload["end"], "issues": [{"etf_code": row["etf_code"], "trade_date": row["trade_date"], "status": row["status"]} for row in payload["rows"] if row["status"] != "PASS"]}


@router.post("/sync")
def fund_flow_sync(overlap_days: int = Query(5, ge=1, le=30), backfill: bool = Query(False)):
    if not _sync_lock.acquire(blocking=False):
        raise HTTPException(409, "资金流数据正在刷新，请稍候。")
    try:
        end = date.today()
        should_backfill = backfill or _needs_history_backfill()
        start = HISTORY_START if should_backfill else _incremental_start(end, overlap_days)
        report = sync_recent(_db(), share_providers=[AkshareSSEProvider(), AkshareSZSEProvider()], nav_provider=AkshareNavProvider(), start=start, end=end)
        return {"mode": "backfill" if should_backfill else "incremental", "start": start.isoformat(), "inserted": report.inserted, "updated": report.updated, "latestTradeDate": report.latest_trade_date.isoformat() if report.latest_trade_date else None, "providerStatus": report.provider_status, "warnings": report.warnings}
    finally:
        _sync_lock.release()


@router.post("/import/preview")
async def fund_flow_import_preview(file: UploadFile = File(...)):
    preview = parse_csv(io.BytesIO(await file.read()), source_id=f"csv:{file.filename}:{date.today().isoformat()}")
    _previews[preview.source_id] = preview
    return {"sourceId": preview.source_id, "committed": False, "rowCount": len(preview.rows), "fieldMapping": preview.field_mapping, "warnings": preview.warnings, "errors": preview.errors}


@router.post("/import/commit")
def fund_flow_import_commit(source_id: str):
    preview = _previews.get(source_id)
    if preview is None:
        raise HTTPException(404, "预览批次不存在或已过期")
    try:
        job = commit_import(preview, _db())
        materialized = rebuild_materialized(_db())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"sourceId": job.source_id, "batchId": job.import_batch_id, "status": job.status, **materialized}


def _export_csv(table: str, codes: list[str], start: date, end: date):
    allowed = {"clean": "fund_flow_etf_daily_clean", "summary": "fund_flow_etf_daily_metrics"}
    table_name = allowed[table]
    with open_fund_flow_connection(_db()) as connection:
        rows = connection.execute(f"SELECT * FROM {table_name} WHERE etf_code IN ({','.join('?' for _ in codes)}) AND trade_date BETWEEN ? AND ? ORDER BY trade_date,etf_code", [*codes, start.isoformat(), end.isoformat()]).fetchall()
        columns = [description[0] for description in connection.execute(f"SELECT * FROM {table_name} LIMIT 0").description]
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(columns)
    writer.writerows(rows)
    return StreamingResponse(iter([stream.getvalue().encode("utf-8-sig")]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=fund_flow_{table}.csv"})


@router.get("/export/{table}.csv")
def fund_flow_export(table: str, preset: str = "core_four", start: Optional[str] = None, end: str = "latest"):
    if table not in {"clean", "summary"}:
        raise HTTPException(404, "unsupported export")
    codes = _codes(preset, None)
    with open_fund_flow_connection(_db()) as connection:
        latest_text = connection.execute("SELECT MAX(trade_date) FROM fund_flow_etf_daily_metrics").fetchone()[0]
    latest = date.fromisoformat(latest_text) if latest_text else date.today()
    return _export_csv(table, codes, _date_or_default(start, date(2023, 12, 29)), _date_or_default(end, latest))
