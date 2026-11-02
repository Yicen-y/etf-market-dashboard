from datetime import date, timedelta
from decimal import Decimal


def independent_ttm(as_of, price, rows):
    start = as_of - timedelta(days=365)
    total = sum((Decimal(row["amount_per_unit"]) for row in rows if start < date.fromisoformat(row["ex_date"]) <= as_of and row["status"] == "PAID"), Decimal("0"))
    return (total / Decimal(price) * Decimal("100")).quantize(Decimal("0.0001"))


def independent_per_unit(amount, unit):
    return (Decimal(amount) / (Decimal("10") if unit == "PER_10" else Decimal("1"))).quantize(Decimal("0.00001"))
