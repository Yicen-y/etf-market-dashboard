from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from .config import DATA_PATH, DATABASE_PATH, INDEX_DATA_PATH, INDEXES, INDEX_INCEPTION_DATES, INDEX_START_DATE, PRODUCT_START_DATES, PRODUCTS, START_DATE, STRATEGIES
from .fetch_data import current_end_date, fetch_csi_total_return_history, fetch_exchange_trading_dates, fetch_index_history, fetch_index_history_etfirst, fetch_index_history_official, fetch_product_history, FetchResult, validate_fetch_result
from .validate_data import validate_index_records, validate_records
from .storage import activate_snapshot, commit_market_release, init_reliability_schema, market_fingerprint, read_index_records, read_records, record_observations, record_quality_issues, record_release_manifest, recover_prepared_release, publish_snapshot, save_raw_payload
from .nontrading_candidates import is_retired_nontrading_candidate
from .nikkei_anchor_sync import sync_nikkei_anchor
from .prism_metrics import PRISM_FORMULA_VERSION, calculate_prism_metrics, trim_to_analysis_ready
from .source_policy import compare_backup, load_backup_policy, trusted_primary_overlaps
from .etf_corroboration import fetch_htbr_closes, compare_closes
from .source_approvals import approved
from .providers import DataProviderManager, LegacyEtfAdapter, etf_close_request
from .snapshot import read_dataset, read_manifest


# SSE and SZSE officially closed on 2018-06-18 for the Dragon Boat Festival.
# AkShare's historical calendar endpoint has included this weekday erroneously.
VERIFIED_NON_TRADING_DATES = {"20180618", "20261007"}


def normalize_exchange_trading_dates(dates: list[str]) -> list[str]:
    return sorted({str(day) for day in dates if str(day) not in VERIFIED_NON_TRADING_DATES})


def is_index_date_valid_for_calendar(code: str, trade_date: str, exchange_dates: set[str]) -> bool:
    """H20915 keeps its native CSI observation dates; other configured series use SSE/SZSE dates."""
    return code == "H20915" or trade_date in exchange_dates


def merge_records(existing: list[dict], incoming: list[dict], *, replace_conflicts: bool = False) -> list[dict]:
    merged = {(r["tradeDate"], r["productCode"]): r for r in existing}
    for row in incoming:
        key = (row["tradeDate"], row["productCode"])
        if key in merged and merged[key] != row and not replace_conflicts:
            raise ValueError(f"conflicting observation for {key}; retained for audit and update blocked")
        merged[key] = row
    return [merged[key] for key in sorted(merged)]


def records_to_calendar(records: list[dict]) -> list[dict]:
    dates: dict[str, dict] = {}
    for row in records:
        dates.setdefault(row["tradeDate"], {})[row["productCode"]] = row["closePrice"]
    return [{"tradeDate": d, "prices": prices} for d, prices in sorted(dates.items())]


def index_records_to_calendar(records: list[dict]) -> list[dict]:
    dates: dict[str, dict] = {}
    for row in records:
        dates.setdefault(row["tradeDate"], {})[row["indexCode"]] = row["closeValue"]
    return [{"tradeDate": d, "values": values} for d, values in sorted(dates.items())]


def complete_metric_rows(rows: list[dict], left: str, right: str) -> list[dict]:
    """Exclude a trailing day that lacks either member of a strategy pair."""
    return [row for row in rows if row.get("values", {}).get(left) not in (None, 0)
            and row.get("values", {}).get(right) not in (None, 0)]


def assess_strategy_inputs(index_records: list[dict], strategy_metrics: dict,
                           strategies: list[dict] = STRATEGIES) -> dict:
    """Expose the date used by each pair and reject a later metric row."""
    codes = {strategy[key] for strategy in strategies for key in ("a", "b")}
    latest = {code:max((row["tradeDate"] for row in index_records if row["indexCode"] == code), default=None)
              for code in codes}
    result = {}
    for strategy in strategies:
        left, right = latest[strategy["a"]], latest[strategy["b"]]
        common = min(left, right) if left and right else None
        rows = strategy_metrics[strategy["id"]]
        if rows and (not common or rows[-1]["tradeDate"] > common):
            raise ValueError(f"strategy dependency calendar mismatch: {strategy['id']}")
        result[strategy["id"]] = {
            "inputDates": {strategy["a"]:left, strategy["b"]:right},
            "effectiveDate": rows[-1]["tradeDate"] if rows else None,
            "status": "CURRENT" if left and left == right else "LAGGING_INPUT",
        }
    return result


def align_index_records_to_reference_calendar(
    records: list[dict], trading_dates: list[str], *, native_calendar_codes: set[str] | None = None
) -> tuple[list[dict], list[dict]]:
    """Keep canonical mainland-index rows on the validated reference calendar.

    A provider may publish one series for the current day before the reference
    series does.  Such a row is retained in raw provenance, but must not enter
    the published snapshot or SQLite canonical table until the shared calendar
    is complete.  Native-calendar series such as H20915 are exempt.
    """
    allowed = set(trading_dates)
    native = native_calendar_codes or {"H20915"}
    kept, deferred = [], []
    for row in records:
        if row.get("indexCode") in native or row.get("tradeDate") in allowed:
            kept.append(row)
        else:
            deferred.append(row)
    return kept, deferred


def reference_trading_dates(
    rows: list[dict], exchange_dates: list[str] | None = None, reference_code: str = "480080"
) -> list[str]:
    """Return the validated exchange calendar represented by a reference index.

    480080 is cross-checked against Wind over the full stored history. If it is
    absent on any exchange-calendar date, publishing is blocked rather than
    silently treating that trading day as a holiday.
    """
    if not rows:
        raise ValueError("cannot build trading calendar from empty index data")
    row_by_date = {row["tradeDate"]: row for row in rows}
    if exchange_dates is None:
        exchange_dates = [row["tradeDate"] for row in rows]
    else:
        start = min(row_by_date)
        # The exchange calendar can already contain today's date while the
        # reference index has not published today's close yet.  Treat only
        # this trailing, not-yet-published suffix as unavailable; an interior
        # gap remains a hard data-quality error below.
        reference_dates = [
            day for day, values in row_by_date.items()
            if values.get("values", {}).get(reference_code) not in (None, 0)
        ]
        if not reference_dates:
            raise ValueError(f"reference trading calendar {reference_code} has no valid observations")
        reference_end = max(reference_dates)
        exchange_dates = [value for value in exchange_dates if start <= value <= reference_end]
    missing = [
        value for value in exchange_dates
        if row_by_date.get(value, {}).get("values", {}).get(reference_code) in (None, 0)
    ]
    if missing:
        raise ValueError(f"reference trading calendar {reference_code} is missing exchange trading dates: {missing[:3]}")
    return exchange_dates


def extend_exchange_dates_from_issuer(database: Path, exchange_dates: list[str], end_date: str) -> list[str]:
    """Extend a lagging local calendar only with archived issuer observations.

    Two distinct mainland index codes must publish the same weekday. This is
    used for dates beyond the local exchange-calendar feed's tail, never to
    fill an interior gap or to infer an H20915 trading day.
    """
    if not exchange_dates:
        return exchange_dates
    seen: dict[str, set[str]] = {}
    with sqlite3.connect(database) as connection:
        rows = connection.execute("""SELECT o.trade_date,b.index_code,b.raw_path,b.raw_sha256
            FROM index_reference_observations o JOIN index_reference_batches b ON b.batch_id=o.batch_id
            WHERE b.status='FETCHED' AND b.provider IN ('CSI official HTTP','CNI official HTTPS')
            AND b.index_code!='H20915' AND o.close_value>0 AND o.trade_date>? AND o.trade_date<=?""",
            (exchange_dates[-1], end_date))
        for day, code, raw_path, digest in rows:
            if datetime.strptime(day, "%Y%m%d").weekday() >= 5 or not raw_path or not digest:
                continue
            path = Path(raw_path)
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                seen.setdefault(day, set()).add(code)
    return sorted(set(exchange_dates) | {day for day, codes in seen.items() if len(codes) >= 2})


def index_fetch_ranges(
    records: list[dict], code: str, fallback: str, end_date: str, trading_dates: list[str]
) -> list[tuple[str, str]]:
    """Return internal missing ranges, excluding legitimate pre-inception dates.

    One following exchange day is included so CSI zero closes can be recovered
    from the next official close and absolute-change fields.
    """
    available = sorted(
        row["tradeDate"] for row in records
        if row.get("indexCode") == code
        and row.get("closeValue") not in (None, 0)
        and row["tradeDate"] >= fallback
    )
    if not available:
        return [(fallback, end_date)] if fallback <= end_date else []
    first, latest = available[0], available[-1]
    observed = set(available)
    bounded = [value for value in trading_dates if first <= value <= min(latest, end_date)]
    missing_positions = [i for i, value in enumerate(bounded) if value not in observed]
    if not missing_positions:
        return []
    ranges: list[tuple[str, str]] = []
    group_start = group_end = missing_positions[0]
    for position in missing_positions[1:]:
        if position == group_end + 1:
            group_end = position
            continue
        context_end = bounded[min(group_end + 1, len(bounded) - 1)]
        ranges.append((bounded[group_start], context_end))
        group_start = group_end = position
    context_end = bounded[min(group_end + 1, len(bounded) - 1)]
    ranges.append((bounded[group_start], context_end))
    return ranges


def merge_index_records(existing: list[dict], incoming: list[dict], *, replace_codes: set[str] | None = None) -> list[dict]:
    merged = {(r["tradeDate"], r["indexCode"]): r for r in existing}
    for row in incoming:
        key = (row["tradeDate"], row["indexCode"])
        if key in merged and merged[key] != row and row["indexCode"] not in (replace_codes or set()):
            raise ValueError(f"conflicting index observation for {key}; update blocked")
        merged[key] = row
    return [merged[key] for key in sorted(merged)]


def _result_rows(result: FetchResult | list[dict]) -> tuple[list[dict], dict]:
    if isinstance(result, FetchResult):
        return result.rows, {"provider": result.provider, "upstream": result.upstream, "raw_sha256": result.raw_sha256, "fetched_at": result.fetched_at, "request": result.request, "source_url": result.source_url, "price_basis": result.price_basis}
    return list(result), {"provider": "PROVENANCE_UNKNOWN", "upstream": "UNKNOWN", "raw_sha256": None, "fetched_at": None, "request": {}, "source_url": None}


def _raw_rows(rows: list[dict], kind: str, metadata: dict, batch_id: str) -> list[dict]:
    return [{
        "symbol": row.get("productCode") or row.get("indexCode"), "kind": kind, "trade_date": row.get("tradeDate"),
        "value_raw": str(row.get("closePrice") if "closePrice" in row else row.get("closeValue")),
        "unit_raw": "元/份" if kind == "etf" else "index_point", "provider": metadata["provider"],
        "upstream_publisher": metadata["upstream"], "provider_request_id": json.dumps(metadata["request"], ensure_ascii=False, sort_keys=True),
        "source_url": metadata["source_url"], "fetched_at": metadata["fetched_at"], "raw_sha256": metadata["raw_sha256"],
        "fetch_batch_id": batch_id, "source_version": f"{metadata.get('price_basis', 'UNKNOWN')}/v1",
    } for row in rows]


def _source_map(rows: list[dict], metadata: dict) -> dict:
    return {(row["tradeDate"], row.get("productCode") or row.get("indexCode")): metadata["provider"] for row in rows}


def next_fetch_start(records: list[dict], code: str, fallback: str, key: str) -> str:
    latest = max((row["tradeDate"] for row in records if row.get(key) == code), default=None)
    if not latest:
        return fallback
    return (datetime.strptime(latest, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")


def should_fetch_range(fetch_start: str, end_date: str) -> bool:
    """Allow a one-day request when the next missing date is today."""
    return fetch_start <= end_date


def latest_common_product_date(records: list[dict], product_codes: set[str], requested_end: str) -> str | None:
    """Return the latest date with a valid row for every configured ETF.

    The provider can publish one or two ETFs before the rest of the market.
    Index requests must therefore stop at the latest *common* ETF date rather
    than the computer's calendar date, otherwise an unpublished tail can make
    the entire release fail.
    """
    if not product_codes:
        return None
    dates_by_product = {
        code: {
            row["tradeDate"]
            for row in records
            if row.get("productCode") == code
            and row.get("tradeDate")
            and row.get("closePrice") not in (None, 0)
            and row["tradeDate"] <= requested_end
        }
        for code in product_codes
    }
    common = set.intersection(*(dates_by_product[code] for code in product_codes))
    return max(common) if common else None


def index_refresh_end_date(effective_etf_end: str, existing_indexes: list[dict],
                           requested_end: str, guarded: bool) -> str:
    """A lagging ETF feed must not roll back an already published index tail."""
    if not guarded:
        return effective_etf_end
    existing_tail = max((row["tradeDate"] for row in existing_indexes
                         if row.get("tradeDate") and row["tradeDate"] <= requested_end), default="")
    return max(effective_etf_end, existing_tail)


def is_empty_trailing_fetch(result: FetchResult | list[dict], fetch_start: str, latest_existing: str | None) -> bool:
    """Return true only when providers have not published a newer tail yet.

    Empty internal ranges remain errors because they represent historical data
    gaps.  An empty range strictly after the latest stored observation is a
    safe no-op and will be retried by the next refresh.
    """
    return (
        isinstance(result, FetchResult)
        and not result.rows
        and latest_existing is not None
        and fetch_start > latest_existing
    )


@contextmanager
def _exclusive_update(data_root: Path):
    data_root.mkdir(parents=True, exist_ok=True)
    with (data_root / ".update.lock").open("a+b") as lock:
        lock.seek(0)
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        if __import__("os").name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def update_dataset(path: Path = DATA_PATH, api_key: Optional[str] = None, end_date: Optional[str] = None, *, h00922_only: bool = False, index_only: bool = False, progress: Callable[[str], None] | None = None, require_reference_verification: bool = False) -> dict:
    with _exclusive_update(DATA_PATH.parent):
        recovery = recover_prepared_release(DATA_PATH.parent, DATABASE_PATH)
        if recovery["state"] == "BLOCKED":
            raise RuntimeError(f"pending release requires review: {recovery['reason']}")
        return _update_dataset(path, api_key, end_date, h00922_only=h00922_only, index_only=index_only, progress=progress, require_reference_verification=require_reference_verification)


def retain_unadjudicated_history(existing_indexes: list[dict], selected_indexes: list[dict]) -> list[dict]:
    """Keep existing dated facts in flat snapshot even when metrics omit them."""
    selected = {(row["tradeDate"], row["indexCode"]) for row in selected_indexes}
    retained = [row for row in existing_indexes
                if (row["tradeDate"], row["indexCode"]) not in selected]
    return sorted(selected_indexes + retained,
                  key=lambda row: (row["tradeDate"], row["indexCode"]))


def same_published_market(data_root: Path, etf_payload: dict, index_payload: dict) -> str | None:
    """Return the active version when a refresh changes no published market facts."""
    try:
        current = read_manifest(data_root)
        if current["snapshot_id"] == "legacy":
            return None
        previous = (read_dataset(data_root, current, "etf"), read_dataset(data_root, current, "index"))
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    transient = {"snapshot_id", "updatedAt", "providerSummary"}
    def durable(payload: dict) -> dict:
        result = {key: value for key, value in payload.items() if key not in transient | {"flatRecords"}}
        if "flatRecords" in payload:
            # Issuer responses may include optional name/change/volume fields
            # that are absent when the same closes are loaded from SQLite on
            # the next run. They are source metadata, not published prices.
            result["flatRecords"] = sorted(
                (row.get("indexCode") or row.get("productCode"), row.get("tradeDate"),
                 row.get("closeValue") if "indexCode" in row else row.get("closePrice"))
                for row in payload["flatRecords"])
        return result
    return current["snapshot_id"] if all(durable(old) == durable(new)
                                         for old, new in zip(previous, (etf_payload, index_payload))) else None


def legacy_h00922_recheck_dates(database: Path) -> list[str]:
    """Recheck legacy sources unless the matching issuer response is still archived."""
    with sqlite3.connect(database) as connection:
        prices = connection.execute("""SELECT trade_date,close_value,source FROM index_prices
            WHERE index_code='H00922' AND source!='AkShare' ORDER BY trade_date""").fetchall()
        has_raw = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='raw_observations'"
        ).fetchone()
        if not has_raw:
            return [day for day, _price, _source in prices]
        candidate_evidence = connection.execute("""SELECT p.trade_date,r.raw_sha256,r.fetch_batch_id
            FROM index_prices p JOIN raw_observations r
              ON r.kind='index' AND r.symbol=p.index_code AND r.trade_date=p.trade_date
             AND r.provider='CSI official HTTP' AND r.upstream_publisher='CSI'
             AND CAST(r.value_raw AS REAL)=p.close_value
            WHERE p.index_code='H00922' AND p.source='CSI official HTTP'""").fetchall()
    certified = set()
    for day, digest, batch in candidate_evidence:
        if day in certified or not re.fullmatch(r"[a-f0-9]{64}", digest or "") or not re.fullmatch(r"[a-zA-Z0-9_-]+", batch or ""):
            continue
        archive = database.parent / "raw" / "market" / batch
        if archive.is_symlink():
            continue
        for raw_file in archive.glob(f"index-H00922-*-{digest[:16]}.bin"):
            if raw_file.is_file() and not raw_file.is_symlink() and hashlib.sha256(raw_file.read_bytes()).hexdigest() == digest:
                certified.add(day)
                break
    return [day for day, _price, source in prices if source != "CSI official HTTP" or day not in certified]


def _update_dataset(path: Path = DATA_PATH, api_key: Optional[str] = None, end_date: Optional[str] = None, *, h00922_only: bool = False, index_only: bool = False, progress: Callable[[str], None] | None = None, require_reference_verification: bool = False) -> dict:
    emit = progress or (lambda _stage: None)
    emit("FETCHING")
    batch_id = uuid.uuid4().hex
    snapshot_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + batch_id[:8]
    fetch_end = end_date or current_end_date()
    existing = read_records(DATABASE_PATH)
    existing_indexes = read_index_records(DATABASE_PATH)
    unverified_h00922_dates = legacy_h00922_recheck_dates(DATABASE_PATH)
    # Historical prices without source evidence stay unlinked. Do not invent a
    # raw observation from a normalized value.
    incoming: list[dict] = []
    source_by_key: dict = {}
    raw_rows: list[dict] = []
    source_issues: list[dict] = []
    provider_summary: dict[str, int] = {}
    provider_manager = DataProviderManager([LegacyEtfAdapter(fetch_product_history, api_key)])
    for code in PRODUCTS:
        if h00922_only or index_only:
            break
        product_start = PRODUCT_START_DATES.get(code, START_DATE)
        latest_existing = max((row["tradeDate"] for row in existing if row.get("productCode") == code), default=None)
        # Re-fetch a short trailing window so upstream corrections can replace
        # previously stored observations without requiring a full history pull.
        fetch_start = (
            max(product_start, (datetime.strptime(latest_existing, "%Y%m%d") - timedelta(days=7)).strftime("%Y%m%d"))
            if latest_existing else product_start
        )
        if not should_fetch_range(fetch_start, fetch_end):
            continue
        result = provider_manager.fetch("akshare_etf_history", etf_close_request(code, fetch_start, fetch_end))
        emit("VALIDATING")
        if isinstance(result, FetchResult):
            try:
                validate_fetch_result(result, datetime.strptime(fetch_start, "%Y%m%d").date(), datetime.strptime(fetch_end, "%Y%m%d").date())
            except ValueError:
                # A provider may lag the computer date by one or more trading
                # days. An empty request strictly after the stored tail is a
                # retryable no-op; historical empty ranges remain hard errors.
                if is_empty_trailing_fetch(result, fetch_start, latest_existing):
                    continue
                raise
        rows, metadata = _result_rows(result)
        if isinstance(result, FetchResult):
            saved = save_raw_payload(DATA_PATH.parent, batch_id, f"etf-{code}", result.raw_bytes)
            if saved:
                metadata["raw_sha256"] = saved[1]
            if result.upstream != "Eastmoney":
                policy = load_backup_policy(DATA_PATH.parent, code)
                primary = trusted_primary_overlaps(DATABASE_PATH, DATA_PATH.parent, code, {row["tradeDate"] for row in rows}) if policy else {}
                issues = ["MISSING_ARCHIVED_PAYLOAD"] if not saved else compare_backup(rows, primary, policy)
                verification = None
                if saved and rows and result.upstream == "Sina":
                    try:
                        independent, independent_raw = fetch_htbr_closes(code, min(r["tradeDate"] for r in rows), max(r["tradeDate"] for r in rows))
                        independent_saved = save_raw_payload(DATA_PATH.parent, batch_id, f"htbr-etf-{code}", independent_raw)
                        if independent_saved:
                            independent_issues = compare_closes(rows, independent)
                            if not independent_issues:
                                issues = []
                                verification = {"provider": "HTBR", "raw_sha256": independent_saved[1],
                                                "matched_dates": len(rows), "price_tolerance": 0.005}
                            else:
                                issues = independent_issues
                    except (RuntimeError, ValueError, KeyError, TypeError, OSError):
                        pass  # No independent evidence; retain the original quarantine reason.
                manual_evidence = approved(DATA_PATH.parent, code, saved[1]) if saved and issues else None
                if manual_evidence:
                    issues = []
                if issues:
                    record_observations(DATABASE_PATH, _raw_rows(rows, "etf", metadata, batch_id))
                    issue_code = "UNVERIFIED_FALLBACK_SOURCE" if issues[0] == "BASIS_UNVERIFIED" else issues[0].split(":")[0]
                    record_quality_issues(DATABASE_PATH, [{"symbol": code, "kind": "etf", "trade_date": row["tradeDate"], "issue_code": issue_code, "severity": "BLOCKED", "batch_id": batch_id} for row in rows])
                    primary_error = str(metadata.get("request", {}).get("eastmoney_error", ""))
                    network_hint = "东方财富连接中断（请检查本机代理或网络）；" if "ProxyError" in primary_error or "RemoteDisconnected" in primary_error else "东方财富主源不可用；"
                    raise ValueError(f"ETF {code} fallback {result.upstream} is quarantined: {network_hint}备用数据未通过口径核验（{issues[0]}），继续使用上一版快照")
                metadata["price_basis"] = "UNADJUSTED_CLOSE"
                evidence_id = verification["raw_sha256"] if verification else manual_evidence or policy["evidence_id"]
                metadata["request"] = {**metadata["request"], "independent_verification": verification,
                                       "manual_approval_evidence_id": manual_evidence,
                                       "source_policy_sha256": policy["policy_sha256"] if policy else None,
                                       "verification_evidence_id": evidence_id}
                source_issues.append({"symbol": code, "kind": "etf", "trade_date": rows[-1]["tradeDate"],
                                      "issue_code": "MANUAL_BACKUP_APPROVAL_USED" if manual_evidence else "VERIFIED_BACKUP_USED",
                                      "severity": "WARNING", "batch_id": batch_id, "resolution_status": "resolved",
                                      "resolution_evidence_id": evidence_id})
        incoming.extend(rows)
        source_by_key.update(_source_map(rows, metadata))
        raw_rows.extend(_raw_rows(rows, "etf", metadata, batch_id))
        provider_summary[metadata["provider"]] = provider_summary.get(metadata["provider"], 0) + len(rows)
    legacy_issues = [{"symbol": row.get("productCode"), "kind": "etf", "trade_date": row.get("tradeDate"), "issue_code": "LEGACY_INVALID_OBSERVATION", "severity": "BLOCKED", "batch_id": batch_id} for row in existing if validate_records([row], set(PRODUCTS))]
    legacy_issues.extend(source_issues)
    valid_existing = [row for row in existing if not validate_records([row], set(PRODUCTS))]
    # Incoming overlap rows replace prior prices only after the configured
    # source and quality checks above have accepted them.
    records = merge_records(valid_existing, incoming, replace_conflicts=True)
    errors = validate_records(records, set(PRODUCTS))
    if errors:
        if raw_rows:
            record_observations(DATABASE_PATH, raw_rows)
        raise ValueError("; ".join(errors))

    requested_end = end_date or current_end_date()
    effective_end = latest_common_product_date(records, set(PRODUCTS), requested_end)
    if effective_end is None:
        raise ValueError("ETF没有共同的有效最新交易日，无法确定指数刷新结束日期")
    index_end = fetch_end if index_only else index_refresh_end_date(
        effective_end, existing_indexes, fetch_end, require_reference_verification)
    emit("FETCHING")
    exchange_dates = normalize_exchange_trading_dates(
        fetch_exchange_trading_dates(INDEX_START_DATE, index_end)
    )
    if not exchange_dates:
        raise ValueError("交易所交易日历为空")
    if require_reference_verification:
        exchange_dates = extend_exchange_dates_from_issuer(DATABASE_PATH, exchange_dates, index_end)
    index_incoming: list[dict] = []
    index_source_by_key: dict = {}
    index_evidence_by_key: dict = {}
    index_raw_rows: list[dict] = []
    exchange_date_set = set(exchange_dates)
    invalid_calendar_rows = [
        row for row in existing_indexes
        if row.get("tradeDate") and row.get("indexCode")
        and not is_index_date_valid_for_calendar(row["indexCode"], row["tradeDate"], exchange_date_set)
    ]
    for code in INDEXES:
        if h00922_only and code != "H00922":
            continue
        inception = INDEX_INCEPTION_DATES.get(code, INDEX_START_DATE)
        eligible_existing = [
            row for row in existing_indexes
            if row.get("indexCode") != code
            or (row["tradeDate"] >= inception and is_index_date_valid_for_calendar(code, row["tradeDate"], exchange_date_set))
        ]
        latest_existing = max(
            (row["tradeDate"] for row in eligible_existing if row.get("indexCode") == code),
            default=None,
        )
        fetch_start = next_fetch_start(eligible_existing, code, inception, "indexCode")
        fetch_ranges = index_fetch_ranges(eligible_existing, code, inception, index_end, exchange_dates)
        if code == "H00922":
            by_year: dict[str, list[str]] = {}
            for day in unverified_h00922_dates:
                if inception <= day <= index_end and day in exchange_date_set:
                    by_year.setdefault(day[:4], []).append(day)
            fetch_ranges.extend((min(days), max(days)) for days in by_year.values())
        if should_fetch_range(fetch_start, index_end):
            fetch_ranges.append((fetch_start, index_end))
        fetch_ranges = list(dict.fromkeys(fetch_ranges))
        for range_start, range_end in fetch_ranges:
            emit("FETCHING")
            expected_days = sum(range_start <= value <= range_end for value in exchange_dates)
            result = None
            if require_reference_verification:
                try:
                    result = fetch_index_history_official(code, range_start, range_end)
                    emit("VALIDATING")
                    validate_fetch_result(
                        result, datetime.strptime(range_start, "%Y%m%d").date(),
                        datetime.strptime(range_end, "%Y%m%d").date(),
                        expected_trading_days=expected_days,
                    )
                except Exception:
                    # The original provider chain remains available, but its
                    # candidate still needs issuer reference evidence at the
                    # publication gate. An unavailable issuer is never treated
                    # as proof that a vendor value matches.
                    result = None
            if result is None and code == "H00922":
                try:
                    result = fetch_csi_total_return_history(code, range_start, range_end, api_key)
                except Exception:
                    if latest_existing and range_start > latest_existing:
                        legacy_issues.append({"symbol": code, "kind": "index", "trade_date": range_start,
                                              "issue_code": "SOURCE_TRAILING_UNAVAILABLE", "severity": "WARNING",
                                              "batch_id": batch_id})
                        continue
                    raise
                emit("VALIDATING")
                if is_empty_trailing_fetch(result, range_start, latest_existing):
                    legacy_issues.append({"symbol": code, "kind": "index", "trade_date": range_start,
                                          "issue_code": "SOURCE_TRAILING_UNAVAILABLE", "severity": "WARNING",
                                          "batch_id": batch_id})
                    continue
                validate_fetch_result(
                    result, datetime.strptime(range_start, "%Y%m%d").date(),
                    datetime.strptime(range_end, "%Y%m%d").date(),
                    expected_trading_days=expected_days,
                )
            elif result is None:
                try:
                    result = fetch_index_history_etfirst(code, range_start, range_end)
                    emit("VALIDATING")
                    if isinstance(result, FetchResult):
                        validate_fetch_result(
                            result,
                            datetime.strptime(range_start, "%Y%m%d").date(),
                            datetime.strptime(range_end, "%Y%m%d").date(),
                            expected_trading_days=expected_days,
                        )
                except Exception as primary_error:
                    emit("FETCHING")
                    fallback_result = None
                    try:
                        if code.startswith("H") or code.endswith("CNY010"):
                            fallback_result = fetch_csi_total_return_history(code, range_start, range_end, api_key)
                        else:
                            fallback_result = fetch_index_history(code, range_start, range_end, api_key)
                        result = fallback_result
                        emit("VALIDATING")
                        if isinstance(fallback_result, FetchResult):
                            validate_fetch_result(
                                fallback_result,
                                datetime.strptime(range_start, "%Y%m%d").date(),
                                datetime.strptime(range_end, "%Y%m%d").date(),
                                expected_trading_days=expected_days,
                            )
                    except Exception as fallback_error:
                        if (is_empty_trailing_fetch(fallback_result, range_start, latest_existing)
                                or (latest_existing and range_start > latest_existing)):
                            legacy_issues.append({"symbol": code, "kind": "index", "trade_date": range_start,
                                                  "issue_code": "SOURCE_TRAILING_UNAVAILABLE", "severity": "WARNING",
                                                  "batch_id": batch_id})
                            continue
                        raise RuntimeError(f"ETFirst and fallback both failed for index {code}. ETFirst: {primary_error}; fallback: {fallback_error}") from fallback_error
            emit("VALIDATING")
            rows, metadata = _result_rows(result)
            saved = None
            if isinstance(result, FetchResult):
                saved = save_raw_payload(DATA_PATH.parent, batch_id, f"index-{code}-{range_start}-{range_end}", result.raw_bytes)
                if saved:
                    metadata["raw_sha256"] = saved[1]
            candidate_evidence = {"candidate_provider": metadata["provider"],
                                  "candidate_raw_path": str(saved[0]) if saved else None,
                                  "candidate_raw_sha256": saved[1] if saved else None,
                                  "candidate_price_basis": metadata.get("price_basis")}
            # Retain unfiltered provider facts in raw provenance, but exclude
            # dates outside the corrected exchange calendar from canonical data.
            index_raw_rows.extend(_raw_rows([row for row in rows if not is_retired_nontrading_candidate(
                row.get("indexCode"), row.get("tradeDate"))], "index", metadata, batch_id))
            invalid_calendar_rows.extend(
                row for row in rows
                if row.get("tradeDate") and row.get("indexCode")
                and not is_retired_nontrading_candidate(row["indexCode"], row["tradeDate"])
                and not is_index_date_valid_for_calendar(row["indexCode"], row["tradeDate"], exchange_date_set)
            )
            rows = [
                row for row in rows
                if not row.get("tradeDate") or not row.get("indexCode")
                or is_index_date_valid_for_calendar(row["indexCode"], row["tradeDate"], exchange_date_set)
            ]
            if require_reference_verification and rows:
                from .index_verification import gate_index_candidates
                old_values = {(item["tradeDate"], item["indexCode"]):item["closeValue"]
                              for item in existing_indexes if item.get("indexCode") == code}
                candidates = [{**item, **candidate_evidence} for item in rows
                              if old_values.get((item["tradeDate"], code)) != item["closeValue"]]
                rejected = gate_index_candidates(DATABASE_PATH, candidates)
                if rejected:
                    blocked = {(item_code, day) for item_code, day, _reason in rejected}
                    for item_code, day, reason in rejected:
                        legacy_issues.append({"symbol": item_code, "kind": "index", "trade_date": day,
                                              "issue_code": f"REFERENCE_GATE_{reason}", "severity": "BLOCKED",
                                              "batch_id": batch_id})
                    rows = [item for item in rows if (code, item["tradeDate"]) not in blocked]
            index_incoming.extend(rows)
            index_source_by_key.update(_source_map(rows, metadata))
            index_evidence_by_key.update({(item["tradeDate"],code): candidate_evidence for item in rows})
            provider_summary[metadata["provider"]] = provider_summary.get(metadata["provider"], 0) + len(rows)
    legacy_issues.extend({"symbol": row.get("indexCode"), "kind": "index", "trade_date": row.get("tradeDate"), "issue_code": "LEGACY_INVALID_OBSERVATION", "severity": "BLOCKED", "batch_id": batch_id} for row in existing_indexes if validate_index_records([row], set(INDEXES)))
    invalid_calendar_rows = list({
        (row.get("tradeDate"), row.get("indexCode")): row
        for row in invalid_calendar_rows
    }.values())
    legacy_issues.extend(
        {"symbol": row.get("indexCode"), "kind": "index", "trade_date": row["tradeDate"], "issue_code": "NON_TRADING_DATE_OBSERVATION", "severity": "BLOCKED", "batch_id": batch_id}
        for row in invalid_calendar_rows
    )
    valid_existing_indexes = [
        row for row in existing_indexes
        if row["tradeDate"] >= INDEX_INCEPTION_DATES.get(row.get("indexCode"), INDEX_START_DATE)
        and is_index_date_valid_for_calendar(row.get("indexCode"), row["tradeDate"], exchange_date_set)
        and not validate_index_records([row], set(INDEXES))
    ]
    index_records = merge_index_records(valid_existing_indexes, index_incoming, replace_codes={"H00922"})
    index_errors = validate_index_records(index_records, set(INDEXES))
    if index_errors:
        if raw_rows or index_raw_rows:
            record_observations(DATABASE_PATH, raw_rows + index_raw_rows)
        raise ValueError("; ".join(index_errors))
    if not index_records:
        raise ValueError("指数历史数据为空")

    updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    calendar = records_to_calendar(records)
    output = {
        "schemaVersion": 2, "snapshot_id": snapshot_id, "source": "per-record provenance", "updatedAt": updated_at,
        "latestTradeDate": calendar[-1]["tradeDate"] if calendar else None, "products": PRODUCTS,
        "records": calendar, "flatRecords": records, "providerSummary": provider_summary,
    }
    index_base_calendar = index_records_to_calendar(index_records)
    latest_index_days = {code:max((row["tradeDate"] for row in index_records if row["indexCode"] == code),default="")
                         for code in ("480080", "H00300")}
    calendar_reference = ("H00300" if require_reference_verification and
                          latest_index_days["H00300"] > latest_index_days["480080"] else "480080")
    trading_dates = reference_trading_dates(index_base_calendar, exchange_dates,
                                            reference_code=calendar_reference)
    index_records, deferred_calendar_rows = align_index_records_to_reference_calendar(index_records, trading_dates)
    legacy_issues.extend(
        {"symbol": row["indexCode"], "kind": "index", "trade_date": row["tradeDate"],
         "issue_code": "OUTSIDE_REFERENCE_CALENDAR", "severity": "BLOCKED", "batch_id": batch_id}
        for row in deferred_calendar_rows
    )
    deferred_keys = {(row["tradeDate"], row["indexCode"]) for row in deferred_calendar_rows}
    index_incoming = [
        row for row in index_incoming
        if (row["tradeDate"], row["indexCode"]) not in deferred_keys
    ]
    index_base_calendar = index_records_to_calendar(index_records)
    index_metrics_full = calculate_prism_metrics(index_base_calendar, trading_dates=trading_dates)
    index_calendar = complete_metric_rows(trim_to_analysis_ready(index_metrics_full), "480080", "480081")
    if not index_calendar:
        raise ValueError("成长100R/价值100R历史不足以完成三棱镜指标预热")
    strategy_metrics = {
        strategy["id"]: complete_metric_rows(trim_to_analysis_ready(
            calculate_prism_metrics(
                index_base_calendar,
                strategy["a"],
                strategy["b"],
                trading_dates=trading_dates,
            )
        ), strategy["a"], strategy["b"])
        for strategy in STRATEGIES
    }
    strategy_input_status = assess_strategy_inputs(index_records, strategy_metrics)
    index_output = {
        "schemaVersion": 2, "snapshot_id": snapshot_id, "source": "per-record provenance", "updatedAt": updated_at,
        "latestTradeDate": index_calendar[-1]["tradeDate"], "indexes": INDEXES, "strategies": STRATEGIES,
        "records": index_calendar, "flatRecords": index_records, "strategyMetrics": strategy_metrics,
        "strategyInputStatus": strategy_input_status,
        "metricFormulaVersion": PRISM_FORMULA_VERSION,
        "tradingCalendar": {"referenceCode": calendar_reference, "dates": trading_dates},
        "metricStartDates": {
            "growth-value": index_calendar[0]["tradeDate"],
            **{key: rows[0]["tradeDate"] if rows else None for key, rows in strategy_metrics.items()},
        },
        "providerSummary": provider_summary,
    }
    emit("VALIDATED")
    if require_reference_verification:
        from .index_verification import gate_index_candidates
        existing_values = {(row["indexCode"],row["tradeDate"]):row["closeValue"] for row in existing_indexes}
        changed = [{**row, **index_evidence_by_key.get((row["tradeDate"],row["indexCode"]),{})}
                   for row in index_incoming
                   if existing_values.get((row["indexCode"],row["tradeDate"])) != row["closeValue"]]
        failures = gate_index_candidates(DATABASE_PATH,changed)
        if failures:
            raise ValueError(f"reference verification gate blocked {len(failures)} index candidates: {failures[:5]}")
    init_reliability_schema(DATABASE_PATH)
    fingerprint = market_fingerprint(DATABASE_PATH)
    existing_etf_values = {(row["productCode"],row["tradeDate"]):row["closePrice"] for row in existing}
    existing_index_values = {(row["indexCode"],row["tradeDate"]):row["closeValue"] for row in existing_indexes}
    changed_etfs = [row for row in incoming if existing_etf_values.get((row["productCode"],row["tradeDate"])) != row["closePrice"]]
    changed_indexes = [row for row in index_incoming if existing_index_values.get((row["indexCode"],row["tradeDate"])) != row["closeValue"]]
    expected_keys = {("etf", row["productCode"], row["tradeDate"]) for row in changed_etfs}
    expected_keys.update(("index", row["indexCode"], row["tradeDate"]) for row in changed_indexes)
    delete_keys = list({
        (row["tradeDate"], row["indexCode"])
        for row in invalid_calendar_rows + deferred_calendar_rows
    })
    if require_reference_verification:
        # Historical calendar findings remain in canonical storage and the
        # flat snapshot until individually adjudicated. Strategy calculations
        # above still use the validated reference calendar.
        index_output["flatRecords"] = retain_unadjudicated_history(existing_indexes, index_records)
        delete_keys = []
    current_snapshot = same_published_market(DATA_PATH.parent, output, index_output)
    if current_snapshot and not delete_keys:
        # The successful re-fetch is still archived under raw/market. Do not
        # rewrite prices, canonical links, or the release pointer for the same
        # published facts. Source outages remain visible in the job result.
        try:
            nikkei_sync = sync_nikkei_anchor()
        except Exception as exc:
            nikkei_sync = {"status": "ERROR", "message": str(exc), "error_type": type(exc).__name__}
        return {"etfCount": len(PRODUCTS), "indexCount": len(INDEXES),
                "strategyCount": len(STRATEGIES) + 2,
                "etfLatestTradeDate": output["latestTradeDate"],
                "indexLatestTradeDate": index_output["latestTradeDate"],
                "requestedEndDate": requested_end, "effectiveEndDate": effective_end,
                "nikkeiAnchor": nikkei_sync, "updatedAt": updated_at,
                "snapshot_id": current_snapshot, "providerSummary": provider_summary,
                "publicationStatus": "UNCHANGED",
                "sourceIssues": [{"symbol": issue["symbol"], "kind": issue["kind"],
                                  "trade_date": issue["trade_date"], "issue_code": issue["issue_code"]}
                                 for issue in legacy_issues if issue["issue_code"] == "SOURCE_TRAILING_UNAVAILABLE"]}
    emit("STAGING")
    manifest = publish_snapshot(DATA_PATH.parent, snapshot_id, output, index_output, activate=False,
                                fetch_batch_id=batch_id, prepublish_fingerprint=fingerprint,
                                expected_raw_count=len(raw_rows) + len(index_raw_rows),
                                expected_canonical_count=len(expected_keys))
    release_record = {**manifest, "provider_summary": provider_summary, "formula_version": PRISM_FORMULA_VERSION}
    canonical_rows = [{"symbol": row["productCode"], "kind": "etf", "trade_date": row["tradeDate"], "normalized_value": row["closePrice"], "normalized_unit": "元/份", "selection_reason": "current selected source", "fact_verified": False, "quality_status": "STRUCTURE_PASS_SOURCE_UNVERIFIED", "batch_id": batch_id} for row in changed_etfs]
    canonical_rows += [{"symbol": row["indexCode"], "kind": "index", "trade_date": row["tradeDate"], "normalized_value": row["closeValue"], "normalized_unit": "index_point", "selection_reason": "validated current release", "fact_verified": False, "quality_status": "STRUCTURE_PASS_SOURCE_UNVERIFIED", "batch_id": batch_id} for row in changed_indexes]
    commit_market_release(DATABASE_PATH, raw_rows=raw_rows + index_raw_rows, quality_rows=legacy_issues,
                          etf_rows=incoming, index_rows=index_incoming, updated_at=updated_at,
                          etf_sources=source_by_key, index_sources=index_source_by_key,
                          delete_index_keys=delete_keys, canonical_rows=canonical_rows,
                          canonical_delete_keys=[] if require_reference_verification else
                              [(row["indexCode"], row["tradeDate"]) for row in invalid_calendar_rows],
                          manifest=release_record)
    emit("PREPARED")
    activate_snapshot(DATA_PATH.parent, manifest)
    record_release_manifest(DATABASE_PATH, release_record)
    issue_resolution = None
    if require_reference_verification:
        try:
            from .resolve_index_issues import resolve
            issue_resolution = resolve(DATABASE_PATH, DATA_PATH.parent, apply=True)
        except (OSError, ValueError, sqlite3.Error) as error:
            # The market release is already active; issue housekeeping must
            # never turn a successful publication into a false failure.
            issue_resolution = {"status": "ERROR", "error_type": type(error).__name__}
    emit("PUBLISHED")
    try:
        nikkei_sync = sync_nikkei_anchor()
    except Exception as exc:
        # The temporary overseas series must not block publication of the
        # project's existing ETF and CSI index snapshot.
        nikkei_sync = {"status": "ERROR", "message": str(exc),
                       "error_type": type(exc).__name__}
    return {"etfCount": len(PRODUCTS), "indexCount": len(INDEXES), "strategyCount": len(STRATEGIES) + 2,
            "etfLatestTradeDate": output["latestTradeDate"], "indexLatestTradeDate": index_output["latestTradeDate"],
            "requestedEndDate": requested_end, "effectiveEndDate": effective_end,
            "nikkeiAnchor": nikkei_sync,
            "updatedAt": updated_at, "snapshot_id": manifest["snapshot_id"], "providerSummary": provider_summary,
            "publicationStatus": "PUBLISHED", "qualityIssueResolution": issue_resolution}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--h00922-only", action="store_true", help="Backfill H00922 from AkShare without refreshing other series")
    parser.add_argument("--index-only", action="store_true", help="Refresh verified index component while ETF feed lags")
    parser.add_argument("--end-date", help="Requested last date, YYYYMMDD")
    parser.add_argument("--require-reference-verification", action="store_true", help="Block new or changed index points without matching reference evidence")
    args = parser.parse_args()
    if args.index_only and not args.require_reference_verification:
        parser.error("--index-only requires --require-reference-verification")
    print(update_dataset(api_key=args.api_key, end_date=args.end_date, h00922_only=args.h00922_only,
                         index_only=args.index_only,
                         require_reference_verification=args.require_reference_verification))

