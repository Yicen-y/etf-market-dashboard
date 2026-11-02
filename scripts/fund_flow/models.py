"""Immutable boundary records; quality rules and calculations live in later tasks."""

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
import re
from typing import Literal, Optional, Union, get_args

DateValue = Union[str, date]
ValidationStatus = Literal["PASS", "WARNING", "BLOCKED"]
MetricStatus = Literal["PASS", "WARNING", "BLOCKED", "INCOMPLETE"]
ImportJobStatus = Literal["pending", "running", "completed", "failed"]
CorporateActionStatus = Literal["discovered", "source_verified", "basis_verified", "applied", "rejected"]


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def _date(value: DateValue) -> None:
    if type(value) is date:
        return
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("date must be YYYY-MM-DD or datetime.date")
    date.fromisoformat(value)


def _identity(code: str, day: DateValue) -> None:
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}\.(SH|SZ)", code):
        raise ValueError("etf_code must include .SH or .SZ")
    _date(day)


def _number(value: Optional[float], name: str, nonnegative: bool = False) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be finite or None")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _status(value: str, allowed) -> None:
    if value not in get_args(allowed):
        raise ValueError(f"unsupported status: {value!r}")


@dataclass(frozen=True)
class RawETFRecord:
    """Source values retain units, scope, missing values and even negative evidence."""

    etf_code: str
    record_date: DateValue
    effective_trade_date: DateValue
    published_at: Optional[str]
    total_share: Optional[float]
    share_unit: str
    share_scope: str
    share_date_basis: str
    nav: Optional[float]
    close: Optional[float]
    total_size: Optional[float]
    source_id: str
    source_version: str
    import_batch_id: str

    def __post_init__(self):
        _identity(self.etf_code, self.record_date)
        _date(self.effective_trade_date)
        if self.published_at is not None:
            _text(self.published_at, "published_at")
            if "T" not in self.published_at and " " not in self.published_at:
                raise ValueError("published_at must include a time")
            datetime.fromisoformat(self.published_at.replace("Z", "+00:00"))
        for name in ("share_unit", "share_scope", "share_date_basis", "source_id", "source_version", "import_batch_id"):
            _text(getattr(self, name), name)
        for name in ("total_share", "nav", "close", "total_size"):
            _number(getattr(self, name), name)


@dataclass(frozen=True)
class RawNAVRecord:
    etf_code: str
    nav_date: DateValue
    nav: float
    cumulative_nav: Optional[float]
    unit: str
    source_id: str
    source_version: str

    def __post_init__(self):
        _identity(self.etf_code, self.nav_date)
        _number(self.nav, "nav", nonnegative=True)
        _number(self.cumulative_nav, "cumulative_nav", nonnegative=True)
        for name in ("unit", "source_id", "source_version"):
            _text(getattr(self, name), name)


@dataclass(frozen=True)
class CleanETFRecord:
    etf_code: str
    trade_date: DateValue
    shares_wan: Optional[float]
    nav: Optional[float]
    size_yi: Optional[float]
    share_scope: str
    validation_status: ValidationStatus
    error_codes: tuple[str, ...]
    source_id: str

    def __post_init__(self):
        _identity(self.etf_code, self.trade_date)
        _status(self.validation_status, ValidationStatus)
        for name in ("share_scope", "source_id"):
            _text(getattr(self, name), name)
        for name in ("shares_wan", "nav", "size_yi"):
            _number(getattr(self, name), name, nonnegative=True)
        if not isinstance(self.error_codes, tuple):
            raise ValueError("error_codes must be an immutable tuple")
        for code in self.error_codes:
            _text(code, "error_code")


@dataclass(frozen=True)
class DailyMetric:
    etf_code: str
    trade_date: DateValue
    shares_adj_wan: Optional[float]
    nav_adj: Optional[float]
    delta_shares_wan: Optional[float]
    net_flow_yi: Optional[float]
    cum_flow_yi: Optional[float]
    intensity_pct: Optional[float]
    calc_version: str
    status: MetricStatus

    def __post_init__(self):
        _identity(self.etf_code, self.trade_date)
        _status(self.status, MetricStatus)
        _text(self.calc_version, "calc_version")
        for name in ("shares_adj_wan", "nav_adj", "delta_shares_wan", "net_flow_yi", "cum_flow_yi", "intensity_pct"):
            _number(getattr(self, name), name, nonnegative=name in ("shares_adj_wan", "nav_adj"))


@dataclass(frozen=True)
class CorporateAction:
    etf_code: str
    ex_date: DateValue
    action_type: str
    event_date: Optional[DateValue] = None
    ratio: Optional[float] = None
    first_post_record_date: Optional[DateValue] = None
    status: CorporateActionStatus = "discovered"
    value: Optional[float] = None

    def __post_init__(self):
        _identity(self.etf_code, self.ex_date)
        _text(self.action_type, "action_type")
        _status(self.status, CorporateActionStatus)
        for day in (self.event_date, self.first_post_record_date):
            if day is not None:
                _date(day)
        _number(self.value, "value")
        _number(self.ratio, "ratio")
        if self.ratio is not None and self.ratio <= 0:
            raise ValueError("ratio must be positive")


@dataclass(frozen=True)
class QualityIssue:
    etf_code: str
    trade_date: DateValue
    code: str
    message: str
    status: ValidationStatus = "WARNING"

    def __post_init__(self):
        _identity(self.etf_code, self.trade_date)
        _text(self.code, "code")
        _text(self.message, "message")
        _status(self.status, ValidationStatus)


@dataclass(frozen=True)
class ImportJob:
    import_batch_id: str
    source_id: str
    status: ImportJobStatus

    def __post_init__(self):
        _text(self.import_batch_id, "import_batch_id")
        _text(self.source_id, "source_id")
        _status(self.status, ImportJobStatus)
