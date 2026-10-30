"""Net-subscription calculations with explicit units and incomplete states."""

from __future__ import annotations

from datetime import date
from typing import Sequence

from ..models import CleanETFRecord, CorporateAction, DailyMetric
from .corporate_actions import validate_corporate_action


CALC_VERSION = "fund-flow-v1"


def calculate_intensity(flow_yi: float, previous_size_yi: float | None) -> float | None:
    if previous_size_yi is None or previous_size_yi == 0:
        return None
    return flow_yi / previous_size_yi * 100


def calculate_daily_metric(
    current: CleanETFRecord,
    previous: CleanETFRecord | None,
    status: str | None = None,
) -> DailyMetric:
    status = status or current.validation_status
    if previous is None:
        return DailyMetric(current.etf_code, current.trade_date, current.shares_wan, current.nav, None, None, None, None, CALC_VERSION, "BLOCKED")
    if current.shares_wan is None or current.nav is None or previous.shares_wan is None or status == "BLOCKED":
        return DailyMetric(current.etf_code, current.trade_date, current.shares_wan, current.nav, None, None, None, None, CALC_VERSION, "BLOCKED")
    delta = current.shares_wan - previous.shares_wan
    flow = delta * current.nav / 10000
    return DailyMetric(current.etf_code, current.trade_date, current.shares_wan, current.nav, delta, flow, None, calculate_intensity(flow, previous.size_yi), CALC_VERSION, status if status in {"PASS", "WARNING"} else "PASS")


def calculate_series(
    rows: Sequence[CleanETFRecord], actions: Sequence[CorporateAction], start: date, end: date
) -> list[DailyMetric]:
    raw_like = list(rows)
    # Clean records are normally already adjusted during ingestion.  Applying
    # verified actions here as well makes the calculation API safe for callers
    # that pass a clean slice directly, while unverified actions remain blocked.
    adjusted: list[CleanETFRecord] = []
    for row in raw_like:
        shares, nav, status, errors = row.shares_wan, row.nav, row.validation_status, list(row.error_codes)
        day = row.trade_date if isinstance(row.trade_date, date) else date.fromisoformat(row.trade_date)
        for action in actions:
            if action.etf_code != row.etf_code:
                continue
            action_issues = validate_corporate_action(action)
            if action_issues and day >= date.fromisoformat(str(action.ex_date)):
                status = "BLOCKED"
                errors.extend(issue.code for issue in action_issues)
            elif day < date.fromisoformat(str(action.first_post_record_date)):
                shares = None if shares is None else shares * action.ratio
                nav = None if nav is None else nav / action.ratio
        size = None if shares is None or nav is None else shares * nav / 10000
        adjusted.append(CleanETFRecord(row.etf_code, row.trade_date, shares, nav, size, row.share_scope, status, tuple(sorted(set(errors))), row.source_id))
    # Keep the row immediately before the requested start date.  It is needed
    # to calculate the first requested day's delta instead of fabricating a
    # zero-flow start.
    ordered_all = sorted(adjusted, key=lambda row: row.trade_date)
    result: list[DailyMetric] = []
    previous = None
    previous_valid = False
    cumulative = 0.0
    cumulative_available = True
    for row in ordered_all:
        day = row.trade_date if isinstance(row.trade_date, date) else date.fromisoformat(row.trade_date)
        metric = calculate_daily_metric(row, previous if previous_valid else None, row.validation_status)
        if previous is None:
            metric = DailyMetric(row.etf_code, row.trade_date, metric.shares_adj_wan, metric.nav_adj, None, None, 0.0, None, CALC_VERSION, "BLOCKED")
        elif not previous_valid or metric.net_flow_yi is None:
            cumulative_available = False
            metric = DailyMetric(row.etf_code, row.trade_date, metric.shares_adj_wan, metric.nav_adj, metric.delta_shares_wan, None, None, metric.intensity_pct, CALC_VERSION, "BLOCKED")
        elif cumulative_available:
            cumulative += metric.net_flow_yi
            metric = DailyMetric(row.etf_code, row.trade_date, metric.shares_adj_wan, metric.nav_adj, metric.delta_shares_wan, metric.net_flow_yi, cumulative, metric.intensity_pct, CALC_VERSION, metric.status)
        if day >= start and day <= end:
            result.append(metric)
        previous = row
        previous_valid = row.validation_status != "BLOCKED" and row.shares_wan is not None and row.nav is not None
    return result


def calculate_rolling_flow(metrics: Sequence[DailyMetric], window: int) -> float | None:
    if window <= 0 or len(metrics) < window:
        return None
    values = [metric.net_flow_yi for metric in metrics[-window:]]
    return None if any(value is None for value in values) else sum(values)


def aggregate_selected_etfs(metrics: Sequence[DailyMetric], selected_codes: list[str], start: date, end: date) -> list[dict]:
    grouped: dict[date, list[DailyMetric]] = {}
    for metric in metrics:
        day = metric.trade_date if isinstance(metric.trade_date, date) else date.fromisoformat(metric.trade_date)
        if day < start or day > end or metric.etf_code not in selected_codes:
            continue
        grouped.setdefault(day, []).append(metric)
    output = []
    for day in sorted(grouped):
        by_code = {metric.etf_code: metric for metric in grouped[day]}
        covered = [code for code in selected_codes if code in by_code and by_code[code].net_flow_yi is not None]
        missing = [code for code in selected_codes if code not in covered]
        values = [by_code[code].net_flow_yi for code in covered]
        output.append({
            "trade_date": day.isoformat(),
            "net_flow_yi": sum(values) if not missing else None,
            "coverage_codes": covered,
            "missing_codes": missing,
            "coverage_ratio": len(covered) / len(selected_codes) if selected_codes else 0,
            "status": "PASS" if not missing else "INCOMPLETE",
        })
    return output
