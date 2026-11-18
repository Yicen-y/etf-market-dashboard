"""Minimal fetch-only provider contract for the ETF close pilot."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from .fetch_data import FetchResult


@dataclass(frozen=True)
class DataRequest:
    instrument_id: str
    dataset_type: str
    start_date: str
    end_date: str
    adjustment: str
    return_type: str
    currency: str
    unit: str
    calendar: str
    as_of: str

    def __post_init__(self):
        parts = self.instrument_id.split(":")
        if len(parts) != 3 or parts[0] != "ETF" or parts[1] not in {"SH", "SZ"} or not parts[2].isdigit():
            raise ValueError("ETF instrument must include market")
        if (self.dataset_type, self.adjustment, self.return_type, self.currency, self.unit) != (
                "etf_daily_close", "none", "price", "CNY", "CNY_PER_SHARE"):
            raise ValueError("unsupported ETF price basis")
        if len(self.start_date) != 8 or len(self.end_date) != 8 or self.start_date > self.end_date:
            raise ValueError("invalid date range")
        try:
            datetime.strptime(self.start_date, "%Y%m%d")
            datetime.strptime(self.end_date, "%Y%m%d")
            as_of = datetime.fromisoformat(self.as_of)
            if as_of.tzinfo is None:
                raise ValueError("as_of timezone required")
        except ValueError as error:
            raise ValueError("invalid request date") from error
        if self.calendar != parts[1]:
            raise ValueError("market calendar mismatch")


class DataProvider(Protocol):
    name: str
    capabilities: frozenset[str]

    def fetch(self, request: DataRequest) -> FetchResult: ...


class LegacyEtfAdapter:
    name = "akshare_etf_history"
    capabilities = frozenset({"etf_daily_close:SH", "etf_daily_close:SZ"})

    def __init__(self, fetcher: Callable, api_key: str | None = None):
        self.fetcher = fetcher
        self.api_key = api_key

    def fetch(self, request: DataRequest) -> FetchResult:
        _, market, code = request.instrument_id.split(":")
        if f"{request.dataset_type}:{market}" not in self.capabilities or not code.isdigit():
            raise ValueError("provider does not support request")
        result = self.fetcher(code, request.start_date, request.end_date, self.api_key)
        if not isinstance(result, FetchResult):
            raise TypeError("provider must return FetchResult")
        return result


class DataProviderManager:
    """Retries transport failures only; never decides whether fetched rows may publish."""

    def __init__(self, providers: list[DataProvider], *, retries: int = 0, cooldown_seconds: int = 60):
        self.providers = {provider.name: provider for provider in providers}
        self.retries = retries
        self.cooldown_seconds = cooldown_seconds
        self.failures: dict[str, int] = {}
        self.open_until: dict[str, float] = {}

    def fetch(self, provider_name: str, request: DataRequest) -> FetchResult:
        provider = self.providers[provider_name]
        market = request.instrument_id.split(":")[1]
        if f"{request.dataset_type}:{market}" not in provider.capabilities:
            raise ValueError("provider capability mismatch")
        if time.monotonic() < self.open_until.get(provider_name, 0):
            raise ConnectionError("provider circuit open")
        for attempt in range(self.retries + 1):
            try:
                result = provider.fetch(request)
                self.failures[provider_name] = 0
                return result
            except (ConnectionError, TimeoutError):
                failures = self.failures.get(provider_name, 0) + 1
                self.failures[provider_name] = failures
                if failures >= 3:
                    self.open_until[provider_name] = time.monotonic() + self.cooldown_seconds
                if attempt >= self.retries:
                    raise
        raise AssertionError("unreachable")


def etf_close_request(code: str, start_date: str, end_date: str) -> DataRequest:
    market = "SH" if code.startswith("5") else "SZ"
    return DataRequest(f"ETF:{market}:{code}", "etf_daily_close", start_date, end_date,
                       "none", "price", "CNY", "CNY_PER_SHARE", market,
                       datetime.now(timezone.utc).isoformat(timespec="seconds"))
