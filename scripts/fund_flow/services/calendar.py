"""Trading-date helpers used by the fund-flow calculation layer."""

from __future__ import annotations

from datetime import date
from typing import Sequence

from ..models import CleanETFRecord


def resolve_previous_trading_date(
    rows: Sequence[CleanETFRecord], trade_date: date
) -> date | None:
    """Return the latest observed date before ``trade_date``.

    This deliberately uses observed, cleaned records instead of assuming that
    every weekday is a trading day.  The exchange calendar can be added later
    without changing the calculation contract.
    """

    dates = sorted({
        row.trade_date if isinstance(row.trade_date, date) else date.fromisoformat(row.trade_date)
        for row in rows
        if (row.trade_date if isinstance(row.trade_date, date) else date.fromisoformat(row.trade_date)) < trade_date
    })
    return dates[-1] if dates else None
