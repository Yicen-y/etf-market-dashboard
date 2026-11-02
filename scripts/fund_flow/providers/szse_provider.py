from __future__ import annotations

from datetime import date
from io import BytesIO
import random
import zipfile
import xml.etree.ElementTree as ET

import requests
import pandas as pd

from ..models import RawETFRecord
from .base import ProviderSchemaError, as_exchange_code, as_float, date_chunks, now_iso, parse_date, retry_call


class AkshareSZSEProvider:
    """Shenzhen exchange ETF shares through AKShare's six-month window API."""

    source_prefix = "akshare:szse"
    source_url = "https://www.szse.cn/market/fund/volume/etf/index.html"

    def __init__(self, *, retries: int = 3, backoff_seconds: float = 0.2):
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    def fetch(self, codes: list[str], start: date, end: date) -> list[RawETFRecord]:
        import akshare as ak

        wanted = {as_exchange_code(code, "SZ") for code in codes}
        rows: list[RawETFRecord] = []
        for chunk_start, chunk_end in date_chunks(start, end, days=180):
            try:
                frame = retry_call(
                    lambda: ak.fund_scale_daily_szse(
                        start_date=chunk_start.strftime("%Y%m%d"),
                        end_date=chunk_end.strftime("%Y%m%d"),
                        symbol="ETF",
                    ),
                    retries=self.retries,
                    backoff_seconds=self.backoff_seconds,
                )
            except Exception:
                # Older local openpyxl versions can fail inside AKShare before
                # it returns a frame. Parse the same official SZSE workbook.
                frame = self._fetch_official_workbook(chunk_start, chunk_end)
            required = {"日期", "基金代码", "基金份额"}
            if not required.issubset(frame.columns):
                raise ProviderSchemaError(f"SZSE response missing columns: {sorted(required - set(frame.columns))}")
            for record in frame.to_dict("records"):
                code = as_exchange_code(record["基金代码"], "SZ")
                if code not in wanted:
                    continue
                record_date = parse_date(record["日期"])
                raw_shares = as_float(record["基金份额"], "基金份额")
                rows.append(
                    RawETFRecord(
                        etf_code=code,
                        record_date=record_date,
                        effective_trade_date=record_date,
                        published_at=now_iso(),
                        total_share=raw_shares / 10000,
                        share_unit="万份",
                        share_scope="on_exchange",
                        share_date_basis="post_close",
                        nav=None,
                        close=None,
                        total_size=None,
                        source_id=f"{self.source_prefix}:{chunk_start:%Y%m%d}-{chunk_end:%Y%m%d}",
                        source_version="akshare",
                        import_batch_id=f"batch-{self.source_prefix}:{chunk_start:%Y%m%d}-{chunk_end:%Y%m%d}",
                    )
                )
        return rows

    @staticmethod
    def _fetch_official_workbook(start: date, end: date):
        response = requests.get(
            "https://www.szse.cn/api/report/ShowReport",
            params={
                "SHOWTYPE": "xlsx",
                "CATALOGID": "scsj_fund_jjgm",
                "TABKEY": "tab1",
                "txtStart": start.isoformat(),
                "txtEnd": end.isoformat(),
                "jjlb": "ETF",
                "random": str(random.random()),
            },
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.szse.cn/market/fund/volume/etf/index.html",
            },
            timeout=30,
        )
        response.raise_for_status()
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows = []
        for xml_row in root.findall(".//x:row", namespace):
            values = {}
            for cell in xml_row.findall("x:c", namespace):
                ref = cell.attrib.get("r", "A1")
                column = "".join(char for char in ref if char.isalpha())
                text = cell.find(".//x:t", namespace)
                values[column] = None if text is None else text.text
            rows.append(values)
        if not rows:
            return pd.DataFrame(columns=["日期", "基金代码", "基金份额"])
        header = rows[0]
        columns = {value: key for key, value in header.items()}
        required = {"日期", "基金代码", "基金规模(份)"}
        if not required.issubset(columns):
            raise ProviderSchemaError(f"SZSE response missing columns: {sorted(required - set(columns))}")
        return pd.DataFrame(
            [
                {
                    "日期": row.get(columns["日期"]),
                    "基金代码": row.get(columns["基金代码"]),
                    "基金份额": row.get(columns["基金规模(份)"]),
                }
                for row in rows[1:]
            ],
            columns=["日期", "基金代码", "基金份额"],
        )

