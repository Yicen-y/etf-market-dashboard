from datetime import date
from decimal import Decimal

from scripts.dividend.domain import (
    CashEvent, Coverage, adjust_for_actions, calculate_annual_reference,
    calculate_forward_groups, calculate_ttm, normalize_cash_amount,
)


def event(code="510880", ex="2026-01-21", amount="0.14300", year=2026, status="PAID"):
    return CashEvent(code, date.fromisoformat(ex), Decimal(amount), year, status, "e1", "r1")


def test_normalizes_per_ten_units_with_decimal():
    assert normalize_cash_amount(Decimal("1.4300"), "PER_10") == Decimal("0.14300")


def test_ttm_uses_left_open_365_day_window_and_paid_events_only():
    result = calculate_ttm(date(2026, 10, 23), Decimal("2.00"), [event(), event(ex="2025-10-23", amount="9")], Coverage.complete())
    assert result.value_pct == Decimal("7.1500")
    assert result.event_ids == ("e1",)


def test_incomplete_coverage_blocks_precise_value():
    result = calculate_ttm(date(2026, 10, 23), Decimal("2.00"), [event()], Coverage.incomplete("partial source"))
    assert result.value_pct is None
    assert result.reason == "partial source"


def test_annual_reference_uses_event_year_for_etf():
    result = calculate_annual_reference(date(2026, 10, 23), Decimal("2"), [event(ex="2025-12-31", amount="1", year=2025)], Coverage.complete(), kind="ETF")
    assert result.value_pct == Decimal("50.00")


def test_forward_groups_do_not_mix_confirmed_and_proposal():
    result = calculate_forward_groups(date(2026, 10, 23), Decimal("2"), [event(ex="2026-11-01", status="CONFIRMED"), event(ex="2026-12-01", amount="0.2", status="PROPOSAL")], Coverage.complete())
    assert result.confirmed.value_pct == Decimal("7.15")
    assert result.proposal.value_pct == Decimal("10.00")


def test_split_adjustment_divides_old_amount_by_ratio():
    assert adjust_for_actions(Decimal("1"), [Decimal("2")]) == Decimal("0.5")
