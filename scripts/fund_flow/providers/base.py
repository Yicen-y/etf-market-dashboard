from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import hashlib
import time
from typing import Callable, Generic, Protocol, TypeVar

from ..models import RawETFRecord, RawNAVRecord


class ProviderUnavailable(RuntimeError):
    """A source could not be reached or did not satisfy its contract."""


class ProviderSchemaError(ProviderUnavailable):
    """A provider response changed or is missing required fields."""


class ShareProvider(Protocol):
    def fetch(self, codes: list[str], start: date, end: date) -> list[RawETFRecord]: ...


class NavProvider(Protocol):
    def fetch_nav(self, codes: list[str], start: date, end: date) -> list[RawNAVRecord]: ...


T = TypeVar("T")


def retry_call(
    operation: Callable[[], T],
    *,
    retries: int = 3,
    backoff_seconds: float = 0.2,
) -> T:
    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            return operation()
        except Exception as exc:  # provider libraries expose varied exceptions
            last_error = exc
            if attempt + 1 < max(1, retries):
                time.sleep(backoff_seconds * (attempt + 1))
    raise ProviderUnavailable(str(last_error)) from last_error


def as_exchange_code(code: object, exchange: str) -> str:
    text = str(code).strip().upper()
    if "." in text:
        return text
    return f"{text.zfill(6)}.{exchange}"


def as_float(value: object, field: str) -> float:
    if value is None or str(value).strip() == "":
        raise ProviderSchemaError(f"missing {field}")
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ProviderSchemaError(f"invalid {field}: {value!r}") from exc


def parse_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    raise ProviderSchemaError(f"invalid date: {value!r}")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def checksum_text(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def date_chunks(start: date, end: date, days: int = 180):
    current = start
    while current <= end:
        chunk_end = min(end, current + timedelta(days=days - 1))
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)

