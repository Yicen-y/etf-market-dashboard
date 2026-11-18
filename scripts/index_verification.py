"""Non-destructive index audit and reference reconciliation.

Run with ``python -m scripts.index_verification audit|verify-recent|verify-full|verify-code|report``.
Reference observations never update index_prices or published JSON snapshots.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .backup_db import backup_database
from .config import DATA_ROOT, DATABASE_PATH, INDEXES, STRATEGIES
from .nontrading_candidates import is_retired_nontrading_candidate

SCHEMA = """
CREATE TABLE IF NOT EXISTS index_verification_runs (
 run_id TEXT PRIMARY KEY, mode TEXT NOT NULL, started_at TEXT NOT NULL,
 request_json TEXT NOT NULL, status TEXT NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS index_reference_batches (
 batch_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, index_code TEXT NOT NULL,
 provider TEXT NOT NULL, upstream TEXT NOT NULL, requested_json TEXT NOT NULL,
 fetched_at TEXT NOT NULL, raw_sha256 TEXT, raw_path TEXT, identity_json TEXT NOT NULL,
 coverage_start TEXT, coverage_end TEXT, status TEXT NOT NULL,
 FOREIGN KEY(run_id) REFERENCES index_verification_runs(run_id)
);
CREATE TABLE IF NOT EXISTS index_reference_observations (
 batch_id TEXT NOT NULL, trade_date TEXT NOT NULL, ordinal INTEGER NOT NULL,
 close_value REAL NOT NULL, data_status TEXT,
 PRIMARY KEY(batch_id, ordinal),
 FOREIGN KEY(batch_id) REFERENCES index_reference_batches(batch_id)
);
CREATE TABLE IF NOT EXISTS index_route_approvals (
 index_code TEXT NOT NULL, trade_date TEXT NOT NULL, official_batch_id TEXT NOT NULL,
 official_sha256 TEXT NOT NULL, akshare_sha256 TEXT NOT NULL, akshare_path TEXT NOT NULL,
 official_close REAL NOT NULL, akshare_close REAL NOT NULL, checked_at TEXT NOT NULL,
 approval_basis TEXT NOT NULL, PRIMARY KEY(index_code,trade_date)
);
CREATE TABLE IF NOT EXISTS index_verification_results (
 run_id TEXT NOT NULL, index_code TEXT NOT NULL, trade_date TEXT NOT NULL,
 status TEXT NOT NULL, local_close REAL, reference_close REAL, delta REAL,
 daily_return_delta REAL, cumulative_return_delta REAL, detail TEXT NOT NULL,
 batch_id TEXT, PRIMARY KEY(run_id,index_code,trade_date),
 FOREIGN KEY(run_id) REFERENCES index_verification_runs(run_id)
);
CREATE TABLE IF NOT EXISTS index_reference_revisions (
 batch_id TEXT NOT NULL, old_sha256 TEXT NOT NULL, new_sha256 TEXT NOT NULL,
 detected_at TEXT NOT NULL, PRIMARY KEY(batch_id,old_sha256,new_sha256)
);
CREATE TABLE IF NOT EXISTS index_reference_failures (
 batch_id TEXT NOT NULL, signature TEXT NOT NULL, observed_at TEXT NOT NULL,
 diagnostic_json TEXT NOT NULL, PRIMARY KEY(batch_id,signature)
);
CREATE TABLE IF NOT EXISTS index_verification_reassessments (
 batch_id TEXT NOT NULL, trade_date TEXT NOT NULL, old_status TEXT NOT NULL,
 new_status TEXT NOT NULL, assessed_at TEXT NOT NULL, evidence_url TEXT,
 PRIMARY KEY(batch_id,trade_date,old_status,new_status)
);
CREATE INDEX IF NOT EXISTS ix_index_verification_results_code_date
 ON index_verification_results(index_code,trade_date);
"""

CSI_FACTSHEETS = {
    "H00821": ("000821", "20041231"), "H00300": ("000300", "20041231"),
    "H00918": ("000918", "20041231"), "H00919": ("000919", "20041231"),
    "932000CNY010": ("932000", "20131231"), "H00811": ("000811", "20041231"),
    "H00813": ("000813", "20041231"), "H20180": ("399986", "20041231"),
    "H20035": ("H30035", "20041231"), "H00922": ("000922", "20041231"),
    "H20903": ("930903", "19991231"), "H20915": ("930915", "20141114"),
}
OFFICIAL_IDENTITY = {code:
    f"https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/{stem}factsheet.pdf"
    for code,(stem,_) in CSI_FACTSHEETS.items()}
CNI_IDENTITY = {
    "480080":"https://www.cnindex.com.cn/html2pdf/preview/jj_980080.pdf",
    "480081":"https://www.cnindex.com.cn/html2pdf/preview/jj_980081.pdf",
}


class ReferenceHTTPError(RuntimeError):
    def __init__(self, status, body_sha256, content_type, endpoint="CSI index-perf",
                 request_params=None, requested_at=None, attempts=1):
        self.diagnostic = {"endpoint":endpoint,"http_status":status,
                           "body_sha256":body_sha256,"content_type":content_type,
                           "request_params":request_params,"requested_at":requested_at or datetime.now(timezone.utc).isoformat(),
                           "attempts":attempts}
        super().__init__(f"{endpoint.split()[0]}_HTTP_{status}")


class ReferenceTransportError(RuntimeError):
    def __init__(self, error_type: str, attempts: int):
        self.diagnostic = {"error_type":error_type,"attempts":attempts}
        super().__init__(f"reference transport failed after {attempts} attempts")


def _reference_get(url, params):
    """Retry bounded transport faults only; never retry 403 or malformed data."""
    import os
    import time
    import requests

    retries = min(2,max(0,int(os.environ.get("INDEX_REFERENCE_RETRIES","1"))))
    for attempt in range(1,retries+2):
        try:
            requested_at = datetime.now(timezone.utc).isoformat()
            response = requests.get(url,params=params,timeout=20)
            try:
                response.reference_attempts = attempt
                response.reference_requested_at = requested_at
            except AttributeError:
                pass  # Minimal response stand-ins need not support metadata.
            return response
        except (requests.Timeout,requests.ConnectionError) as error:
            if attempt > retries:
                raise ReferenceTransportError(type(error).__name__,attempt) from error
            time.sleep(min(attempt,2)*0.5)


def connect(path: Path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def migrate(connection):
    connection.executescript(SCHEMA)


def expected_identity(code):
    item = INDEXES[code]
    return {"code": code, "name": item["name"], "return_type": item.get("returnType", "total_return"),
            "currency": item.get("currency", "CNY"), "publisher": "CNI" if code in ("480080", "480081") else "CSI",
            "base_date": CSI_FACTSHEETS[code][1] if code in CSI_FACTSHEETS else "20121231",
            "calendar": "CSI_NATIVE" if code == "H20915" else "MAINLAND"}


def identity_status(expected, observed):
    if not observed:
        return "NO_REFERENCE"
    for key in ("code", "return_type", "currency", "publisher"):
        if observed.get(key) != expected.get(key):
            return "IDENTITY_CONFLICT" if observed.get(key) is not None else "IDENTITY_UNCONFIRMED"
    if expected.get("base_date") and observed.get("base_date") != expected["base_date"]:
        return "IDENTITY_CONFLICT" if observed.get("base_date") else "IDENTITY_UNCONFIRMED"
    return "MATCH"


def independent_upstreams(sources):
    """Provider wrappers pointing at the same publisher count once."""
    return len({source["upstream"] for source in sources if source.get("upstream")})


def reconcile(local, reference, *, identity, calendar=None, decimals=2):
    """Compare published precision; calendar=None means no authoritative calendar."""
    local_by_day = defaultdict(list)
    ref_by_day = defaultdict(list)
    for row in local:
        local_by_day[row["tradeDate"]].append(row)
    for row in reference:
        ref_by_day[row["tradeDate"]].append(row)
    tolerance = Decimal(1).scaleb(-decimals) / 2
    output = []
    prior = None
    first = None
    for day in sorted(set(local_by_day) | set(ref_by_day)):
        own, other = local_by_day[day], ref_by_day[day]
        a = Decimal(str(own[0]["closeValue"])) if own else None
        b = Decimal(str(other[0]["closeValue"])) if other else None
        detail = []
        if len(own) > 1 or len(other) > 1:
            status = "DUPLICATE_DATE"
        elif calendar is not None and day not in calendar:
            status = "CALENDAR_EXCEPTION"
        elif not own:
            status = "MISSING_LOCAL"
        elif not other:
            status = "NO_REFERENCE"
        elif other[0].get("dataStatus") == "RECOVERED_FROM_NEXT_DAY_ABSOLUTE_CHANGE":
            status = "DERIVED_REFERENCE"
        elif other[0].get("dataStatus") == "ZERO_TRADING_VOLUME":
            status = "CALENDAR_REVIEW"
        elif a <= 0 or b <= 0:
            status = "INVALID_VALUE"
        elif abs(a - b) > tolerance:
            status = "MISMATCH"
        elif identity != "MATCH":
            status = identity
        else:
            status = "MATCH"
        delta = float(a-b) if a is not None and b is not None else None
        daily = float(a/prior[0] - b/prior[1]) if prior and a and b and prior[0] and prior[1] else None
        if a and b and first is None:
            first = (a,b)
        cumulative = float(a/first[0] - b/first[1]) if a and b and first else None
        if a and b and status not in ("DUPLICATE_DATE", "INVALID_VALUE"):
            prior = (a,b)
        if daily is not None and abs(daily) > float(tolerance / b) * 2:
            detail.append("RETURN_DIFFERENCE")
        if cumulative is not None and b and abs(cumulative) > float(tolerance / b) * 2:
            detail.append("CUMULATIVE_DIFFERENCE")
        output.append({"tradeDate": day, "status": status, "local": float(a) if a is not None else None,
                       "reference": float(b) if b is not None else None, "delta": delta,
                       "daily_return_delta": daily, "cumulative_return_delta": cumulative,
                       "detail": ",".join(detail)})
    return output


def require_original_response(results, provider):
    """A parsed provider frame can corroborate numbers, not prove raw upstream publication."""
    if provider not in ("CSI official HTTP", "CNI official HTTPS"):
        for item in results:
            if item["status"] == "MATCH":
                item["status"] = "SOURCE_EVIDENCE_INCOMPLETE"
                item["detail"] = "Parsed provider frame only; upstream HTTP response unavailable"
    return results


def _calendar(data_root, code):
    if code == "H20915":
        return None  # only an independently sourced CSI calendar can constrain it
    path = data_root / "verification" / "mainland_calendar.json"
    if path.exists():
        return set(json.loads(path.read_text(encoding="utf-8"))["dates"])
    return None


def capture_mainland_calendar(data_root=DATA_ROOT):
    """Capture Sina exchange dates through AkShare with a source hash."""
    import akshare as ak
    frame = ak.tool_trade_date_hist_sina()
    if frame is None or frame.empty or "trade_date" not in frame:
        raise RuntimeError("mainland exchange calendar unavailable")
    raw = frame.to_json(orient="records",date_format="iso").encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    directory = data_root / "verification" / "raw"
    directory.mkdir(parents=True,exist_ok=True)
    path = directory / f"{digest}.json"
    if not path.exists():
        path.write_bytes(raw)
    dates = sorted({d.strftime("%Y%m%d") for d in frame["trade_date"].dropna()})
    result = {"source":"AkShare/Sina exchange calendar","fetched_at":datetime.now(timezone.utc).isoformat(),
              "raw_sha256":digest,"raw_path":str(path),"covered_through":dates[-1],"dates":dates}
    output=data_root / "verification" / "mainland_calendar.json"
    output.write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8")
    return result


def audit(database=DATABASE_PATH, output=None, data_root=DATA_ROOT):
    output = output or data_root / "verification" / "baseline"
    output.mkdir(parents=True, exist_ok=True)
    backup = output / "audit.sqlite"
    if backup.exists():
        backup = output / f"audit-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.sqlite"
    backup_info = backup_database(database, backup)
    with connect(backup) as db:
        rows = [dict(r) for r in db.execute("SELECT trade_date,index_code,close_value,source FROM index_prices ORDER BY index_code,trade_date")]
        issues = [dict(r) for r in db.execute("SELECT symbol,trade_date,issue_code,resolution_status FROM quality_issues WHERE kind='index'")]
    by_code = defaultdict(list)
    for row in rows:
        if row["index_code"] in INDEXES:
            by_code[row["index_code"]].append(row)
    summaries = {}
    anomalies = []
    for code in INDEXES:
        series = by_code[code]
        dates = Counter(r["trade_date"] for r in series)
        jumps = []
        for before, after in zip(series, series[1:]):
            if before["close_value"] > 0 and abs(after["close_value"] / before["close_value"] - 1) > .15:
                jumps.append({"date": after["trade_date"], "return": after["close_value"] / before["close_value"] - 1})
        nonpositive = [r["trade_date"] for r in series if r["close_value"] <= 0]
        duplicates = [day for day, n in dates.items() if n > 1]
        weekend = [day for day in dates if datetime.strptime(day, "%Y%m%d").weekday() >= 5]
        known_calendar = _calendar(data_root, code)
        missing = sorted(d for d in known_calendar if min(dates,default="9") <= d <= max(dates,default="0") and d not in dates) if known_calendar else []
        # A local calendar alone cannot establish historic coverage. Missing dates
        # are finalized during reference reconciliation using observed source dates.
        existing = [i for i in issues if i["symbol"] == code]
        summaries[code] = {"name": INDEXES[code]["name"], "count": len(series),
                           "start": min(dates, default=None), "end": max(dates, default=None),
                           "unknown_source": sum(r["source"] == "PROVENANCE_UNKNOWN" for r in series),
                           "duplicate_dates": duplicates, "nonpositive_dates": nonpositive,
                           "weekend_dates": weekend, "suspect_jumps": jumps,
                           "missing_trading_days": missing, "missing_calendar_status": "PENDING_REFERENCE",
                           "quality_issues": Counter(i["issue_code"] for i in existing),
                           "open_issues": sum(i["resolution_status"] == "open" for i in existing),
                           "historic_issues_absent_from_prices": sum(i["trade_date"] not in dates for i in existing)}
        anomalies += [{"index_code": code, "trade_date": d, "kind": "WEEKEND_RECORD"} for d in weekend]
        anomalies += [{"index_code": code, "trade_date": j["date"], "kind": "SUSPECT_JUMP", "return": j["return"]} for j in jumps]
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "backup": backup_info,
               "total_index_rows": len(rows), "registered_rows": sum(x["count"] for x in summaries.values()),
               "indexes": summaries, "anomalies": anomalies}
    (output / "baseline.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=list), encoding="utf-8")
    lines = ["# 指数基线审计", "", f"SQLite 一致性副本：`{backup}`；完整性：{backup_info['integrity']}。", "",
             f"记录总数：{len(rows)}。缺失交易日需由实际参考序列确认。", "",
             "| 指数 | 记录 | 起止 | 来源未知 | 周末记录 | 可疑跳变 | 历史问题不在正式表 |", "|---|---:|---|---:|---:|---:|---:|"]
    for code, s in summaries.items():
        lines.append(f"| {code} | {s['count']} | {s['start']}–{s['end']} | {s['unknown_source']} | {len(s['weekend_dates'])} | {len(s['suspect_jumps'])} | {s['historic_issues_absent_from_prices']} |")
    (output / "baseline.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    return payload


def _fetch(code, start, end):
    from datetime import datetime, timedelta
    from .fetch_data import FetchResult
    if code in ("480080", "480081"):
        url = "https://hq.cnindex.com.cn/market/market/getIndexDailyDataWithDataFormat"
        params = {"indexCode":code,"startDate":datetime.strptime(start,"%Y%m%d").strftime("%Y-%m-%d"),
                  "endDate":datetime.strptime(end,"%Y%m%d").strftime("%Y-%m-%d"),"frequency":"day"}
        response = _reference_get(url,params)
        if not response.ok:
            raise ReferenceHTTPError(response.status_code,hashlib.sha256(response.content).hexdigest(),response.headers.get("content-type"),"CNI daily-history",
                                     params,getattr(response,"reference_requested_at",None),getattr(response,"reference_attempts",1))
        payload=response.json()
        matrix=payload.get("data",{}).get("data")
        if not isinstance(matrix,list):
            raise ValueError("CNI reference schema changed")
        rows=[]
        for entry in matrix:
            if len(entry)<6:
                raise ValueError("CNI reference row schema changed")
            day=str(entry[0]).replace("-","")[:8]
            if start<=day<=end:
                rows.append({"tradeDate":day,"indexCode":code,"closeValue":float(entry[5])})
        if not rows:
            raise RuntimeError("CNI returned no reference observations")
        return FetchResult(rows=rows,provider="CNI official HTTPS",upstream="CNI",request=params,
                           raw_bytes=response.content,source_url=url,price_basis="OFFICIAL_DAILY_CLOSE")
    upstream_end = (datetime.strptime(end,"%Y%m%d")+timedelta(days=1)).strftime("%Y%m%d")
    url = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
    params = {"indexCode":code,"startDate":start,"endDate":upstream_end}
    response = _reference_get(url,params)
    if not response.ok:
        raise ReferenceHTTPError(response.status_code,hashlib.sha256(response.content).hexdigest(),
                                 response.headers.get("content-type"),request_params=params,
                                 requested_at=getattr(response,"reference_requested_at",None),
                                 attempts=getattr(response,"reference_attempts",1))
    payload = response.json()
    if payload.get("success") is not True or str(payload.get("code")) != "200" or not isinstance(payload.get("data"),list):
        raise ValueError("CSI response schema or status changed")
    rows = []
    for item in payload["data"]:
        if item.get("indexCode") != code:
            raise ValueError("CSI reference identity code mismatch")
        day = str(item.get("tradeDate", "")).replace("-", "")[:8]
        if start <= day <= end:
            rows.append({"tradeDate":day,"indexCode":code,"closeValue":float(item["close"]),
                         "indexNameEnAll":item.get("indexNameEnAll"),
                         "change":item.get("change"),"tradingVol":item.get("tradingVol"),
                         "dataStatus":"ZERO_TRADING_VOLUME" if item.get("tradingVol")==0 else None})
    if not rows:
        raise RuntimeError("CSI returned no reference observations")
    return FetchResult(rows=rows,provider="CSI official HTTP",upstream="CSI",request=params,
                       raw_bytes=response.content,source_url=url,price_basis="OFFICIAL_DAILY_CLOSE")


def verify(database, data_root, codes, mode, limit=None, batch_size=250,
           start_date=None, end_date=None, resume=False, request_delay=0):
    now = datetime.now(timezone.utc).isoformat()
    csi_blocked = False
    failed_batches = 0
    with connect(database) as db:
        migrate(db)
        for code in codes:
            local = [dict(r) for r in db.execute("SELECT trade_date AS tradeDate,close_value AS closeValue,source FROM index_prices WHERE index_code=? ORDER BY trade_date", (code,))]
            if start_date:
                local = [r for r in local if r["tradeDate"] >= start_date]
            if end_date:
                local = [r for r in local if r["tradeDate"] <= end_date]
            if limit:
                local = local[-limit:]
            if not local:
                continue
            window_start = start_date or local[0]["tradeDate"]
            window_end = end_date or local[-1]["tradeDate"]
            run_id = hashlib.sha256(json.dumps([mode,code,window_start,window_end]).encode()).hexdigest()[:24]
            db.execute("INSERT INTO index_verification_runs VALUES (?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET started_at=excluded.started_at,status=excluded.status,error=NULL",
                       (run_id,mode,now,json.dumps({"code":code,"limit":limit,"start":window_start,"end":window_end}),"RUNNING",None))
            db.commit()
            windows = [(local,local[0]["tradeDate"],window_end if mode=="verify-daily" else local[-1]["tradeDate"])] if start_date or end_date else [
                (local[offset:offset+batch_size],local[offset]["tradeDate"],local[min(offset+batch_size,len(local))-1]["tradeDate"])
                for offset in range(0,len(local),batch_size)]
            for part,start,end in windows:
                batch_id = hashlib.sha256(f"{run_id}:{start}:{end}".encode()).hexdigest()[:24]
                if resume and db.execute("SELECT 1 FROM index_reference_batches WHERE batch_id=? AND status='FETCHED'",(batch_id,)).fetchone():
                    continue
                expected = expected_identity(code)
                try:
                    if csi_blocked and expected["publisher"] == "CSI":
                        raise RuntimeError("CSI access blocked earlier in this run")
                    fetched = _fetch(code,start,end)
                    if request_delay:
                        import time
                        time.sleep(request_delay)
                    reference = [r for r in fetched.rows if start <= r["tradeDate"] <= end]
                    # AkShare's daily-history endpoints return code and price but
                    # not official identity metadata. Do not infer an identity pass.
                    official_url = OFFICIAL_IDENTITY.get(code) if fetched.upstream == "CSI" else CNI_IDENTITY.get(code)
                    english_name = reference[0].get("indexNameEnAll","") if reference else ""
                    confirmed_return = ("total_return" if "Total Return Index" in english_name else
                                        "price_or_other" if english_name else None)
                    confirmed_currency = "CNY" if "(CNY)" in english_name or official_url else None
                    observed = {"code":code,"publisher":fetched.upstream,
                                "return_type":confirmed_return or ("total_return" if official_url else None),
                                "currency":confirmed_currency if fetched.upstream=="CSI" else None,
                                "base_date":CSI_FACTSHEETS[code][1] if code in CSI_FACTSHEETS else ("20121231" if official_url else None),
                                "reference_name_en":english_name,
                                "reference_url":fetched.source_url,
                                "identity_evidence_url":official_url}
                    check = identity_status(expected,observed)
                    raw = fetched.raw_bytes
                    raw_hash = hashlib.sha256(raw).hexdigest() if raw else None
                    raw_dir = data_root / "verification" / "raw"
                    raw_dir.mkdir(parents=True,exist_ok=True)
                    raw_path = raw_dir / f"{raw_hash}.json" if raw_hash else None
                    if raw_path and not raw_path.exists():
                        raw_path.write_bytes(raw)
                    status = "FETCHED" if reference else "EMPTY"
                    error = None; failure_diagnostic = None
                except Exception as exc:
                    failed_batches += 1
                    if (isinstance(exc,ReferenceHTTPError) and exc.diagnostic["http_status"] == 403
                            and expected["publisher"] == "CSI"):
                        csi_blocked = True
                    fetched = None; reference = []; observed = {}; check = "NO_REFERENCE"
                    raw_hash = None; raw_path = None; status = "UNAVAILABLE"; error = f"{type(exc).__name__}: {exc}"
                    failure_diagnostic = getattr(exc,"diagnostic",{"error_type":type(exc).__name__})
                observed_at = datetime.now(timezone.utc).isoformat()
                with db:
                    old = db.execute("SELECT raw_sha256 FROM index_reference_batches WHERE batch_id=?",(batch_id,)).fetchone()
                    if error:
                        signature = hashlib.sha256(json.dumps(failure_diagnostic,sort_keys=True).encode()).hexdigest()[:20]
                        db.execute("INSERT INTO index_reference_failures VALUES (?,?,?,?) ON CONFLICT(batch_id,signature) DO UPDATE SET observed_at=excluded.observed_at",
                                   (batch_id,signature,observed_at,json.dumps(failure_diagnostic)))
                        if old and old[0]:
                            continue  # retain last valid evidence on a later fetch failure
                    previous_values = [(r[0],r[1]) for r in db.execute(
                        "SELECT trade_date,close_value FROM index_reference_observations WHERE batch_id=? ORDER BY ordinal",(batch_id,))]
                    new_values = [(r["tradeDate"],r["closeValue"]) for r in reference]
                    if old and old[0] and raw_hash and old[0] != raw_hash and previous_values != new_values:
                        db.execute("INSERT OR IGNORE INTO index_reference_revisions VALUES (?,?,?,?)",(batch_id,old[0],raw_hash,observed_at))
                    db.execute("INSERT INTO index_reference_batches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(batch_id) DO UPDATE SET provider=excluded.provider,upstream=excluded.upstream,requested_json=excluded.requested_json,fetched_at=excluded.fetched_at,raw_sha256=excluded.raw_sha256,raw_path=excluded.raw_path,status=excluded.status,identity_json=excluded.identity_json,coverage_start=excluded.coverage_start,coverage_end=excluded.coverage_end",
                               (batch_id,run_id,code,fetched.provider if fetched else "AkShare",fetched.upstream if fetched else expected["publisher"],
                                json.dumps({"code":code,"start":start,"end":end,
                                            "actual_request":getattr(fetched,"request",None) if getattr(fetched,"request",None) else ({"indexCode":code,"startDate":start,
                                                "endDate":(datetime.strptime(end,"%Y%m%d")+timedelta(days=1)).strftime("%Y%m%d")}
                                                if expected["publisher"]=="CSI" else
                                                {"indexCode":code,"startDate":datetime.strptime(start,"%Y%m%d").strftime("%Y-%m-%d"),
                                                 "endDate":datetime.strptime(end,"%Y%m%d").strftime("%Y-%m-%d"),"frequency":"day"})}),
                                observed_at,raw_hash,str(raw_path) if raw_path else None,
                                json.dumps({"expected":expected,"observed":observed,"error":error}),
                                min((r["tradeDate"] for r in reference),default=None),max((r["tradeDate"] for r in reference),default=None),status))
                    db.execute("DELETE FROM index_reference_observations WHERE batch_id=?",(batch_id,))
                    db.executemany("INSERT INTO index_reference_observations VALUES (?,?,?,?,?)",
                                   [(batch_id,r["tradeDate"],i,r["closeValue"],r.get("dataStatus")) for i,r in enumerate(reference)])
                    results = require_original_response(
                        reconcile(part,reference,identity=check,calendar=_calendar(data_root,code),decimals=4 if code in CNI_IDENTITY else 2),
                        fetched.provider if fetched else "UNAVAILABLE")
                    db.executemany("INSERT INTO index_verification_results VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id,index_code,trade_date) DO UPDATE SET status=excluded.status,local_close=excluded.local_close,reference_close=excluded.reference_close,delta=excluded.delta,daily_return_delta=excluded.daily_return_delta,cumulative_return_delta=excluded.cumulative_return_delta,detail=excluded.detail,batch_id=excluded.batch_id",
                                   [(run_id,code,r["tradeDate"],r["status"],r["local"],r["reference"],r["delta"],r["daily_return_delta"],r["cumulative_return_delta"],r["detail"] or (error or ""),batch_id) for r in results])
                    if mode == "verify-daily":
                        for item in results:
                            if item["status"] not in ("MISMATCH","IDENTITY_CONFLICT","INVALID_VALUE","CALENDAR_EXCEPTION"):
                                continue
                            issue = "REFERENCE_" + item["status"]
                            if not db.execute("SELECT 1 FROM quality_issues WHERE symbol=? AND kind='index' AND trade_date=? AND issue_code=?",
                                              (code,item["tradeDate"],issue)).fetchone():
                                db.execute("INSERT INTO quality_issues(symbol,kind,trade_date,issue_code,severity,detected_at,batch_id) VALUES (?,'index',?,?,'BLOCKED',?,?)",
                                           (code,item["tradeDate"],issue,now,run_id))
            with db:
                db.execute("UPDATE index_verification_runs SET status='COMPLETED' WHERE run_id=?",(run_id,))
    return failed_batches


def reassess_saved(database=DATABASE_PATH, data_root=DATA_ROOT):
    """Recompute assessments from saved HTTP bodies without contacting providers."""
    changed = 0
    with connect(database) as db:
        migrate(db)
        batches = [dict(r) for r in db.execute("SELECT * FROM index_reference_batches WHERE status='FETCHED' AND raw_path IS NOT NULL")]
        for batch in batches:
            path = Path(batch["raw_path"])
            if not path.is_file():
                continue
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != batch["raw_sha256"]:
                raise ValueError(f"reference hash mismatch: {batch['batch_id']}")
            payload = json.loads(raw)
            code = batch["index_code"]
            request = json.loads(batch["requested_json"])
            start,end = request["start"],request["end"]
            if "actual_request" not in request:
                request["actual_request"] = ({"indexCode":code,"startDate":start,
                    "endDate":(datetime.strptime(end,"%Y%m%d")+timedelta(days=1)).strftime("%Y%m%d")}
                    if batch["upstream"]=="CSI" else {"symbol":code,"start_date":start,"end_date":end})
                with db:
                    db.execute("UPDATE index_reference_batches SET requested_json=? WHERE batch_id=?",
                               (json.dumps(request),batch["batch_id"]))
            if (batch["upstream"] == "CNI" and isinstance(payload,dict)
                    and isinstance(payload.get("data"),dict) and isinstance(payload["data"].get("data"),list)):
                reference = [{"tradeDate":str(r[0]).replace("-","")[:8],"closeValue":float(r[5])}
                             for r in payload["data"]["data"] if len(r)>=6
                             and start<=str(r[0]).replace("-","")[:8]<=end]
                english = ""
                request["actual_request"] = {"indexCode":code,"startDate":datetime.strptime(start,"%Y%m%d").strftime("%Y-%m-%d"),
                    "endDate":datetime.strptime(end,"%Y%m%d").strftime("%Y-%m-%d"),"frequency":"day"}
            elif isinstance(payload,dict) and isinstance(payload.get("data"),list):
                reference = [{"tradeDate":str(r["tradeDate"]).replace("-","")[:8],
                              "closeValue":float(r["close"]),
                              "dataStatus":"ZERO_TRADING_VOLUME" if r.get("tradingVol")==0 else None}
                             for r in payload["data"] if r.get("indexCode")==code and start<=str(r.get("tradeDate",""))[:8]<=end]
                english = next((r.get("indexNameEnAll","") for r in payload["data"] if r.get("indexCode")==code),"")
            elif isinstance(payload,list) and payload:
                # AkShare 1.18.64 serializes the CSI frame with stable column
                # order; verify the embedded code before trusting mapped rows.
                if batch["upstream"] != "CSI" or any(len(r)<5 or list(r.values())[1] != code for r in payload):
                    continue
                english = str(list(payload[0].values())[4])
                reference = [{"tradeDate":r[0],"closeValue":r[1],"dataStatus":r[2]}
                             for r in db.execute("SELECT trade_date,close_value,data_status FROM index_reference_observations WHERE batch_id=? ORDER BY ordinal",(batch["batch_id"],))]
            else:
                continue
            local = [dict(r) for r in db.execute("SELECT trade_date AS tradeDate,close_value AS closeValue FROM index_prices WHERE index_code=? AND trade_date BETWEEN ? AND ? ORDER BY trade_date",(code,start,end))]
            url = OFFICIAL_IDENTITY.get(code) or CNI_IDENTITY.get(code)
            observed = {"code":code,"publisher":batch["upstream"],
                        "return_type":"total_return" if "Total Return Index" in english or code in CNI_IDENTITY else None,
                        "currency":"CNY" if code in CSI_FACTSHEETS and (url or "(CNY)" in english) else None,
                        "base_date":CSI_FACTSHEETS[code][1] if code in CSI_FACTSHEETS else ("20121231" if code in CNI_IDENTITY else None),
                        "reference_name_en":english,"identity_evidence_url":url,
                        "reference_url":("https://hq.cnindex.com.cn/market/market/getIndexDailyDataWithDataFormat" if code in CNI_IDENTITY else
                            "https://www.csindex.com.cn/csindex-home/perf/index-perf" if isinstance(payload,dict) else "AkShare stock_zh_index_hist_csindex")}
            status = identity_status(expected_identity(code),observed)
            provider = ("CNI official HTTPS" if code in CNI_IDENTITY and isinstance(payload,dict) else
                        "CSI official HTTP" if isinstance(payload,dict) else batch["provider"])
            results = require_original_response(
                reconcile(local,reference,identity=status,calendar=_calendar(data_root,code),decimals=4 if code in CNI_IDENTITY else 2),provider)
            with db:
                for item in results:
                    old = db.execute("SELECT status FROM index_verification_results WHERE run_id=? AND index_code=? AND trade_date=?",
                                     (batch["run_id"],code,item["tradeDate"])).fetchone()
                    if old and old[0] != item["status"]:
                        db.execute("INSERT OR IGNORE INTO index_verification_reassessments VALUES (?,?,?,?,?,?)",
                                   (batch["batch_id"],item["tradeDate"],old[0],item["status"],datetime.now(timezone.utc).isoformat(),url))
                        changed += 1
                    db.execute("INSERT INTO index_verification_results VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id,index_code,trade_date) DO UPDATE SET status=excluded.status,local_close=excluded.local_close,reference_close=excluded.reference_close,delta=excluded.delta,daily_return_delta=excluded.daily_return_delta,cumulative_return_delta=excluded.cumulative_return_delta,detail=excluded.detail,batch_id=excluded.batch_id",
                               (batch["run_id"],code,item["tradeDate"],item["status"],item["local"],item["reference"],item["delta"],item["daily_return_delta"],item["cumulative_return_delta"],item["detail"],batch["batch_id"]))
                db.execute("UPDATE index_reference_batches SET identity_json=?,provider=?,requested_json=?,coverage_start=?,coverage_end=? WHERE batch_id=?",
                           (json.dumps({"expected":expected_identity(code),"observed":observed},ensure_ascii=False),
                            provider,
                            json.dumps(request),min((r["tradeDate"] for r in reference),default=None),
                            max((r["tradeDate"] for r in reference),default=None),batch["batch_id"]))
    return changed


def collect_cni_route_approvals(database, data_root, code, start, end, *, fetcher=None):
    """Archive AkShare's parsed CNI frame and same-day issuer comparisons.

    This is a user-approved same-upstream route check, not currency evidence or
    an independent provider observation.
    """
    if code not in CNI_IDENTITY:
        raise ValueError("CNI route approval is restricted to registered CNI codes")
    if fetcher is None:
        from .fetch_data import fetch_index_history
        fetcher = fetch_index_history
    fetched = fetcher(code, start, end)
    if fetched.provider != "AkShare" or fetched.upstream != "CNI" or not fetched.raw_bytes:
        raise ValueError("AkShare CNI route evidence unavailable")
    raw = fetched.raw_bytes
    digest = hashlib.sha256(raw).hexdigest()
    # AkShare's raw_bytes are its parsed DataFrame, not the upstream HTTP body.
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("AkShare CNI frame schema changed")
    route_rows = {row["tradeDate"]: Decimal(str(row["closeValue"])) for row in fetched.rows
                  if start <= row["tradeDate"] <= end}
    frame_rows = {str(row["日期"])[:10].replace("-", ""): Decimal(str(row["收盘价"]))
                  for row in parsed if isinstance(row, dict) and "日期" in row and "收盘价" in row}
    if any(frame_rows.get(day) != value for day, value in route_rows.items()):
        raise ValueError("AkShare parsed frame and mapped closes differ")
    if not route_rows:
        raise ValueError("AkShare CNI returned no overlapping dates")
    archive = Path(data_root) / "verification" / "cni-route" / f"{digest}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        archive.write_bytes(raw)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
        raise ValueError("AkShare CNI frame archive changed")
    approved = []
    with connect(database) as db:
        migrate(db)
        for day, value in route_rows.items():
            official = db.execute("""SELECT b.batch_id,b.raw_sha256,b.raw_path,o.close_value,
                b.identity_json FROM index_reference_observations o
                JOIN index_reference_batches b ON b.batch_id=o.batch_id
                WHERE b.index_code=? AND o.trade_date=? AND b.provider='CNI official HTTPS'
                AND b.status='FETCHED' ORDER BY b.fetched_at DESC LIMIT 1""", (code, day)).fetchone()
            if not official or not official[1] or not official[2]:
                continue
            official_path = Path(official[2])
            if not official_path.is_file() or hashlib.sha256(official_path.read_bytes()).hexdigest() != official[1]:
                continue
            observed = json.loads(official[4]).get("observed", {})
            expected = expected_identity(code)
            if any(observed.get(key) != expected[key] for key in ("code", "publisher", "return_type", "base_date")):
                continue
            official_value = Decimal(str(official[3]))
            delta = abs(official_value - value)
            if observed.get("currency") is not None or delta >= USER_CHANNEL_POINT_TOLERANCE or value <= 0:
                continue
            basis = ("USER_APPROVED_SAME_UPSTREAM_NUMERIC_MATCH" if delta == 0
                     else "USER_APPROVED_CHANNEL_POINT_DELTA_LT_0_05")
            db.execute("""INSERT INTO index_route_approvals VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(index_code,trade_date) DO UPDATE SET
                official_batch_id=excluded.official_batch_id,official_sha256=excluded.official_sha256,
                akshare_sha256=excluded.akshare_sha256,akshare_path=excluded.akshare_path,
                official_close=excluded.official_close,akshare_close=excluded.akshare_close,
                checked_at=excluded.checked_at,approval_basis=excluded.approval_basis""",
                (code,day,official[0],official[1],digest,str(archive),float(official_value),float(value),
                 datetime.now(timezone.utc).isoformat(),basis))
            approved.append(day)
        db.commit()
    return approved


def _cni_route_approved(db, code, day, official_batch_id, official_sha, official_close, observed):
    expected = expected_identity(code)
    if code not in CNI_IDENTITY or observed.get("currency") is not None or any(
            observed.get(key) != expected[key] for key in ("code", "publisher", "return_type", "base_date")):
        return False
    row = db.execute("""SELECT official_sha256,akshare_sha256,akshare_path,
        official_close,akshare_close,approval_basis FROM index_route_approvals
        WHERE index_code=? AND trade_date=? AND official_batch_id=?""",
        (code,day,official_batch_id)).fetchone()
    if not row or row[0] != official_sha or row[5] not in (
            "USER_APPROVED_SAME_UPSTREAM_NUMERIC_MATCH", "USER_APPROVED_CHANNEL_POINT_DELTA_LT_0_05"):
        return False
    path = Path(row[2])
    recorded_official, recorded_akshare = Decimal(str(row[3])), Decimal(str(row[4]))
    delta = abs(recorded_official-recorded_akshare)
    return (path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row[1]
            and recorded_official == Decimal(str(official_close))
            and (delta == 0 if row[5] == "USER_APPROVED_SAME_UPSTREAM_NUMERIC_MATCH"
                 else Decimal("0") < delta < USER_CHANNEL_POINT_TOLERANCE))


USER_CHANNEL_POINT_TOLERANCE = Decimal("0.05")
ALTERNATE_INDEX_PROVIDERS = frozenset({"AkShare", "ETFirst", "HTBR", "Wind MCP"})
INCOMPATIBLE_PRICE_BASES = frozenset({"PRICE_INDEX", "PRICE_RETURN", "UNADJUSTED_CLOSE"})


def _archived_channel_matches(database, db, code, day, value):
    """Find the selected published value in an intact archived provider response."""
    has_raw = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='raw_observations'").fetchone()
    has_prices = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='index_prices'").fetchone()
    if not has_raw or not has_prices:
        return False
    selected = db.execute("SELECT source,close_value FROM index_prices WHERE index_code=? AND trade_date=?",
                          (code, day)).fetchone()
    if not selected or selected[0] not in ALTERNATE_INDEX_PROVIDERS or Decimal(str(selected[1])) != value:
        return False
    rows = db.execute("""SELECT raw_sha256,fetch_batch_id,source_version FROM raw_observations
        WHERE kind='index' AND symbol=? AND trade_date=? AND provider=? AND value_raw=?
        ORDER BY raw_record_id DESC LIMIT 20""", (code, day, selected[0], str(value))).fetchall()
    for digest, batch, basis in rows:
        if (basis.split("/", 1)[0] in INCOMPATIBLE_PRICE_BASES
                or not re.fullmatch(r"[a-f0-9]{64}", digest or "")
                or not re.fullmatch(r"[A-Za-z0-9_-]+", batch or "")):
            continue
        for archive in (database.parent / "raw" / "market" / batch).glob(f"*-{digest[:16]}.bin"):
            if archive.is_file() and not archive.is_symlink() and hashlib.sha256(archive.read_bytes()).hexdigest() == digest:
                return True
    return False


def _alternate_channel_evidence(database, db, code, day, value, row):
    provider = row.get("candidate_provider")
    if provider is None:
        return _archived_channel_matches(database, db, code, day, value)
    if provider not in ALTERNATE_INDEX_PROVIDERS:
        return False
    if row.get("candidate_price_basis") in INCOMPATIBLE_PRICE_BASES:
        return False
    path, digest = row.get("candidate_raw_path"), row.get("candidate_raw_sha256")
    if not path or not digest:
        return False
    archive = Path(path)
    return archive.is_file() and not archive.is_symlink() and hashlib.sha256(archive.read_bytes()).hexdigest() == digest


def gate_index_candidates(database, candidates):
    """Require same-basis reference evidence for every candidate before publishing."""
    failures = []
    if not candidates:
        return failures
    with connect(database) as db:
        for row in candidates:
            code, day = row["indexCode"], row["tradeDate"]
            if code == "H20915" and datetime.strptime(day, "%Y%m%d").weekday() >= 5:
                # Its holiday calendar is independent of A shares, but a
                # weekend-stamped candidate needs explicit native-calendar
                # adjudication before publication. Keep the source evidence.
                failures.append((code,day,"CALENDAR_REVIEW"));continue
            refs = db.execute("""SELECT o.close_value,b.identity_json,b.raw_sha256,b.raw_path,b.status,o.data_status,b.provider,b.batch_id
              FROM index_reference_observations o JOIN index_reference_batches b ON b.batch_id=o.batch_id
              WHERE b.index_code=? AND o.trade_date=? ORDER BY b.fetched_at DESC LIMIT 1""",(code,day)).fetchone()
            if not refs or refs[4] != "FETCHED":
                failures.append((code,day,"NO_REFERENCE"));continue
            if refs[5] == "ZERO_TRADING_VOLUME":
                failures.append((code,day,"CALENDAR_EXCEPTION"));continue
            if refs[6] not in ("CSI official HTTP", "CNI official HTTPS"):
                failures.append((code,day,"SOURCE_EVIDENCE_INCOMPLETE"));continue
            observed = json.loads(refs[1]).get("observed",{})
            identity = identity_status(expected_identity(code),observed)
            if identity != "MATCH" and not (identity == "IDENTITY_UNCONFIRMED" and
                    _cni_route_approved(db,code,day,refs[7],refs[2],refs[0],observed)):
                failures.append((code,day,"IDENTITY_UNCONFIRMED"));continue
            path = Path(refs[3]) if refs[3] else None
            if not path or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=refs[2]:
                failures.append((code,day,"REFERENCE_EVIDENCE_MISSING"));continue
            tolerance = Decimal("0.00005") if code in CNI_IDENTITY else Decimal("0.005")
            value = Decimal(str(row["closeValue"]))
            delta = abs(value-Decimal(str(refs[0])))
            if refs[0] <= 0 or value <= 0:
                failures.append((code,day,"MISMATCH"));continue
            if row.get("candidate_price_basis") in INCOMPATIBLE_PRICE_BASES:
                failures.append((code,day,"IDENTITY_CONFLICT"));continue
            if delta <= tolerance:
                continue
            if delta < USER_CHANNEL_POINT_TOLERANCE and _alternate_channel_evidence(Path(database),db,code,day,value,row):
                continue
            if delta < USER_CHANNEL_POINT_TOLERANCE and row.get("candidate_provider") in ALTERNATE_INDEX_PROVIDERS:
                failures.append((code,day,"SOURCE_EVIDENCE_INCOMPLETE"));continue
            failures.append((code,day,"MISMATCH"))
    return failures


def report(database=DATABASE_PATH, output=None):
    output = output or DATA_ROOT / "verification"
    output.mkdir(parents=True,exist_ok=True)
    with connect(database) as db:
        migrate(db)
        observed = [dict(r) for r in db.execute("""SELECT v.*,p.source,b.provider,b.upstream,b.raw_sha256,b.identity_json,run.started_at
          FROM index_verification_results v JOIN index_verification_runs run ON run.run_id=v.run_id
          LEFT JOIN index_prices p ON p.index_code=v.index_code AND p.trade_date=v.trade_date
          LEFT JOIN index_reference_batches b ON b.batch_id=v.batch_id
          WHERE run.status='COMPLETED'
          ORDER BY v.index_code,v.trade_date""")]
        rejected_reference_days = {(r[0],r[1]) for r in db.execute("SELECT symbol,trade_date FROM quality_issues WHERE kind='index' AND issue_code='NON_TRADING_DATE_OBSERVATION'")}
        local_counts = {r[0]:r[1] for r in db.execute("SELECT index_code,COUNT(*) FROM index_prices GROUP BY index_code")}
        source_rows = [dict(r) for r in db.execute("""SELECT index_code,provider,upstream,status,COUNT(*) AS batches,
          MIN(coverage_start) AS first_reference_date,MAX(coverage_end) AS last_reference_date
          FROM index_reference_batches GROUP BY index_code,provider,upstream,status ORDER BY index_code,provider,status""")]
    # Preserve a successfully fetched reference when a later upstream request fails.
    best = {}
    for item in observed:
        key = item["index_code"],item["trade_date"]
        score = (item["reference_close"] is not None,item["provider"] in ("CSI official HTTP","CNI official HTTPS"),item["started_at"])
        if key not in best or score > best[key][0]:
            best[key] = score,item
    rows = [entry[1] for key,entry in sorted(best.items())]
    for item in rows:
        if item["status"] == "MISSING_LOCAL" and ((item["index_code"],item["trade_date"]) in rejected_reference_days
                or is_retired_nontrading_candidate(item["index_code"],item["trade_date"])):
            item["status"] = "CALENDAR_EXCEPTION"
            item["detail"] = "Reference date previously rejected as non-trading in quality_issues"
        if item["index_code"] == "H20915" and item["trade_date"] == "20180618" and item["status"] == "CALENDAR_REVIEW":
            item["status"] = "CALENDAR_EXCEPTION"
            item["detail"] = "HKEX Tuen Ng Festival holiday; CSI zero-volume placeholder"
    summary = {}
    for code in INDEXES:
        selected = [r for r in rows if r["index_code"] == code]
        counts = Counter(r["status"] for r in selected)
        numeric_matches = sum(r["local_close"] is not None and r["reference_close"] is not None
                              and r["reference_close"] > 0 and abs(r["delta"]) <= (0.00005 if code in CNI_IDENTITY else .005) for r in selected)
        conflict_count = sum(counts[k] for k in ("MISMATCH","IDENTITY_CONFLICT","CALENDAR_EXCEPTION","INVALID_VALUE","DUPLICATE_DATE"))
        summary[code] = {"local_records":local_counts.get(code,0),"checked":len(selected),"match":counts["MATCH"],"conflict":conflict_count,
                         "unverified":len(selected)-counts["MATCH"]-conflict_count,
                         "numeric_conflict":counts["MISMATCH"],
                         "calendar_exceptions":counts["CALENDAR_EXCEPTION"],
                         "invalid_values":counts["INVALID_VALUE"],
                         "reference_covered":sum(r["reference_close"] is not None for r in selected),
                         "numeric_match":numeric_matches,
                         "raw_http_covered":sum(r["provider"] in ("CSI official HTTP","CNI official HTTPS") and r["local_close"] is not None and r["reference_close"] is not None for r in selected),
                         "http_match":sum(r["provider"] in ("CSI official HTTP","CNI official HTTPS") and r["status"]=="MATCH" for r in selected),
                         "unknown_source_verified":sum(r["source"]=="PROVENANCE_UNKNOWN" and r["status"]=="MATCH" for r in selected),
                         "statuses":dict(counts),"coverage":counts["MATCH"]/len(selected) if selected else 0}
    anomalies = [r for r in rows if r["status"]!="MATCH"]
    years = Counter((r["index_code"],r["trade_date"][:4],r["status"]) for r in anomalies)
    payload = {"generated_at":datetime.now(timezone.utc).isoformat(),"indexes":summary,
               "source_inventory":{code:[r for r in source_rows if r["index_code"]==code] for code in INDEXES},
               "yearly_anomalies":[{"index_code":c,"year":y,"status":s,"count":n} for (c,y,s),n in sorted(years.items())],
               "anomalies":anomalies,"affected_strategies":{s["id"]:[s["a"],s["b"]] for s in STRATEGIES if summary[s["a"]]["conflict"] or summary[s["b"]]["conflict"] or summary[s["a"]]["unverified"] or summary[s["b"]]["unverified"]}}
    (output/"verification-report.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["# 指数参考核验", "", "来源未知但数值通过独立核验不会更改原始采集来源。缺上游原始响应、身份未确认、推导参考值和来源不可用均保持未核验。", "",
           "| 指数 | 本地记录 | 参考覆盖 | 数值一致 | 综合一致 | 冲突 | 未核验 | HTTP 原始响应覆盖 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for code,s in summary.items():
        lines.append(f"| {code} | {s['local_records']} | {s['reference_covered']} | {s['numeric_match']} | {s['match']} | {s['conflict']} | {s['unverified']} | {s['raw_http_covered']} |")
    lines += ["",f"异常与未核验明细见 `verification-report.json`（{len(anomalies)} 条）。",
              "", "## 重点异常", "",
              "- H20915 2026-11-07 本地有记录，中证参考响应无该日；周末日期与 11 月 9 日重复点位需复核原始采集。",
              "- H20180 2013-06-28 本地点位 4303.99 为推导值；中证原始响应为 0.00，不能据此独立确认推导值。",
              "- H20915 2018-06-18 中证响应沿用 6 月 15 日点位且成交量为零；港交所将当天列为端午节假日。",
              "- 2018-06-18 部分其他指数参考接口亦返回点位，原有质量记录将其列为非交易日，归为 CALENDAR_EXCEPTION。",
              "", "## 每日增量方案", "", "收盘后运行 `verify-daily --days 7`，再以 `update_data --require-reference-verification` 执行发布；仅新增或变化的候选点位通过同口径参考证据门禁时才发布。定期使用 `verify-full --resume` 补齐历史失败批次。"]
    (output/"verification-report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return payload


def read_data_center_verification(database=DATABASE_PATH):
    """Read-only data-center adapter; never creates tables or fetches providers."""
    with connect(database) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='index_verification_results'").fetchone():
            return {"status":"NOT_RUN","indexes":{}}
        counts = db.execute("""WITH ranked AS (
          SELECT v.index_code,v.trade_date,v.status,
                 ROW_NUMBER() OVER (PARTITION BY v.index_code,v.trade_date
                   ORDER BY (v.reference_close IS NOT NULL) DESC,(b.provider IN ('CSI official HTTP','CNI official HTTPS')) DESC,r.started_at DESC) AS n
          FROM index_verification_results v JOIN index_verification_runs r ON r.run_id=v.run_id
          LEFT JOIN index_reference_batches b ON b.batch_id=v.batch_id
          WHERE r.status='COMPLETED')
          SELECT index_code,status,COUNT(*) FROM ranked WHERE n=1 GROUP BY index_code,status""").fetchall()
    grouped = defaultdict(dict)
    for code,status,count in counts:
        grouped[code][status] = count
    return {"status":"AVAILABLE","indexes":{code:grouped.get(code,{}) for code in INDEXES}}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("audit","calendar","verify-recent","verify-full","verify-code","verify-window","verify-daily","reassess","report"))
    parser.add_argument("--code",choices=tuple(INDEXES))
    parser.add_argument("--days",type=int,default=60)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--request-delay",type=float,default=.4)
    parser.add_argument("--database",type=Path,default=DATABASE_PATH)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    if args.mode=="audit":
        result=audit(args.database,args.output)
    elif args.mode=="calendar":
        capture_mainland_calendar()
        result=report(args.database,args.output)
    elif args.mode=="report":
        result=report(args.database,args.output)
    elif args.mode=="reassess":
        reassess_saved(args.database)
        result=report(args.database,args.output)
    else:
        if args.mode in ("verify-code","verify-window") and not args.code:
            parser.error(f"{args.mode} requires --code")
        if args.mode=="verify-window" and not (args.start and args.end):
            parser.error("verify-window requires --start and --end")
        codes=[args.code] if args.code else list(INDEXES)
        failures=0
        if args.mode=="verify-daily":
            from datetime import timedelta
            from zoneinfo import ZoneInfo
            through=args.end or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
            for code in codes:
                with connect(args.database) as db:
                    latest=db.execute("SELECT MAX(trade_date) FROM index_prices WHERE index_code=?",(code,)).fetchone()[0]
                if latest:
                    start=(datetime.strptime(latest,"%Y%m%d")-timedelta(days=args.days)).strftime("%Y%m%d")
                    failures += verify(args.database,DATA_ROOT,[code],args.mode,start_date=start,end_date=through,resume=args.resume,request_delay=args.request_delay)
        else:
            failures += verify(args.database,DATA_ROOT,codes,args.mode,args.days if args.mode=="verify-recent" else None,
                   start_date=args.start,end_date=args.end,resume=args.resume,request_delay=args.request_delay)
        result=report(args.database,args.output)
    print(json.dumps({"mode":args.mode,"indexes":len(result["indexes"])},ensure_ascii=False))
    if args.mode.startswith("verify-") and failures:
        raise SystemExit(2)


if __name__=="__main__":
    main()
