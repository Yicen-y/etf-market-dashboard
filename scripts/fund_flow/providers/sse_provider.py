from __future__ import annotations

from datetime import date, timedelta

from ..models import RawETFRecord
from .base import ProviderSchemaError, as_exchange_code, as_float, now_iso, parse_date, retry_call


class AkshareSSEProvider:
    """Shanghai exchange ETF shares through AKShare's official SSE adapter."""

    source_prefix = "akshare:sse"
    source_url = "https://www.sse.com.cn/assortment/fund/etf/list/scale/"

    def __init__(self, *, retries: int = 3, backoff_seconds: float = 0.2):
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    def fetch(self, codes: list[str], start: date, end: date) -> list[RawETFRecord]:
        import akshare as ak

        wanted = {as_exchange_code(code, "SH") for code in codes}
        rows: list[RawETFRecord] = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                day_text = current.strftime("%Y%m%d")
                frame = retry_call(
                    lambda: ak.fund_etf_scale_sse(date=day_text),
                    retries=self.retries,
                    backoff_seconds=self.backoff_seconds,
                )
                required = {"基金代码", "基金份额"}
                if not required.issubset(frame.columns):
                    raise ProviderSchemaError(f"SSE response missing columns: {sorted(required - set(frame.columns))}")
                source_id = f"{self.source_prefix}:{day_text}"
                for record in frame.to_dict("records"):
                    code = as_exchange_code(record["基金代码"], "SH")
                    if code not in wanted:
                        continue
                    record_date = parse_date(record.get("统计日期", current))
                    rows.append(
                        RawETFRecord(
                            etf_code=code,
                            record_date=record_date,
                            effective_trade_date=record_date,
                            published_at=now_iso(),
                            total_share=as_float(record["基金份额"], "基金份额"),
                            share_unit="万份",
                            share_scope="on_exchange",
                            share_date_basis="post_close",
                            nav=None,
                            close=None,
                            total_size=None,
                            source_id=source_id,
                            source_version="akshare",
                            import_batch_id=f"batch-{source_id}",
                        )
                    )
            current += timedelta(days=1)
        return rows

