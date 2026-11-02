from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from contextlib import closing
from pathlib import Path
import json
from typing import Iterable

from ..config import DATABASE_PATH, ETF_UNIVERSE
from ..db import init_fund_flow_schema, open_fund_flow_connection, seed_default_fund_master
from ..models import RawETFRecord, RawNAVRecord
from ..providers.base import NavProvider, ProviderUnavailable, ShareProvider, now_iso
from .persistence import rebuild_materialized


@dataclass
class SyncReport:
    inserted: int = 0
    updated: int = 0
    latest_trade_date: date | None = None
    provider_status: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: list[dict] = field(default_factory=list)


def calculate_flow_yi(current: RawETFRecord, previous: RawETFRecord | None) -> float | None:
    if previous is None or current.total_share is None or previous.total_share is None or current.nav is None:
        return None
    return (current.total_share - previous.total_share) * current.nav / 10000


def _source_row(connection, source_id: str, provider, row_count: int, error: str | None = None):
    connection.execute(
        """INSERT INTO fund_flow_data_sources(source_id,url,retrieved_at,row_count,error_message)
           VALUES (?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
           url=excluded.url,retrieved_at=excluded.retrieved_at,row_count=excluded.row_count,
           error_message=excluded.error_message""",
        (source_id, getattr(provider, "source_url", None), now_iso(), row_count, error),
    )


def _insert_rows(connection, rows: Iterable[RawETFRecord]) -> tuple[int, int]:
    inserted = updated = 0
    for row in rows:
        values = {
            "etf_code": row.etf_code,
            "record_date": row.record_date.isoformat(),
            "effective_trade_date": row.effective_trade_date.isoformat(),
            "published_at": row.published_at,
            "total_share": row.total_share,
            "share_unit": row.share_unit,
            "share_scope": row.share_scope,
            "share_date_basis": row.share_date_basis,
            "nav": row.nav,
            "close": row.close,
            "total_size": row.total_size,
            "source_id": row.source_id,
            "source_version": row.source_version,
            "import_batch_id": row.import_batch_id,
        }
        before = connection.execute(
            """SELECT 1 FROM fund_flow_etf_daily_raw WHERE etf_code=? AND record_date=?
               AND share_scope=? AND source_id=? AND source_version=? AND import_batch_id=?""",
            tuple(values[key] for key in ("etf_code", "record_date", "share_scope", "source_id", "source_version", "import_batch_id")),
        ).fetchone()
        connection.execute(
            """INSERT OR REPLACE INTO fund_flow_etf_daily_raw
               (etf_code,record_date,effective_trade_date,published_at,total_share,share_unit,
                share_scope,share_date_basis,nav,close,total_size,source_id,source_version,import_batch_id)
               VALUES (:etf_code,:record_date,:effective_trade_date,:published_at,:total_share,:share_unit,
                :share_scope,:share_date_basis,:nav,:close,:total_size,:source_id,:source_version,:import_batch_id)""",
            values,
        )
        if before:
            updated += 1
        else:
            inserted += 1
    return inserted, updated


def _insert_nav_rows(connection, rows: Iterable[RawNAVRecord]) -> None:
    for row in rows:
        connection.execute(
            """INSERT OR REPLACE INTO fund_flow_nav_daily_raw
               (etf_code,nav_date,nav,cumulative_nav,unit,source_id,source_version)
               VALUES (?,?,?,?,?,?,?)""",
            (
                row.etf_code,
                row.nav_date.isoformat(),
                row.nav,
                row.cumulative_nav,
                row.unit,
                row.source_id,
                row.source_version,
            ),
        )


def _attach_nav(rows: list[RawETFRecord], nav_rows: list[RawNAVRecord]) -> list[RawETFRecord]:
    nav_map = {(row.etf_code, row.nav_date): row.nav for row in nav_rows}
    return [replace(row, nav=nav_map.get((row.etf_code, row.effective_trade_date), row.nav)) for row in rows]


def sync_recent(
    db_path: Path = DATABASE_PATH,
    *,
    share_providers: list[ShareProvider],
    nav_provider: NavProvider | None,
    codes: list[str] | None = None,
    start: date,
    end: date,
    retry_policy: dict | None = None,
) -> SyncReport:
    del retry_policy  # providers own their retry policy; retained for API stability
    codes = codes or list(ETF_UNIVERSE)
    init_fund_flow_schema(db_path)
    seed_default_fund_master(db_path)
    report = SyncReport()
    share_rows: list[RawETFRecord] = []
    with closing(open_fund_flow_connection(db_path)) as connection:
        with connection:
            for provider in share_providers:
                provider_name = provider.__class__.__name__
                try:
                    rows = provider.fetch(codes, start, end)
                    share_rows.extend(rows)
                    source_ids = {row.source_id for row in rows} or {f"{provider_name}:empty"}
                    for source_id in source_ids:
                        _source_row(connection, source_id, provider, sum(row.source_id == source_id for row in rows))
                    state = "success" if rows else "warning"
                    report.provider_status.append({"provider": provider_name, "status": state, "rows": len(rows)})
                    if not rows:
                        report.warnings.append(f"{provider_name}: empty response; existing data retained")
                except Exception as exc:
                    report.provider_status.append({"provider": provider_name, "status": "failed", "error": str(exc)})
                    report.warnings.append(f"{provider_name}: {exc}")

            if nav_provider is not None and share_rows:
                try:
                    nav_rows = nav_provider.fetch_nav(codes, start, end)
                    nav_by_source = {row.source_id for row in nav_rows}
                    for source_id in nav_by_source:
                        _source_row(connection, source_id, nav_provider, sum(row.source_id == source_id for row in nav_rows))
                    _insert_nav_rows(connection, nav_rows)
                    share_rows = _attach_nav(share_rows, nav_rows)
                    state = "success" if nav_rows else "warning"
                    report.provider_status.append({"provider": nav_provider.__class__.__name__, "status": state, "rows": len(nav_rows)})
                    if not nav_rows:
                        report.warnings.append(f"{nav_provider.__class__.__name__}: empty response; NAV remains unavailable")
                except Exception as exc:
                    report.provider_status.append({"provider": nav_provider.__class__.__name__, "status": "failed", "error": str(exc)})
                    report.warnings.append(f"{nav_provider.__class__.__name__}: {exc}")

            for row in share_rows:
                connection.execute(
                    """INSERT OR IGNORE INTO fund_flow_import_jobs
                       (import_batch_id,source_id,status,started_at,finished_at)
                       VALUES (?,?,?,?,?)""",
                    (row.import_batch_id, row.source_id, "completed", now_iso(), now_iso()),
                )
            report.inserted, report.updated = _insert_rows(connection, share_rows)
            if share_rows:
                report.latest_trade_date = max(row.effective_trade_date for row in share_rows)

            for code in codes:
                records = [row for row in share_rows if row.etf_code == code]
                records.sort(key=lambda row: row.effective_trade_date)
                previous = None
                for row in records:
                    flow = calculate_flow_yi(row, previous)
                    report.metrics.append({"etf_code": code, "trade_date": row.effective_trade_date.isoformat(), "net_flow_yi": flow})
                    previous = row
    materialized = rebuild_materialized(db_path, codes)
    report.warnings.extend([] if materialized["metricCount"] else ["no metrics materialized; raw data may be unavailable"])
    return report

