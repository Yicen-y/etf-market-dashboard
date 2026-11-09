"""Read-only research endpoints; never upgrades unverified legacy data to verified."""
import json
import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from scripts.config import DATABASE_PATH, ROOT
from scripts.dividend.research import ah_common_40, condition_forward_returns, dividend_regression
from scripts.dividend.research_store import read_research_series, research_series_metadata
from scripts.dividend.research_sync import DEFAULT_RESEARCH_START_DATE, sync_research_sources
from scripts.dividend.research_backtest import backtest_ah_momentum
from scripts.prism_metrics import calculate_prism_metrics
from scripts.storage import read_index_records

router = APIRouter(prefix="/api/research", tags=["dividend-research"])


def _index_rows():
    manifest_path = ROOT / "data" / "current_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        data_path = (ROOT / "data" / manifest["files"]["index"]).resolve()
        if not data_path.is_relative_to((ROOT / "data").resolve()):
            raise ValueError("invalid data path")
        raw = data_path.read_bytes()
        expected_hash = manifest.get("sha256", {}).get("index")
        if expected_hash and hashlib.sha256(raw).hexdigest() != expected_hash:
            raise ValueError("index snapshot hash mismatch")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data.get("flatRecords"), list):
            raise ValueError("index snapshot does not contain flatRecords")
        return manifest, data
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, detail={"code": "INDEX_SNAPSHOT_UNAVAILABLE", "message": str(exc)}) from exc


def _h00922_source_status(rows):
    """Confirm that every fitted snapshot point matches an AkShare sourced DB fact."""
    try:
        with sqlite3.connect(DATABASE_PATH) as connection:
            stored = {day: (value, source) for day, value, source in connection.execute(
                "SELECT trade_date, close_value, source FROM index_prices WHERE index_code=?", ("H00922",)
            )}
    except sqlite3.Error:
        return "UNVERIFIED_SOURCE"
    if rows and all(
        row["tradeDate"] in stored
        and stored[row["tradeDate"]][1] == "AkShare"
        and abs(float(row["closeValue"]) - stored[row["tradeDate"]][0]) < 1e-8
        for row in rows
    ):
        return "AKSHARE_SOURCED"
    return "UNVERIFIED_SOURCE"


@router.get("/dividend-regression")
def regression(mode: str = Query("fixed_asof", pattern="^(fixed_asof|expanding_point_in_time)$"),
               fit_start: str = Query("20121231", pattern=r"^\d{8}$"), as_of: Optional[str] = Query(None, pattern=r"^\d{8}$"),
               sigma: float = Query(1.5, gt=0, le=3), warmup: int = Query(756, ge=3, le=5000)):
    manifest, data = _index_rows()
    rows = [r for r in data.get("flatRecords", []) if r.get("indexCode") == "H00922"
            and fit_start <= r.get("tradeDate", "") <= (as_of or "99999999")]
    if not rows:
        raise HTTPException(424, detail={"code": "INSUFFICIENT_INDEX_HISTORY", "message": "H00922在所选区间没有数据"})
    try:
        result = dividend_regression(rows, mode=mode, sigma=sigma, expanding_warmup=warmup)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_RESEARCH_DATA", "message": str(exc)}) from exc
    source_status = _h00922_source_status(rows)
    result.update({"indexCode": "H00922", "indexName": "中证红利全收益指数", "currency": "CNY",
                   "returnType": "total_return", "metricUnit": "index_point", "snapshotId": manifest.get("snapshot_id"),
                   "sourceProvider": "AkShare" if source_status == "AKSHARE_SOURCED" else None,
                   "qualityStatus": source_status,
                   "warning": ("H00922点位与AkShare来源数据库逐日一致；" if source_status == "AKSHARE_SOURCED"
                               else "拟合区间中存在未确认来源或与数据库不一致的点位；")
                   + "全样本拟合为事后结果，不可用于历史信号。"})
    if mode == "expanding_point_in_time":
        result["conditionalForwardReturns"] = condition_forward_returns(
            result["rows"], rows, horizons=(20, 60, 120, 252))
    else:
        result["conditionalForwardReturns"] = []
    return result


@router.get("/dividend-ah")
def dividend_ah(window: int = Query(40, ge=1, le=252)):
    manifest, _ = _index_rows()
    all_rows = read_index_records(DATABASE_PATH)
    a = [{"tradeDate": r["tradeDate"], "closeValue": r["closeValue"]} for r in all_rows if r.get("indexCode") == "H00922"]
    h = [{"tradeDate": r["tradeDate"], "closeValue": r["closeValue"]} for r in all_rows if r.get("indexCode") == "H20915"]
    if not h:
        return {"snapshotId": manifest.get("snapshot_id"), "indexCodes": ["H00922", "H20915"],
                "qualityStatus": "MISSING_SERIES", "rows": [],
                "message": "当前数据库没有H20915港股通高股息人民币全收益指数历史数据；未用价格指数或前值替代。"}
    if window != 40:
        raise HTTPException(501, detail={"code": "WINDOW_NOT_IMPLEMENTED", "message": "当前仅开放需求定义的40共同交易日指标"})
    result_rows = ah_common_40(a, h)
    a_by_day = {row["tradeDate"]: row["closeValue"] for row in a}
    h_by_day = {row["tradeDate"]: row["closeValue"] for row in h}
    common_dates = sorted(set(a_by_day) & set(h_by_day))
    prism_input = [{"tradeDate": day, "values": {"H00922": a_by_day[day], "H20915": h_by_day[day]}}
                   for day in common_dates]
    prism_metrics = calculate_prism_metrics(prism_input, "H00922", "H20915", trading_dates=common_dates)
    metrics_by_day = {row["tradeDate"]: row for row in prism_metrics}
    first = next((row for row in result_rows if row.get("aClose") is not None and row.get("hClose") is not None), None)
    if first:
        for row in result_rows:
            row["aNormalized"] = row["aClose"] / first["aClose"] * 100 if row.get("aClose") is not None else None
            row["hNormalized"] = row["hClose"] / first["hClose"] * 100 if row.get("hClose") is not None else None
            row["spread40Pp"] = row["spread40"] * 100 if row.get("spread40") is not None else None
            row.update({key: metrics_by_day.get(row["tradeDate"], {}).get(key)
                        for key in ("ratioMa242", "ratioUpper242", "ratioLower242", "rsi14")})
    ready = [row for row in result_rows if row["quality"] == "READY"]
    latest = result_rows[-1] if result_rows else None
    return {"snapshotId": manifest.get("snapshot_id"), "indexCodes": ["H00922", "H20915"],
            "currency": "CNY", "returnType": "total_return", "window": 40,
            "qualityStatus": "UNVERIFIED_SOURCE", "calendarBasis": "observed_date_intersection",
            "latest": latest, "coverage": {"aRows": len(a), "hRows": len(h), "commonRows": len(result_rows), "ready40Rows": len(ready),
                                             "firstCommonDate": result_rows[0]["tradeDate"] if result_rows else None,
                                             "lastCommonDate": latest["tradeDate"] if latest else None}, "rows": result_rows,
            "warning": "只按两指数均有真实记录的日期求交集；未取得独立港股指数交易日历，无法区分单边源缺数与休市，故标为UNVERIFIED_SOURCE。指数理论研究，不代表ETF可交易回测。"}


@router.get("/dividend-ah-backtest")
def dividend_ah_backtest(start: Optional[str] = Query(None, pattern=r"^\d{8}$"),
                         end: Optional[str] = Query(None, pattern=r"^\d{8}$"),
                         lookback: int = Query(40, ge=1, le=252),
                         cost_bps: float = Query(0, ge=0, le=1000)):
    """Research-only A/H index comparison; it is not an executable ETF backtest."""
    manifest, data = _index_rows()
    a = {row["tradeDate"]: row["closeValue"] for row in data.get("flatRecords", [])
         if row.get("indexCode") == "H00922"}
    h = {row["tradeDate"]: row["closeValue"] for row in data.get("flatRecords", [])
         if row.get("indexCode") == "H20915"}
    dates = sorted(day for day in set(a) & set(h) if (not start or day >= start) and (not end or day <= end))
    if len(dates) < 2:
        raise HTTPException(424, detail={"code": "INSUFFICIENT_COMMON_HISTORY", "message": "所选日期内不足两个共同有效观测点"})
    rows = [{"tradeDate": day, "aClose": a[day], "hClose": h[day]} for day in dates]
    try:
        result = backtest_ah_momentum(rows, lookback=lookback, cost_bps=cost_bps)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_BACKTEST_INPUT", "message": str(exc)}) from exc
    result.update({"snapshotId": manifest.get("snapshot_id"), "indexCodes": ["H00922", "H20915"],
                   "qualityStatus": "UNVERIFIED_SOURCE",
                   "dataWarning": "本地历史点位尚未逐日完成官方核对；结果仅为人民币全收益指数理论研究，不代表ETF可交易绩效。"})
    return result


@router.get("/dividend-yield")
def dividend_yield(start: Optional[str] = Query(None, pattern=r"^\d{8}$"),
                    end: Optional[str] = Query(None, pattern=r"^\d{8}$"),
                    window: str = Query("5y", pattern="^(3y|5y|10y|all)$")):
    today = date.today().strftime("%Y%m%d")
    end_day = end or today
    default_days = {"3y": 365 * 3, "5y": 365 * 5, "10y": 365 * 10, "all": 365 * 40}[window]
    start_day = start or (datetime.strptime(end_day, "%Y%m%d").date() - timedelta(days=default_days)).strftime("%Y%m%d")
    if start_day > end_day:
        raise HTTPException(422, detail={"code": "INVALID_DATE_RANGE", "message": "起始日期不得晚于结束日期"})
    yields = read_research_series(DATABASE_PATH, "CSI_DIV_YIELD2_000922", "00010101", end_day)
    bonds = read_research_series(DATABASE_PATH, "CCDC_CN10Y", "00010101", end_day)
    yields_by_day = {row["tradeDate"]: row for row in yields}
    bonds_by_day = {row["tradeDate"]: row for row in bonds}
    days = sorted(set(yields_by_day) | set(bonds_by_day))
    from bisect import bisect_left, bisect_right, insort
    from collections import deque
    from math import isfinite

    window_rows = deque()
    sorted_values = []
    yield_index = 0
    output_rows = []
    window_days = {"3y": 365 * 3, "5y": 365 * 5, "10y": 365 * 10, "all": 365 * 40}[window]
    for day in days:
        dy = yields_by_day.get(day)
        bond = bonds_by_day.get(day)
        history_start = (datetime.strptime(day, "%Y%m%d").date() - timedelta(days=window_days)).strftime("%Y%m%d")
        while yield_index < len(yields) and yields[yield_index]["tradeDate"] <= day:
            row = yields[yield_index]
            window_rows.append(row)
            value = row["value"]
            if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
                insort(sorted_values, value)
            yield_index += 1
        while window_rows and window_rows[0]["tradeDate"] < history_start:
            value = window_rows.popleft()["value"]
            if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
                sorted_values.pop(bisect_left(sorted_values, value))
        if dy is None or bond is None:
            calculated = {"spreadPp": None, "percentile": None, "quality": "MISSING_OFFICIAL"}
        else:
            count = len(sorted_values)
            calculated = {"spreadPp": dy["value"] - bond["value"], "sampleCount": count,
                          "percentile": 100 * bisect_right(sorted_values, dy["value"]) / count if count >= 30 else None,
                          "quality": "READY" if count >= 30 else "INSUFFICIENT_HISTORY"}
        if start_day <= day <= end_day:
            output_rows.append({"tradeDate": day, "observationDate": day, "availableAt": dy.get("availableAt") if dy else None,
                                "dividendYield2Pct": dy["value"] if dy else None,
                                "cn10yPct": bond["value"] if bond else None,
                                "spreadPp": calculated["spreadPp"],
                                "yieldPercentile": calculated["percentile"],
                                "sampleCount": calculated.get("sampleCount", len(sorted_values)),
                                "qualityStatus": calculated["quality"],
                                "yieldSource": dy["provider"] if dy else None,
                                "bondSource": bond["provider"] if bond else None})
    latest_yield = yields[-1] if yields else None
    latest_bond = bonds[-1] if bonds else None
    status = "READY" if latest_yield and latest_bond else "PARTIAL" if latest_yield or latest_bond else "MISSING_OFFICIAL"
    return {"snapshotId": None, "indexCode": "000922", "indexName": "中证红利价格指数",
            "metric": "CSI_DIV_YIELD2", "metricUnit": "%", "spreadUnit": "pp", "window": window,
            "qualityStatus": status, "rows": output_rows,
            "coverage": {"yieldCount": len(yields), "yieldStart": yields[0]["tradeDate"] if yields else None,
                         "yieldEnd": latest_yield["tradeDate"] if latest_yield else None,
                         "bondCount": len(bonds), "bondStart": bonds[0]["tradeDate"] if bonds else None,
                         "bondEnd": latest_bond["tradeDate"] if latest_bond else None,
                         "pairedCount": sum(row["spreadPp"] is not None for row in output_rows)},
            "latest": {"dividendYield2Pct": latest_yield["value"] if latest_yield else None,
                       "yieldDate": latest_yield["tradeDate"] if latest_yield else None,
                       "cn10yPct": latest_bond["value"] if latest_bond else None,
                       "cn10yDate": latest_bond["tradeDate"] if latest_bond else None,
                       "spreadPp": (latest_yield["value"] - latest_bond["value"])
                       if latest_yield and latest_bond and latest_yield["tradeDate"] == latest_bond["tradeDate"] else None},
            "sources": {"yield": research_series_metadata(DATABASE_PATH, "CSI_DIV_YIELD2_000922"),
                        "bond": research_series_metadata(DATABASE_PATH, "CCDC_CN10Y")},
            "message": "股息率2源为中证官方滚动XLS窗口，由本地按次保存；无历史回填接口的日期仍缺失。股息率和国债收益率只按同日精确对齐，不前值填充。"}


@router.get("/series-quality")
def series_quality(series_id: str = Query(..., pattern="^(CSI_DIV_YIELD2_000922|CCDC_CN10Y)$")):
    rows = read_research_series(DATABASE_PATH, series_id, "00010101", "99991231", include_revisions=True)
    current = read_research_series(DATABASE_PATH, series_id, "00010101", "99991231")
    return {"seriesId": series_id, "qualityStatus": "READY" if current else "MISSING",
            "observationCount": len(current), "revisionCount": len(rows),
            "startDate": current[0]["tradeDate"] if current else None,
            "endDate": current[-1]["tradeDate"] if current else None,
            "metadata": research_series_metadata(DATABASE_PATH, series_id), "revisions": rows}


@router.post("/refresh")
def refresh_research_data(start: Optional[str] = Query(None, pattern=r"^\d{8}$"),
                          end: Optional[str] = Query(None, pattern=r"^\d{8}$")):
    end_day = end or date.today().strftime("%Y%m%d")
    start_day = start or DEFAULT_RESEARCH_START_DATE
    result = sync_research_sources(DATABASE_PATH, ROOT / "data", start_day, end_day)
    # FastAPI's return value is kept serializable; a partial source failure is data, not an HTTP crash.
    return JSONResponse(status_code=200 if result["status"] == "READY" else 207, content=result)
