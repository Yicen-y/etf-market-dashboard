from __future__ import annotations

import os
from datetime import date

from .base import ProviderUnavailable


class TushareProvider:
    """Optional adapter; it never prevents the application from starting."""

    def __init__(self, token: str | None = None):
        self.token = token or os.getenv("TUSHARE_TOKEN")

    def fetch(self, codes: list[str], start: date, end: date):
        if not self.token:
            raise ProviderUnavailable("TUSHARE_TOKEN is not configured")
        try:
            import tushare as ts
        except ImportError as exc:
            raise ProviderUnavailable("tushare is not installed") from exc
        client = ts.pro_api(self.token)
        return client.etf_share_size(
            ts_code=",".join(codes),
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )

