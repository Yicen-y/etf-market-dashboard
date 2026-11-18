"""Read-only, evidence-based status for the dashboard's shared datasets."""
from __future__ import annotations

import sqlite3
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .snapshot import read_dataset, read_manifest
from .jobs import recent_jobs
from .data_center_detail import build_detail
from .config import STRATEGIES


REGISTRY = (
    ("etf_prices", "ETF 日收盘", "etf_prices", "etf", ("主看板", "轮动总览")),
    ("index_prices", "指数日点位", "index_prices", "index", ("三棱镜", "五年之锚", "红利研究", "股债性价比")),
    ("fund_flow", "ETF 份额与资金流", "fund_flow_etf_daily_metrics", None, ("资金流向",)),
    ("dividends", "股票与 ETF 股息", "dividend_events", None, ("股息率", "红利研究")),
    ("bond_value", "股债估值", None, None, ("股债性价比",)),
)


def strategy_calculations(payload: dict, snapshot_id: str | None) -> list[dict]:
    """Check published metric dates against the two actual input calendars."""
    dates: dict[str, set[str]] = {}
    for row in payload.get("flatRecords", []):
        code, day = row.get("indexCode"), row.get("tradeDate")
        if code and day and row.get("closeValue") is not None:
            dates.setdefault(code, set()).add(day)
    declared = payload.get("strategyInputStatus", {})
    specs = [{"id": "prism", "name": "三棱镜轮动", "a": "480080", "b": "480081"}, *STRATEGIES]
    result = []
    for spec in specs:
        a, b = spec["a"], spec["b"]
        overlap = dates.get(a, set()) & dates.get(b, set())
        common = max(overlap, default=None)
        metric_rows = (payload.get("records", []) if spec["id"] == "prism" else
                       payload.get("strategyMetrics", {}).get(spec["id"], []))
        metric_days = [row.get("tradeDate") for row in metric_rows]
        metric_latest = max((day for day in metric_days if day), default=None)
        out_of_calendar = sum(day not in overlap for day in metric_days)
        claimed = declared.get(spec["id"], {}) if spec["id"] != "prism" else {}
        claim_conflict = bool(claimed and (claimed.get("effectiveDate") != common or
                              claimed.get("inputDates") != {a: max(dates.get(a, set()), default=None),
                                                             b: max(dates.get(b, set()), default=None)}))
        status = ("NO_COMMON_DATE" if not common else
                  "INPUT_DATE_CONFLICT" if out_of_calendar or metric_latest and metric_latest > common or claim_conflict else
                  "METRIC_LAG" if metric_latest != common else "MATCH")
        result.append({"id": spec["id"], "name": spec["name"], "inputs": [a, b],
                       "input_dates": {a: max(dates.get(a, set()), default=None),
                                       b: max(dates.get(b, set()), default=None)},
                       "common_date": common, "calculation_date": metric_latest,
                       "out_of_calendar_rows": out_of_calendar, "status": status,
                       "snapshot_id": snapshot_id})
    return result


def _expected_mainland_date(data_root: Path) -> str | None:
    """Use an explicit local exchange calendar; never infer holidays from weekdays."""
    path = data_root / "market_calendar.json"
    try:
        calendar = json.loads(path.read_text(encoding="utf-8"))
        dates = calendar["dates"]
        if not isinstance(dates, list) or dates != sorted(set(dates)):
            return None
        if any(not isinstance(day, str) or len(day) != 8 or datetime.strptime(day, "%Y%m%d").strftime("%Y%m%d") != day for day in dates):
            return None
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        cutoff = (now.date() if now.hour >= 18 else now.date() - timedelta(days=1)).strftime("%Y%m%d")
        if calendar.get("covered_through", "") < cutoff:
            return None
        valid = [day for day in dates if day <= cutoff]
        return valid[-1] if valid else None
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def _official_mainland_reference_date(database: Path) -> str | None:
    """Fallback market day from archived mainland issuer observations."""
    try:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        cutoff = (now.date() if now.hour >= 18 else now.date() - timedelta(days=1)).strftime("%Y%m%d")
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            csi = connection.execute("""SELECT o.trade_date FROM index_reference_observations o
                JOIN index_reference_batches b ON b.batch_id=o.batch_id
                WHERE b.provider='CSI official HTTP' AND b.index_code<>'H20915'
                AND b.status='FETCHED' AND b.raw_sha256 IS NOT NULL AND b.raw_path IS NOT NULL
                AND o.trade_date<=? GROUP BY o.trade_date
                HAVING COUNT(DISTINCT b.index_code)>=3 ORDER BY o.trade_date DESC LIMIT 1""", (cutoff,)).fetchone()
            dates = dict(connection.execute("""SELECT b.index_code,MAX(o.trade_date)
                FROM index_reference_observations o JOIN index_reference_batches b
                ON b.batch_id=o.batch_id WHERE b.index_code IN ('480080','480081')
                AND b.provider='CNI official HTTPS' AND b.status='FETCHED'
                AND b.raw_sha256 IS NOT NULL AND b.raw_path IS NOT NULL
                GROUP BY b.index_code"""))
        day = dates.get("480080")
        cni_day = day if day and day == dates.get("480081") and day <= cutoff else None
        return max((candidate for candidate in (csi[0] if csi else None, cni_day) if candidate), default=None)
    except (OSError, sqlite3.Error):
        return None


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _summary(connection, tables, table):
    if table is None or table not in tables:
        return {"rows": None, "latest_trade_date": None}
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    day = next((name for name in ("trade_date", "record_date", "ex_date") if name in columns), None)
    count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    latest = connection.execute(f"SELECT MAX({day}) FROM {table}").fetchone()[0] if day else None
    return {"rows": count, "latest_trade_date": latest}


def _snapshot_matches_market(data_root: Path, database: Path, manifest: dict | None) -> bool:
    """Compare published price facts, ignoring collection timestamps."""
    if not manifest:
        return False
    try:
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            for kind, table, code_column, value_column, payload_code, payload_value in (
                ("etf", "etf_prices", "product_code", "close_price", "productCode", "closePrice"),
                ("index", "index_prices", "index_code", "close_value", "indexCode", "closeValue"),
            ):
                rows = read_dataset(data_root, manifest, kind).get("flatRecords", [])
                published = {(row["tradeDate"], row[payload_code]): row[payload_value] for row in rows}
                if len(published) != len(rows):
                    return False
                stored = {(day, code): value for day, code, value in connection.execute(
                    f"SELECT trade_date,{code_column},{value_column} FROM {table}")}
                if published != stored:
                    return False
        return True
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False


def _recent_issues(connection, tables):
    if "quality_issues" not in tables:
        return []
    return [dict(zip(("issue_id", "symbol", "kind", "trade_date", "issue_code", "severity", "batch_id", "raw_sha256", "candidate_price"), row))
            for row in connection.execute("""SELECT q.issue_id,q.symbol,q.kind,q.trade_date,q.issue_code,q.severity,q.batch_id,
                (SELECT r.raw_sha256 FROM raw_observations r WHERE r.symbol=q.symbol AND r.kind=q.kind
                 AND r.trade_date=q.trade_date AND r.fetch_batch_id=q.batch_id ORDER BY r.raw_record_id DESC LIMIT 1),
                (SELECT r.value_raw FROM raw_observations r WHERE r.symbol=q.symbol AND r.kind=q.kind
                 AND r.trade_date=q.trade_date AND r.fetch_batch_id=q.batch_id ORDER BY r.raw_record_id DESC LIMIT 1)
                FROM quality_issues q WHERE q.resolution_status='open'
                AND q.issue_id=(SELECT MAX(newer.issue_id) FROM quality_issues newer
                    WHERE newer.symbol=q.symbol AND newer.kind=q.kind AND newer.trade_date=q.trade_date
                    AND newer.issue_code=q.issue_code AND newer.resolution_status='open')
                AND NOT (q.severity='BLOCKED' AND EXISTS (
                    SELECT 1 FROM canonical_observations c JOIN raw_observations selected
                    ON selected.raw_record_id=c.selected_raw_id
                    WHERE c.symbol=q.symbol AND c.kind=q.kind AND c.trade_date=q.trade_date
                    AND selected.fetch_batch_id<>q.batch_id))
                ORDER BY q.issue_id DESC LIMIT 30""")]


def build_data_center(data_root: Path, database: Path) -> dict:
    """No writes and no inferred external verification."""
    try:
        manifest = read_manifest(data_root)
        snapshot_id = manifest["snapshot_id"]
    except (OSError, ValueError, KeyError, TypeError):
        manifest, snapshot_id = None, None
    database_error = None
    try:
        if not database.exists():
            raise FileNotFoundError("database unavailable")
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            tables = _tables(connection)
            summaries = {item[0]: _summary(connection, tables, item[2]) for item in REGISTRY}
            issues = _recent_issues(connection, tables)
            last_fetch = connection.execute("SELECT MAX(fetched_at) FROM raw_observations").fetchone()[0] if "raw_observations" in tables else None
            pending = connection.execute("SELECT COUNT(*) FROM release_manifest WHERE status='prepared'").fetchone()[0] if "release_manifest" in tables else 0
    except (OSError, sqlite3.Error) as error:
        database_error = type(error).__name__
        summaries = {item[0]: {"rows": None, "latest_trade_date": None} for item in REGISTRY}
        issues, last_fetch, pending = [], None, 0
    try:
        jobs = recent_jobs(data_root)
    except sqlite3.Error:
        jobs = []
    expected_mainland = _expected_mainland_date(data_root) or _official_mainland_reference_date(database)
    datasets = []
    strategy_dates = []
    for dataset_id, title, _, snapshot_key, affected in REGISTRY:
        item = {"id": dataset_id, "name": title, **summaries[dataset_id], "affected_dashboards": list(affected),
                "fetch_status": "UNKNOWN", "validation_status": "UNKNOWN", "publication_status": "UNKNOWN",
                "source_verification": "UNKNOWN", "snapshot_id": None, "error": None,
                "expected_trade_date": expected_mainland if dataset_id in {"etf_prices", "index_prices"} else None,
                "freshness_status": "UNKNOWN", "using_previous_release": False}
        if snapshot_key and manifest:
            try:
                payload = read_dataset(data_root, manifest, snapshot_key)
                published_latest = max((row.get("tradeDate") for row in payload.get("flatRecords", [])
                                        if row.get("tradeDate")), default=None)
                item.update(latest_trade_date=published_latest or payload.get("latestTradeDate"),
                            metric_latest_trade_date=payload.get("latestTradeDate"), snapshot_id=snapshot_id,
                            publication_status="PUBLISHED", validation_status="STRUCTURE_PASS")
                if dataset_id == "index_prices":
                    strategy_dates = strategy_calculations(payload, snapshot_id)
                    watched = {"H00821": "沪深300红利全收益", "H00918": "沪深300成长全收益", "H00300": "沪深300全收益"}
                    item["watched_series"] = {name: max((row["tradeDate"] for row in payload.get("flatRecords", [])
                                                          if row.get("indexCode") == code), default=None)
                                              for code, name in watched.items()}
            except (OSError, ValueError, KeyError, TypeError) as error:
                item.update(publication_status="FAILED", validation_status="FAILED", error=str(error))
        elif snapshot_key:
            item.update(publication_status="FAILED", error="current manifest unavailable")
        elif item["rows"]:
            item["publication_status"] = "LOCAL_DB"
        if dataset_id == "bond_value":
            path = data_root / "research" / "bond_value_hs300.json"
            item["publication_status"] = "LOCAL_FILE" if path.exists() else "UNKNOWN"
        relevant = [issue for issue in issues if issue["kind"] == snapshot_key] if snapshot_key else []
        item["open_issue_count"] = len(relevant)
        if relevant:
            excluded = {"NON_TRADING_DATE_OBSERVATION", "OUTSIDE_REFERENCE_CALENDAR", "NON_POSITIVE_INDEX_VALUE", "LEGACY_INVALID_OBSERVATION"}
            if any(i["severity"] == "BLOCKED" and i["issue_code"] not in excluded for i in relevant):
                item["fetch_status"] = "CANDIDATE_BLOCKED"
            elif any(i["issue_code"] == "SOURCE_TRAILING_UNAVAILABLE" for i in relevant):
                item["fetch_status"] = "PARTIAL_SOURCE_LAG"
            else:
                item["fetch_status"] = "CHECKED_EXCLUDED"
            if any(i["issue_code"] == "SOURCE_TRAILING_UNAVAILABLE" for i in relevant):
                item["source_verification"] = "部分指数最新日期暂未返回；对应序列等待重试"
        elif dataset_id == "etf_prices" and item["publication_status"] == "PUBLISHED":
            item["source_verification"] = "已发布；具体来源见逐条记录"
        if item["publication_status"] == "PUBLISHED":
            latest = item["latest_trade_date"]
            expected = item["expected_trade_date"]
            if expected and latest:
                item["freshness_status"] = "STALE" if latest < expected else "CURRENT"
                item["using_previous_release"] = latest < expected
        datasets.append(item)
    try:
        detail = build_detail(data_root,database,snapshot_id,expected_mainland)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
        detail = {"series":[],"series_summary":{"total":0,"normal":0,"stale":0,"anomaly":0},
                  "versions":[],"provider_diagnostics":[],"index_anomalies":[]}
    current_release = next((row for row in detail["versions"] if row["snapshot_id"] == snapshot_id),None)
    daily_files = sorted((data_root / "verification" / "daily").glob("????????.json"))
    try:
        last_daily = json.loads(daily_files[-1].read_text(encoding="utf-8")) if daily_files else None
    except (OSError, ValueError, TypeError):
        last_daily = None
    if isinstance(last_daily, dict):
        checks = last_daily.get("indexes") or {}
        for row in detail["series"]:
            if row.get("type") != "index":
                continue
            attempt = checks.get(row.get("code"))
            if not isinstance(attempt, dict) or attempt.get("status") != "REFERENCE_ERROR":
                continue
            diagnostic = attempt.get("diagnostic") or {}
            failure_time = diagnostic.get("requested_at")
            success_time = max((value for value in (row.get("last_collected_at"),
                                                    row.get("last_reference_at")) if value), default=None)
            try:
                if failure_time and success_time and datetime.fromisoformat(success_time) > datetime.fromisoformat(failure_time):
                    continue  # A later successful check supersedes this daily failure.
            except (ValueError, TypeError):
                pass
            row.update(fetch_status="FAILED", acquisition_status="FAILED",
                       operational_status="FETCH_FAILED",
                       fetch_error={"error_type": attempt.get("error_type", "ReferenceError"),
                                    "run_date": last_daily.get("run_date"), **diagnostic})
        summary = detail["series_summary"]
        states = Counter(row["operational_status"] for row in detail["series"])
        summary.update(normal=states["NORMAL"], stale=states["STALE"],
                       fetch_failed=states["FETCH_FAILED"], anomaly=states["ANOMALY"],
                       unknown=states["UNKNOWN"])
        summary["dimensions"]["acquisition_status"] = dict(
            Counter(row.get("acquisition_status", "UNKNOWN") for row in detail["series"]))
    return {"schema_version": 2, "generated_at": datetime.now().astimezone().isoformat(),
            "database_error": database_error,
            "current_snapshot_id": snapshot_id, "last_fetch_at": last_fetch, "prepared_releases": pending,
            "storage_bytes": {"database": database.stat().st_size if database.exists() else None,
                              "releases": sum(p.stat().st_size for p in (data_root / "releases").rglob("*") if p.is_file()),
                              "backups": sum(p.stat().st_size for p in (data_root / "backups").rglob("*") if p.is_file())},
            "datasets": datasets, "recent_issues": issues, "recent_jobs": jobs,
            "series":detail["series"],"series_summary":detail["series_summary"],
            "strategy_calculations":strategy_dates,
            "versions":detail["versions"],"provider_diagnostics":detail["provider_diagnostics"],
            "index_anomalies":detail["index_anomalies"],
            "last_daily_verification":last_daily,
            "last_update_result":jobs[0] if jobs else None,
            "last_successful_publication_at":next((row["published_at"] for row in detail["versions"]
                                                   if row["status"] == "published"),None),
            "snapshot_database_consistency":"UNKNOWN" if snapshot_id == "legacy" else
                "MATCH" if current_release and current_release["status"] == "published"
                and _snapshot_matches_market(data_root, database, manifest) else "MISMATCH",
            "summary": {"total": len(datasets), "published": sum(d["publication_status"] == "PUBLISHED" for d in datasets),
                        "failed": sum(d["publication_status"] == "FAILED" for d in datasets),
                        "unknown": sum(d["publication_status"] == "UNKNOWN" for d in datasets)}}
