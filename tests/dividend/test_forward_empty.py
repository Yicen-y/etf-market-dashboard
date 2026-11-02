from datetime import date
from decimal import Decimal

from scripts.dividend.domain import Coverage, calculate_forward_groups


def test_empty_forward_groups_are_unavailable_not_zero():
    result = calculate_forward_groups(date(2026, 1, 1), Decimal("2"), [], Coverage.complete())
    assert result.confirmed.value_pct is None
    assert result.proposal.value_pct is None
    assert result.proposal.reason
