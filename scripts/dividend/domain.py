from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional, Sequence


MONEY = Decimal("0.00001")
PERCENT = Decimal("0.0001")


@dataclass(frozen=True)
class CashEvent:
    security_id: str
    ex_date: date
    amount_per_unit: Decimal
    fiscal_year: Optional[int]
    status: str
    event_id: str
    revision_id: str


@dataclass(frozen=True)
class Coverage:
    status: str
    reason: Optional[str] = None

    @classmethod
    def complete(cls):
        return cls("COMPLETE")

    @classmethod
    def incomplete(cls, reason: str):
        return cls("INCOMPLETE", reason)


@dataclass(frozen=True)
class MetricResult:
    value_pct: Optional[Decimal]
    numerator_cash_per_unit: Optional[Decimal]
    denominator_price: Decimal
    event_ids: tuple[str, ...]
    reason: Optional[str] = None


@dataclass(frozen=True)
class ForwardResult:
    confirmed: MetricResult
    proposal: MetricResult


def normalize_cash_amount(amount: Decimal, unit: str) -> Decimal:
    if unit == "PER_10":
        amount = amount / Decimal("10")
    elif unit != "PER_UNIT":
        raise ValueError(f"unsupported cash unit: {unit}")
    return amount.quantize(MONEY, rounding=ROUND_HALF_UP)


def adjust_for_actions(amount: Decimal, ratios: Sequence[Decimal]) -> Decimal:
    result = amount
    for ratio in ratios:
        if ratio <= 0:
            raise ValueError("corporate-action ratio must be positive")
        result /= ratio
    return result.quantize(MONEY, rounding=ROUND_HALF_UP)


def _metric(price: Decimal, events: Iterable[CashEvent], coverage: Coverage) -> MetricResult:
    selected = tuple(events)
    if coverage.status != "COMPLETE":
        return MetricResult(None, None, price, tuple(e.event_id for e in selected), coverage.reason or "incomplete coverage")
    if price <= 0:
        return MetricResult(None, None, price, tuple(e.event_id for e in selected), "missing or invalid price")
    numerator = sum((e.amount_per_unit for e in selected), Decimal("0")).quantize(MONEY, rounding=ROUND_HALF_UP)
    value = (numerator / price * Decimal("100")).quantize(PERCENT, rounding=ROUND_HALF_UP)
    return MetricResult(value, numerator, price, tuple(e.event_id for e in selected))


def calculate_ttm(as_of: date, price: Decimal, events: Iterable[CashEvent], coverage: Coverage) -> MetricResult:
    start = as_of - timedelta(days=365)
    selected = (e for e in events if start < e.ex_date <= as_of and e.status == "PAID")
    return _metric(price, selected, coverage)


def calculate_annual_reference(as_of: date, price: Decimal, events: Iterable[CashEvent], coverage: Coverage, *, kind: str) -> MetricResult:
    target_year = as_of.year - 1 if kind == "ETF" else max((e.fiscal_year for e in events if e.fiscal_year is not None), default=None)
    selected = (e for e in events if e.status == "PAID" and (e.ex_date.year if kind == "ETF" else e.fiscal_year) == target_year)
    return _metric(price, selected, coverage)


def calculate_forward_groups(as_of: date, price: Decimal, events: Iterable[CashEvent], coverage: Coverage) -> ForwardResult:
    future = (e for e in events if e.ex_date > as_of and e.status in {"CONFIRMED", "PROPOSAL"})
    confirmed = []
    proposal = []
    for event in future:
        (confirmed if event.status == "CONFIRMED" else proposal).append(event)
    def empty_metric() -> MetricResult:
        return MetricResult(None, None, price, (), "暂无已公告待派或预案")
    return ForwardResult(empty_metric() if not confirmed else _metric(price, confirmed, coverage), empty_metric() if not proposal else _metric(price, proposal, coverage))
