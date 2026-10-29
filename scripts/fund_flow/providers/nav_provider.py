from __future__ import annotations

from datetime import date

from ..models import RawNAVRecord
from .base import ProviderSchemaError, as_exchange_code, as_float, now_iso, parse_date, retry_call


class AkshareNavProvider:
    """Historical unit NAV from a separate fund-data endpoint."""

    source_prefix = "akshare:nav"
    source_url = "https://fund.eastmoney.com/"

    def __init__(self, *, retries: int = 3, backoff_seconds: float = 0.2):
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    def fetch_nav(self, codes: list[str], start: date, end: date) -> list[RawNAVRecord]:
        import akshare as ak

        rows: list[RawNAVRecord] = []
        for code in codes:
            fund_code = str(code).split(".", 1)[0].zfill(6)
            frame = retry_call(
                lambda: ak.fund_etf_fund_info_em(
                    fund=fund_code,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                ),
                retries=self.retries,
                backoff_seconds=self.backoff_seconds,
            )
            required = {"净值日期", "单位净值"}
            if not required.issubset(frame.columns):
                raise ProviderSchemaError(f"NAV response missing columns: {sorted(required - set(frame.columns))}")
            for record in frame.to_dict("records"):
                nav_date = parse_date(record["净值日期"])
                if not start <= nav_date <= end:
                    continue
                rows.append(
                    RawNAVRecord(
                        etf_code=as_exchange_code(code, code.split(".")[-1]),
                        nav_date=nav_date,
                        nav=as_float(record["单位净值"], "单位净值"),
                        cumulative_nav=(
                            None if record.get("累计净值") in (None, "") else as_float(record["累计净值"], "累计净值")
                        ),
                        unit="元/份",
                        source_id=f"{self.source_prefix}:{fund_code}",
                        source_version="akshare",
                    )
                )
        return rows

