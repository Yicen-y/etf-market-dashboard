"""Confirmed closed-market candidate keys retired from future ingestion."""

MAINLAND_CODES = frozenset({"932000CNY010", "H00300", "H00811", "H00813", "H00821",
                            "H00918", "H00919", "H00922", "H20035", "H20180", "H20903"})
SATURDAY_DATES = frozenset({"20261031", "20261107", "20261114"})


def is_retired_nontrading_candidate(code: str, day: str) -> bool:
    return (code in MAINLAND_CODES and day in SATURDAY_DATES) or (code == "H00922" and day == "20180618")
