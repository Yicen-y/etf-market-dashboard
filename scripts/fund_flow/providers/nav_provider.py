from __future__ import annotations

from datetime import date
import math
import time

import requests

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
            try:
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
                if not frame.empty:
                    rows.extend(self._records(code, fund_code, frame.to_dict("records"), start, end, "akshare"))
                    continue
            except Exception:
                # New Eastmoney responses have 14 columns while older AKShare
                # releases still rename exactly 13 columns. Use the same
                # official endpoint with a compatible parser in that case.
                pass

            records = retry_call(
                lambda: self._fetch_eastmoney_records(fund_code, start, end),
                retries=self.retries,
                backoff_seconds=self.backoff_seconds,
            )
            rows.extend(self._records(code, fund_code, records, start, end, "eastmoney-api"))
        return rows

    @staticmethod
    def _records(code: str, fund_code: str, records: list[dict], start: date, end: date, version: str) -> list[RawNAVRecord]:
        result: list[RawNAVRecord] = []
        for record in records:
            nav_date = parse_date(record.get("净值日期") or record.get("FSRQ"))
            if not start <= nav_date <= end:
                continue
            nav_value = record.get("单位净值") if "单位净值" in record else record.get("DWJZ")
            cumulative_value = record.get("累计净值") if "累计净值" in record else record.get("LJJZ")
            result.append(
                RawNAVRecord(
                    etf_code=as_exchange_code(code, code.split(".")[-1]),
                    nav_date=nav_date,
                    nav=as_float(nav_value, "单位净值"),
                    cumulative_nav=(None if cumulative_value in (None, "") else as_float(cumulative_value, "累计净值")),
                    unit="元/份",
                    source_id=f"{AkshareNavProvider.source_prefix}:{fund_code}",
                    source_version=version,
                )
            )
        return result

    @staticmethod
    def _fetch_eastmoney_records(fund_code: str, start: date, end: date) -> list[dict]:
        url = "https://api.fund.eastmoney.com/f10/lsjz"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"https://fundf10.eastmoney.com/jjjz_{fund_code}.html",
        }
        page_size = 20
        params = {
            "fundCode": fund_code,
            "pageIndex": 1,
            "pageSize": page_size,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "_": round(time.time() * 1000),
        }
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        data = (payload.get("Data") or {})
        first_page = data.get("LSJZList") or []
        # Eastmoney exposes TotalCount at the response root, not inside Data.
        total_count = int(payload.get("TotalCount") or data.get("TotalCount") or len(first_page))
        if not isinstance(first_page, list):
            raise ProviderSchemaError("Eastmoney NAV response has invalid LSJZList")
        records = list(first_page)
        for page in range(2, max(1, math.ceil(total_count / page_size)) + 1):
            params["pageIndex"] = page
            page_response = requests.get(url, params=params, headers=headers, timeout=30)
            page_response.raise_for_status()
            page_data = (page_response.json().get("Data") or {}).get("LSJZList") or []
            if not isinstance(page_data, list):
                raise ProviderSchemaError(f"Eastmoney NAV page {page} has invalid LSJZList")
            records.extend(page_data)
        return records

