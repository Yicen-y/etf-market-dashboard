from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import requests

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
                try:
                    frame = retry_call(
                        lambda: ak.fund_etf_scale_sse(date=day_text),
                        retries=self.retries,
                        backoff_seconds=self.backoff_seconds,
                    )
                except Exception:
                    # The official SSE JSON is the source behind AKShare. A
                    # mojibake column map in older AKShare builds can fail
                    # inside the adapter before a DataFrame is returned.
                    frame = self._fetch_official(day_text)
                required = {"基金代码", "基金份额"}
                if not required.issubset(frame.columns):
                    # Some installed AKShare builds expose the source fields
                    # with mojibake column labels. The SSE response order is
                    # stable, so normalize by position after validating width.
                    if len(frame.columns) >= 6:
                        frame = frame.copy()
                        frame.columns = ["序号", "基金代码", "基金简称", "ETF类型", "统计日期", "基金份额", *list(frame.columns[6:])]
                    else:
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
                            # AKShare's SSE adapter returns shares, while the
                            # dashboard stores 万份 for both exchanges.
                            total_share=as_float(record["基金份额"], "基金份额") / 10000,
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

    @staticmethod
    def _fetch_official(day_text: str) -> pd.DataFrame:
        response = requests.get(
            "https://query.sse.com.cn/commonQuery.do",
            params={
                "isPagination": "true",
                "pageHelp.pageSize": "10000",
                "pageHelp.pageNo": "1",
                "pageHelp.beginPage": "1",
                "pageHelp.cacheSize": "1",
                "pageHelp.endPage": "1",
                "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L",
                "STAT_DATE": f"{day_text[:4]}-{day_text[4:6]}-{day_text[6:]}",
            },
            headers={"Referer": "https://www.sse.com.cn/", "User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        data = (payload.get("pageHelp") or {}).get("data") or []
        return pd.DataFrame(
            [
                {"序号": item.get("NUM"), "基金代码": item.get("SEC_CODE"), "基金简称": item.get("SEC_NAME"), "ETF类型": item.get("ETF_TYPE"), "统计日期": item.get("STAT_DATE"), "基金份额": float(item["TOT_VOL"]) * 10000}
                for item in data
                if item.get("SEC_CODE") and item.get("TOT_VOL") not in (None, "")
            ],
            columns=["序号", "基金代码", "基金简称", "ETF类型", "统计日期", "基金份额"],
        )

