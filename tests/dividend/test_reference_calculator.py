from datetime import date
from decimal import Decimal

from scripts.dividend.domain import CashEvent, Coverage, calculate_ttm
from tests.dividend.reference_calculator import independent_per_unit, independent_ttm


def test_510880_unit_and_date_fixture_matches_independent_recalculation():
    assert independent_per_unit("1.4300", "PER_10") == Decimal("0.14300")
    rows = [{"ex_date": "2026-01-21", "amount_per_unit": "0.14300", "status": "PAID"}]
    expected = independent_ttm(date(2026, 10, 23), "2", rows)
    actual = calculate_ttm(date(2026, 10, 23), Decimal("2"), [CashEvent("ETF:510880", date(2026, 1, 21), Decimal("0.14300"), 2026, "PAID", "510880-2026-01", "r1")], Coverage.complete())
    assert actual.value_pct == expected
