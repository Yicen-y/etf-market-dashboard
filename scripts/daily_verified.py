"""Incremental reference checks and guarded publication for the daily job.

The verification phase is isolated by index. A failed reference request never
turns into a match and does not discard evidence from another index.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from .config import DATABASE_PATH, DATA_ROOT, INDEXES
from .index_verification import (ReferenceHTTPError, ReferenceTransportError,
                                 collect_cni_route_approvals, report, verify)
from .update_data import update_dataset
from .snapshot import read_dataset, read_manifest
from .industry_total_return_sync import sync as sync_industry_total_return


def _recent_start(database: Path, code: str, overlap_days: int) -> str | None:
    with sqlite3.connect(database) as connection:
        dates = [row[0] for row in connection.execute(
            "SELECT trade_date FROM index_prices WHERE index_code=? ORDER BY trade_date DESC LIMIT ?",
            (code, overlap_days),
        )]
    return dates[-1] if dates else None


def _history_sample(database: Path, code: str, year: int) -> tuple[str, str] | None:
    """Rotate a small old window by year; keep the daily network load bounded."""
    with sqlite3.connect(database) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM index_prices WHERE index_code=?", (code,)
        ).fetchone()[0]
        if count <= 40:
            return None
        offset = (year * 23 + sum(map(ord, code))) % (count - 20)
        dates = [row[0] for row in connection.execute(
            "SELECT trade_date FROM index_prices WHERE index_code=? ORDER BY trade_date LIMIT 20 OFFSET ?",
            (code, offset),
        )]
    return (dates[0], dates[-1]) if dates else None


def _complete_day_cutoff(now: datetime) -> str:
    """Never publish today's ETF observations before the local close buffer."""
    return (now.date() if now.hour >= 18 else now.date() - timedelta(days=1)).strftime("%Y%m%d")


def _reference_dates(database: Path) -> dict[str, str]:
    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"index_reference_batches", "index_reference_observations"} <= tables:
            return {}
        return dict(connection.execute("""SELECT b.index_code,MAX(o.trade_date)
            FROM index_reference_batches b JOIN index_reference_observations o ON o.batch_id=b.batch_id
            WHERE b.status='FETCHED' AND b.provider IN ('CSI official HTTP','CNI official HTTPS')
            AND b.raw_sha256 IS NOT NULL GROUP BY b.index_code"""))


def _daily_metrics(database: Path, data_root: Path, reference_dates: dict[str, str], through: str,
                   attempts: dict[str, dict] | None = None) -> dict:
    from .index_verification import gate_index_candidates
    mainland = [reference_dates.get(code) for code in ("480080", "480081")]
    target = mainland[0] if mainland[0] and mainland[0] == mainland[1] and mainland[0] <= through else None
    try:
        payload = read_dataset(data_root, read_manifest(data_root), "index")
        latest_rows = {}
        for row in payload.get("flatRecords", []):
            code = row.get("indexCode")
            if code in INDEXES and (code not in latest_rows or row["tradeDate"] > latest_rows[code]["tradeDate"]):
                latest_rows[code] = row
        published = {code: latest_rows.get(code, {}).get("tradeDate") for code in INDEXES}
    except (OSError, ValueError, KeyError, TypeError):
        published = {code:None for code in INDEXES}
    status = {}
    with sqlite3.connect(database) as connection:
        has_reference = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for code in INDEXES:
            needed = reference_dates.get(code) if code == "H20915" else target
            fetched = bool(needed and reference_dates.get(code, "") >= needed and
                           (attempts is None or attempts.get(code, {}).get("status") == "CHECKED"))
            published_now = bool(needed and published.get(code) and published[code] >= needed)
            failures = []
            observation = None
            if fetched and {"index_reference_batches", "index_reference_observations"} <= has_reference:
                observation = connection.execute("""SELECT o.close_value FROM index_reference_observations o
                    JOIN index_reference_batches b ON b.batch_id=o.batch_id WHERE b.index_code=?
                    AND o.trade_date=? AND b.status='FETCHED' ORDER BY b.fetched_at DESC LIMIT 1""",
                    (code,needed)).fetchone()
                if observation:
                    # A published point must itself pass the reference gate. Checking
                    # the reference against itself would overstate daily quality.
                    candidate_close = (latest_rows[code]["closeValue"] if published_now
                                       else observation[0])
                    failures = gate_index_candidates(database,[{"indexCode":code,"tradeDate":needed,
                                                                "closeValue":candidate_close}])
            gate_passed = bool(fetched and observation is not None and not failures)
            status[code] = {"expected_date":needed,"reference_date":reference_dates.get(code),
                            "published_date":published.get(code),"latest_fetched":fetched,
                            "attempt_status":attempts.get(code, {}).get("status") if attempts is not None else None,
                            "quality_gate_passed":gate_passed,"latest_published":published_now,
                            "reason": "EXPECTED_CALENDAR_UNCONFIRMED" if not needed else
                                      "REFERENCE_UNAVAILABLE" if not fetched else
                                      failures[0][2] if failures else
                                      "PUBLICATION_WITHHELD" if not published_now else None}
    expected = sum(bool(row["expected_date"]) for row in status.values())
    return {"expected_trade_date":target,"expected_index_count":expected,
            "latest_fetched_count":sum(row["latest_fetched"] for row in status.values()),
            "quality_gate_pass_count":sum(row["quality_gate_passed"] for row in status.values()),
            "published_count":sum(row["latest_published"] for row in status.values()),
            "using_previous_count":sum(bool(row["expected_date"]) and not row["latest_published"] for row in status.values()),
            "latest_missing_count":sum(bool(row["expected_date"]) and not row["latest_fetched"] for row in status.values()),
            "indexes":status}


def run_daily(*, database: Path = DATABASE_PATH, data_root: Path = DATA_ROOT,
              overlap_days: int = 7, through: str | None = None,
              sample_history: bool = False, publish: bool = True,
              verifier=verify, publisher=update_dataset) -> dict:
    if overlap_days < 1:
        raise ValueError("overlap_days must be positive")
    today = datetime.now(ZoneInfo("Asia/Shanghai"))
    through = through or _complete_day_cutoff(today)
    datetime.strptime(through, "%Y%m%d")
    statuses: dict[str, dict] = {}
    for code in INDEXES:
        start = _recent_start(database, code, overlap_days)
        if start is None:
            statuses[code] = {"status": "NO_LOCAL_HISTORY", "failed_batches": 0}
            continue
        if through < start:
            statuses[code] = {"status":"NO_WINDOW","failed_batches":0,
                              "start":start,"end":through}
            continue
        try:
            failures = verifier(database, data_root, [code], "verify-daily",
                                start_date=start, end_date=through, resume=False)
            statuses[code] = {"status": "REFERENCE_UNAVAILABLE" if failures else "CHECKED",
                              "failed_batches":failures,"start":start,"end":through}
            if code in ("480080", "480081") and not failures and verifier is verify:
                try:
                    approved = collect_cni_route_approvals(database,data_root,code,start,through)
                    statuses[code]["route_approval"] = {"status":"APPROVED" if through in approved else "NO_TARGET_MATCH",
                                                        "approved_dates":approved,"same_upstream":True}
                except Exception as error:
                    statuses[code]["route_approval"] = {"status":"UNAVAILABLE",
                                                        "error_type":type(error).__name__,"same_upstream":True}
        except Exception as error:
            statuses[code] = {"status":"REFERENCE_ERROR","failed_batches":1,
                              "error_type":type(error).__name__,"start":start,"end":through}
            if isinstance(error, (ReferenceHTTPError, ReferenceTransportError)):
                detail = error.diagnostic
                statuses[code]["diagnostic"] = {
                    key: value for key, value in detail.items()
                    if key in {"endpoint", "http_status", "body_sha256", "content_type",
                               "requested_at", "attempts", "error_type"}
                }
                if isinstance(detail.get("request_params"), dict):
                    statuses[code]["diagnostic"]["request_params"] = {
                        key: value for key, value in detail["request_params"].items()
                        if key in {"indexCode", "startDate", "endDate", "frequency"}
                    }
        if sample_history:
            window = _history_sample(database, code, today.year)
            if window:
                try:
                    failures = verifier(database, data_root, [code], "verify-window",
                                        start_date=window[0], end_date=window[1], resume=False)
                    statuses[code]["history_sample"] = {
                        "start":window[0],"end":window[1],
                        "status":"REFERENCE_UNAVAILABLE" if failures else "CHECKED"}
                except Exception as error:
                    statuses[code]["history_sample"] = {
                        "start":window[0],"end":window[1],"status":"REFERENCE_ERROR",
                        "error_type":type(error).__name__}
    report(database, data_root / "verification")
    reference_dates = _reference_dates(database)
    publication = {"status":"NOT_REQUESTED"}
    if publish:
        try:
            summary = publisher(require_reference_verification=True,end_date=through)
            # ETF feeds can lag the issuer's index close. Publish the index
            # component separately when its verified reference extends beyond
            # the common ETF date; strategy pairs retain their common date.
            before_index_refresh = _daily_metrics(database,data_root,reference_dates,through)["indexes"]
            if any(code not in ("480080", "480081") and row["reference_date"] and
                   row["reference_date"] > (row["published_date"] or "")
                   for code,row in before_index_refresh.items()):
                summary = publisher(require_reference_verification=True,index_only=True,end_date=through)
            publication = {"status":summary.get("publicationStatus", "PUBLISHED"),"snapshot_id":summary.get("snapshot_id"),
                           "latest_index_date":summary.get("indexLatestTradeDate"),
                           "provider_summary":summary.get("providerSummary",{})}
        except Exception as error:
            # The public report contains only a classification, never the
            # provider exception text (which might include a signed URL).
            publication = {"status":"WITHHELD","reason":_failure_reason(error),
                           "error_type":type(error).__name__}
    payload = {"run_date":today.date().isoformat(),"through":through,
               "overlap_trading_days":overlap_days,"sample_history":sample_history,
               "indexes":statuses,"publication":publication,
               "latest_metrics":_daily_metrics(database,data_root,reference_dates,through,statuses)}
    destination = data_root / "verification" / "daily" / f"{through}.json"
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    temporary.replace(destination)
    return payload


def _failure_reason(error: Exception) -> str:
    message = str(error)
    if "reference verification gate blocked" in message:
        return "REFERENCE_GATE_BLOCKED"
    if "calendar review blocked" in message:
        return "CALENDAR_REVIEW_REQUIRED"
    if "quarantined" in message:
        return "ETF_SOURCE_QUARANTINED"
    if "empty response" in message or "unavailable" in message.lower():
        return "SOURCE_UNAVAILABLE"
    return "FETCH_OR_VALIDATION_FAILED"


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlap-days",type=int,default=7)
    parser.add_argument("--through",help="YYYYMMDD")
    parser.add_argument("--sample-history",action="store_true")
    parser.add_argument("--verify-only",action="store_true")
    parser.add_argument("--industry-overlap-days",type=int,default=7)
    args = parser.parse_args(argv)
    result = run_daily(overlap_days=args.overlap_days,through=args.through,
                       sample_history=args.sample_history,publish=not args.verify_only)
    industry = {"status":"SKIPPED_VERIFY_ONLY"}
    if not args.verify_only:
        try:
            rows = sync_industry_total_return(end=result["through"],
                                              overlap_days=args.industry_overlap_days)
            industry = {"status":"UPDATED", "series":len(rows),
                        "added":sum(row["added"] for row in rows),
                        "revised":sum(row["revised"] for row in rows)}
        except Exception as error:
            industry = {"status":"FAILED", "error_type":type(error).__name__}
    print(json.dumps({"checked":sum(x["status"]=="CHECKED" for x in result["indexes"].values()),
                      "unavailable":sum(x["status"]!="CHECKED" for x in result["indexes"].values()),
                      "publication":result["publication"],
                      "industry_total_return":industry},ensure_ascii=False))
    if result["publication"]["status"] == "WITHHELD" or industry["status"] == "FAILED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
