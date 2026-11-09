from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import DATA_PATH, DATABASE_PATH, INDEX_DATA_PATH, INDEXES, INDEX_INCEPTION_DATES, INDEX_START_DATE, PRODUCT_START_DATES, PRODUCTS, START_DATE, STRATEGIES
from .fetch_data import current_end_date, fetch_csi_total_return_history, fetch_exchange_trading_dates, fetch_index_history, fetch_index_history_etfirst, fetch_product_history, FetchResult, validate_fetch_result
from .validate_data import validate_index_records, validate_records
from .storage import delete_canonical_index_observations, read_index_records, read_records, record_canonical_observations, record_legacy_observations, record_observations, record_quality_issues, record_release_manifest, publish_snapshot, save_raw_payload, upsert_market_records_atomic
from .nikkei_anchor_sync import sync_nikkei_anchor
from .prism_metrics import PRISM_FORMULA_VERSION, calculate_prism_metrics, trim_to_analysis_ready


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
        return result.rows, {"provider": result.provider, "upstream": result.upstream, "raw_sha256": result.raw_sha256, "fetched_at": result.fetched_at, "request": result.request, "source_url": result.source_url}
    return list(result), {"provider": "PROVENANCE_UNKNOWN", "upstream": "UNKNOWN", "raw_sha256": None, "fetched_at": None, "request": {}, "source_url": None}


def _raw_rows(rows: list[dict], kind: str, metadata: dict, batch_id: str) -> list[dict]:
    return [{
        "symbol": row.get("productCode") or row.get("indexCode"), "kind": kind, "trade_date": row.get("tradeDate"),
        "value_raw": str(row.get("closePrice") if "closePrice" in row else row.get("closeValue")),
        "unit_raw": "元/份" if kind == "etf" else "index_point", "provider": metadata["provider"],
        "upstream_publisher": metadata["upstream"], "provider_request_id": json.dumps(metadata["request"], ensure_ascii=False, sort_keys=True),
        "source_url": metadata["source_url"], "fetched_at": metadata["fetched_at"], "raw_sha256": metadata["raw_sha256"],
        "fetch_batch_id": batch_id, "source_version": "v1",
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


def update_dataset(path: Path = DATA_PATH, api_key: Optional[str] = None, end_date: Optional[str] = None, *, h00922_only: bool = False) -> dict:
    batch_id = uuid.uuid4().hex
    snapshot_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + batch_id[:8]
    fetch_end = end_date or current_end_date()
    existing = read_records(DATABASE_PATH)
    existing_indexes = read_index_records(DATABASE_PATH)
    with sqlite3.connect(DATABASE_PATH) as connection:
        unverified_h00922_dates = [day for (day,) in connection.execute(
            "SELECT trade_date FROM index_prices WHERE index_code='H00922' AND source!='AkShare' ORDER BY trade_date"
        )]
    record_legacy_observations(DATABASE_PATH, existing, existing_indexes)
    incoming: list[dict] = []
    source_by_key: dict = {}
    raw_rows: list[dict] = []
    provider_summary: dict[str, int] = {}
    for code in PRODUCTS:
        if h00922_only:
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
        result = fetch_product_history(code, fetch_start, fetch_end, api_key)
        if isinstance(result, FetchResult):
            validate_fetch_result(result, datetime.strptime(fetch_start, "%Y%m%d").date(), datetime.strptime(fetch_end, "%Y%m%d").date())
        rows, metadata = _result_rows(result)
        if isinstance(result, FetchResult):
            saved = save_raw_payload(DATA_PATH.parent, batch_id, f"etf-{code}", result.raw_bytes)
            if saved:
                metadata["raw_sha256"] = saved[1]
        incoming.extend(rows)
        source_by_key.update(_source_map(rows, metadata))
        raw_rows.extend(_raw_rows(rows, "etf", metadata, batch_id))
        provider_summary[metadata["provider"]] = provider_summary.get(metadata["provider"], 0) + len(rows)
    legacy_issues = [{"symbol": row.get("productCode"), "kind": "etf", "trade_date": row.get("tradeDate"), "issue_code": "LEGACY_INVALID_OBSERVATION", "severity": "BLOCKED", "batch_id": batch_id} for row in existing if validate_records([row], set(PRODUCTS))]
    valid_existing = [row for row in existing if not validate_records([row], set(PRODUCTS))]
    # ETF closes are sourced exclusively from AkShare; incoming overlap rows
    # are authoritative corrections to older values from other providers.
    records = merge_records(valid_existing, incoming, replace_conflicts=True)
    errors = validate_records(records, set(PRODUCTS))
    if errors:
        if raw_rows:
            record_observations(DATABASE_PATH, raw_rows)
        raise ValueError("; ".join(errors))

    index_end = end_date or current_end_date()
    exchange_dates = normalize_exchange_trading_dates(
        fetch_exchange_trading_dates(INDEX_START_DATE, index_end)
    )
    if not exchange_dates:
        raise ValueError("交易所交易日历为空")
    index_incoming: list[dict] = []
    index_source_by_key: dict = {}
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
            expected_days = sum(range_start <= value <= range_end for value in exchange_dates)
            if code == "H00922":
                result = fetch_csi_total_return_history(code, range_start, range_end, api_key)
                validate_fetch_result(
                    result, datetime.strptime(range_start, "%Y%m%d").date(),
                    datetime.strptime(range_end, "%Y%m%d").date(),
                    expected_trading_days=expected_days,
                )
            else:
                try:
                    result = fetch_index_history_etfirst(code, range_start, range_end)
                    if isinstance(result, FetchResult):
                        validate_fetch_result(
                            result,
                            datetime.strptime(range_start, "%Y%m%d").date(),
                            datetime.strptime(range_end, "%Y%m%d").date(),
                            expected_trading_days=expected_days,
                        )
                except Exception as primary_error:
                    fallback_result = None
                    try:
                        if code.startswith("H") or code.endswith("CNY010"):
                            fallback_result = fetch_csi_total_return_history(code, range_start, range_end, api_key)
                        else:
                            fallback_result = fetch_index_history(code, range_start, range_end, api_key)
                        result = fallback_result
                        if isinstance(fallback_result, FetchResult):
                            validate_fetch_result(
                                fallback_result,
                                datetime.strptime(range_start, "%Y%m%d").date(),
                                datetime.strptime(range_end, "%Y%m%d").date(),
                                expected_trading_days=expected_days,
                            )
                    except Exception as fallback_error:
                        if is_empty_trailing_fetch(fallback_result, range_start, latest_existing):
                            continue
                        raise RuntimeError(f"ETFirst and fallback both failed for index {code}. ETFirst: {primary_error}; fallback: {fallback_error}") from fallback_error
            rows, metadata = _result_rows(result)
            if isinstance(result, FetchResult):
                saved = save_raw_payload(DATA_PATH.parent, batch_id, f"index-{code}-{range_start}-{range_end}", result.raw_bytes)
                if saved:
                    metadata["raw_sha256"] = saved[1]
            # Retain unfiltered provider facts in raw provenance, but exclude
            # dates outside the corrected exchange calendar from canonical data.
            index_raw_rows.extend(_raw_rows(rows, "index", metadata, batch_id))
            invalid_calendar_rows.extend(
                row for row in rows
                if row.get("tradeDate") and row.get("indexCode")
                and not is_index_date_valid_for_calendar(row["indexCode"], row["tradeDate"], exchange_date_set)
            )
            rows = [
                row for row in rows
                if not row.get("tradeDate") or not row.get("indexCode")
                or is_index_date_valid_for_calendar(row["indexCode"], row["tradeDate"], exchange_date_set)
            ]
            index_incoming.extend(rows)
            index_source_by_key.update(_source_map(rows, metadata))
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
    trading_dates = reference_trading_dates(index_base_calendar, exchange_dates)
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
    index_calendar = trim_to_analysis_ready(index_metrics_full)
    if not index_calendar:
        raise ValueError("成长100R/价值100R历史不足以完成三棱镜指标预热")
    strategy_metrics = {
        strategy["id"]: trim_to_analysis_ready(
            calculate_prism_metrics(
                index_base_calendar,
                strategy["a"],
                strategy["b"],
                trading_dates=trading_dates,
            )
        )
        for strategy in STRATEGIES
    }
    index_output = {
        "schemaVersion": 2, "snapshot_id": snapshot_id, "source": "per-record provenance", "updatedAt": updated_at,
        "latestTradeDate": index_calendar[-1]["tradeDate"], "indexes": INDEXES, "strategies": STRATEGIES,
        "records": index_calendar, "flatRecords": index_records, "strategyMetrics": strategy_metrics,
        "metricFormulaVersion": PRISM_FORMULA_VERSION,
        "tradingCalendar": {"referenceCode": "480080", "dates": trading_dates},
        "metricStartDates": {
            "growth-value": index_calendar[0]["tradeDate"],
            **{key: rows[0]["tradeDate"] if rows else None for key, rows in strategy_metrics.items()},
        },
        "providerSummary": provider_summary,
    }
    record_observations(DATABASE_PATH, raw_rows + index_raw_rows)
    record_quality_issues(DATABASE_PATH, legacy_issues)
    # Both market tables are committed only after both streams have passed validation.
    delete_keys = list({
        (row["tradeDate"], row["indexCode"])
        for row in invalid_calendar_rows + deferred_calendar_rows
    })
    upsert_market_records_atomic(
        DATABASE_PATH, incoming, index_incoming, updated_at, source_by_key,
        index_source_by_key,
        delete_index_keys=delete_keys,
    )
    manifest = publish_snapshot(DATA_PATH.parent, snapshot_id, output, index_output)
    record_canonical_observations(DATABASE_PATH, [{"symbol": row["productCode"], "kind": "etf", "trade_date": row["tradeDate"], "normalized_value": row["closePrice"], "normalized_unit": "元/份", "selection_reason": "validated current release", "fact_verified": False, "quality_status": "PASS", "batch_id": batch_id} for row in records] + [{"symbol": row["indexCode"], "kind": "index", "trade_date": row["tradeDate"], "normalized_value": row["closeValue"], "normalized_unit": "index_point", "selection_reason": "validated current release", "fact_verified": False, "quality_status": "PASS", "batch_id": batch_id} for row in index_records])
    delete_canonical_index_observations(
        DATABASE_PATH, [(row["indexCode"], row["tradeDate"]) for row in invalid_calendar_rows]
    )
    record_release_manifest(DATABASE_PATH, {**manifest, "provider_summary": provider_summary, "formula_version": PRISM_FORMULA_VERSION})
    try:
        nikkei_sync = sync_nikkei_anchor()
    except Exception as exc:
        # The temporary overseas series must not block publication of the
        # project's existing ETF and CSI index snapshot.
        nikkei_sync = {"status": "ERROR", "message": str(exc)}
    return {"etfCount": len(PRODUCTS), "indexCount": len(INDEXES), "strategyCount": len(STRATEGIES) + 2,
            "etfLatestTradeDate": output["latestTradeDate"], "indexLatestTradeDate": index_output["latestTradeDate"],
            "nikkeiAnchor": nikkei_sync,
            "updatedAt": updated_at, "snapshot_id": manifest["snapshot_id"], "providerSummary": provider_summary}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--h00922-only", action="store_true", help="Backfill H00922 from AkShare without refreshing other series")
    args = parser.parse_args()
    print(update_dataset(api_key=args.api_key, h00922_only=args.h00922_only))

