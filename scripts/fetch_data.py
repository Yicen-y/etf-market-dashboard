from datetime import date
import akshare as ak
from datetime import datetime, timedelta
import os
import time


def _disable_process_proxy() -> None:
    # Eastmoney rejects the local proxy connection in some Windows setups.
    # Limit this to the update process; system/browser proxy settings remain unchanged.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def fetch_product_history(product_code: str, start_date: str, end_date: str, api_key=None) -> list[dict]:
    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    records = []
    cursor = start
    _disable_process_proxy()
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=365), end)
        frame = None
        last_error = None
        for attempt in range(3):
            try:
                frame = ak.fund_etf_hist_em(symbol=product_code, period="daily", start_date=cursor.strftime("%Y%m%d"), end_date=chunk_end.strftime("%Y%m%d"), adjust="")
                break
            except Exception as error:
                last_error = error
                if attempt < 2:
                    time.sleep(2 ** attempt)
        if frame is None:
            raise RuntimeError(f"AkShare request failed for {product_code} ({cursor} - {chunk_end}): {last_error}") from last_error
        if not frame.empty:
            if not {"日期", "收盘"}.issubset(frame.columns):
                raise RuntimeError(f"AkShare response for {product_code} is missing required columns")
            records.extend({"tradeDate": str(row["日期"]).replace("-", ""), "productCode": product_code, "closePrice": float(row["收盘"])} for _, row in frame.iterrows())
        cursor = chunk_end + timedelta(days=1)
    return records


def current_end_date() -> str:
    return date.today().strftime("%Y%m%d")

