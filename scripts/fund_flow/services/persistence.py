"""Materialize clean records and metrics from versioned raw SQLite rows."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import json

from ..config import DATABASE_PATH, ETF_UNIVERSE
from ..db import init_fund_flow_schema, open_fund_flow_connection, seed_default_fund_master
from ..models import CleanETFRecord, RawETFRecord
from .corporate_actions import apply_share_unit_adjustment, load_seed_action
from .flows import calculate_series
from .quality import validate_daily_records


def _raw_from_row(row):
    return RawETFRecord(
        etf_code=row[0], record_date=row[1], effective_trade_date=row[2],
        published_at=row[3], total_share=row[4], share_unit=row[5], share_scope=row[6],
        share_date_basis=row[7], nav=row[8], close=row[9], total_size=row[10],
        source_id=row[11], source_version=row[12], import_batch_id=row[13],
    )


def _ensure_seed_actions(connection):
    """Load reviewed metadata files into the audit table, without quote data."""
    event_root = Path(__file__).resolve().parents[3] / "data" / "source_events"
    for path in sorted(event_root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        source_id = f"seed:event:{path.stem}"
        connection.execute("INSERT OR IGNORE INTO fund_flow_data_sources(source_id,url,retrieved_at,row_count,error_message) VALUES (?,?,?,?,?)", (source_id, None, None, 0, "metadata seed; official source URL pending"))
        connection.execute(
            """INSERT OR IGNORE INTO fund_flow_corporate_actions
               (etf_code,ex_date,action_type,event_date,ratio,first_post_record_date,status,value,source_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (payload["etf_code"], payload["ex_date"], payload["action_type"], payload.get("event_date"), payload.get("ratio"), payload.get("first_post_record_date"), payload.get("status", "source_verified"), payload.get("value"), source_id),
        )


def _load_actions(connection, code: str):
    from ..models import CorporateAction
    rows = connection.execute("SELECT etf_code,ex_date,action_type,event_date,ratio,first_post_record_date,status,value FROM fund_flow_corporate_actions WHERE etf_code=? ORDER BY ex_date", (code,)).fetchall()
    return [CorporateAction(etf_code=row[0], ex_date=row[1], action_type=row[2], event_date=row[3], ratio=row[4], first_post_record_date=row[5], status=row[6], value=row[7]) for row in rows]


def rebuild_materialized(db_path: Path = DATABASE_PATH, codes: list[str] | None = None) -> dict:
    """Rebuild clean/metric tables from raw data without deleting raw history."""

    codes = codes or list(ETF_UNIVERSE)
    init_fund_flow_schema(db_path)
    seed_default_fund_master(db_path)
    with open_fund_flow_connection(db_path) as connection:
        _ensure_seed_actions(connection)
        raw_rows = connection.execute(
            """SELECT r.etf_code,r.record_date,r.effective_trade_date,r.published_at,
                      r.total_share,r.share_unit,r.share_scope,r.share_date_basis,
                      COALESCE((SELECT n.nav FROM fund_flow_nav_daily_raw n
                                WHERE n.etf_code=r.etf_code AND n.nav_date=r.effective_trade_date
                                ORDER BY n.rowid DESC LIMIT 1), r.nav),
                      r.close,r.total_size,r.source_id,r.source_version,r.import_batch_id
               FROM fund_flow_etf_daily_raw r
               WHERE r.etf_code IN ({})
               ORDER BY r.etf_code,r.effective_trade_date,r.rowid""".format(",".join("?" for _ in codes)), codes
        ).fetchall()
        grouped: dict[str, list[RawETFRecord]] = {code: [] for code in codes}
        latest_by_key = {}
        for row in raw_rows:
            latest_by_key[(row[0], row[2], row[6])] = _raw_from_row(row)
        for row in latest_by_key.values():
            grouped.setdefault(row.etf_code, []).append(row)
        clean_count = metric_count = 0
        for code, raw in grouped.items():
            if not raw:
                continue
            actions = _load_actions(connection, code)
            clean_rows = apply_share_unit_adjustment(raw, actions)
            issues = validate_daily_records(clean_rows)
            issue_map = {(issue.etf_code, str(issue.trade_date)): issue for issue in issues}
            materialized: list[CleanETFRecord] = []
            for row in clean_rows:
                issue = issue_map.get((row.etf_code, str(row.trade_date)))
                if issue:
                    materialized.append(CleanETFRecord(row.etf_code, row.trade_date, row.shares_wan, row.nav, row.size_yi, row.share_scope, issue.status, tuple(sorted(set(row.error_codes + (issue.code,)))), row.source_id))
                else:
                    materialized.append(row)
                connection.execute(
                    """INSERT OR REPLACE INTO fund_flow_etf_daily_clean
                       (etf_code,trade_date,shares_wan,nav,size_yi,share_scope,validation_status,error_codes,source_id)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (materialized[-1].etf_code, str(materialized[-1].trade_date), materialized[-1].shares_wan, materialized[-1].nav, materialized[-1].size_yi, materialized[-1].share_scope, materialized[-1].validation_status, json.dumps(materialized[-1].error_codes, ensure_ascii=False), materialized[-1].source_id),
                )
                clean_count += 1
            metrics = calculate_series(materialized, [], date.min, date.max)
            for metric in metrics:
                connection.execute(
                    """INSERT OR REPLACE INTO fund_flow_etf_daily_metrics
                       (etf_code,trade_date,shares_adj_wan,nav_adj,delta_shares_wan,net_flow_yi,cum_flow_yi,intensity_pct,calc_version,status)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (metric.etf_code, str(metric.trade_date), metric.shares_adj_wan, metric.nav_adj, metric.delta_shares_wan, metric.net_flow_yi, metric.cum_flow_yi, metric.intensity_pct, metric.calc_version, metric.status),
                )
                metric_count += 1
        connection.commit()
    return {"cleanCount": clean_count, "metricCount": metric_count}
