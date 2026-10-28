from datetime import date
import akshare as ak
from datetime import datetime, timedelta
import json
import os
import subprocess
import time
from .config import INDEX_START_DATE, PRODUCT_START_DATES


def _disable_process_proxy() -> None:
    # Eastmoney rejects the local proxy connection in some Windows setups.
    # Limit this to the update process; system/browser proxy settings remain unchanged.
    if os.getenv("ETF_DIRECT") != "1":
        return
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def discover_start_date(product_code: str, end_date: str) -> str:
    """Use the earliest available fund net-value date as an automatic start date."""
    try:
        info = ak.fund_etf_fund_info_em(fund=product_code, start_date="20000101", end_date=end_date)
        if info is not None and not info.empty and "净值日期" in info.columns:
            earliest = info["净值日期"].dropna().min()
            if earliest is not None:
                return earliest.strftime("%Y%m%d")
    except Exception:
        pass
    return PRODUCT_START_DATES.get(product_code, "20130101")


def fetch_product_history_etfirst(product_code: str, start_date: str, end_date: str) -> list[dict]:
    command = ["etfirst", "--json", "etf-detail", "all", "--product-code", product_code,
               "--start-date", start_date, "--end-date", end_date]
    result = subprocess.run(command, capture_output=True, text=False, check=False)
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(error or "ETFirst request failed")
    raw = result.stdout or b""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gb18030")
    payload = json.loads(text)
    rows = payload.get("results", {}).get("getReturnTrendList", {}).get(product_code, [])
    return [{"tradeDate": row["tradeDate"], "productCode": product_code, "closePrice": float(row["closePrice"])} for row in rows]


def fetch_product_history(product_code: str, start_date: str, end_date: str, api_key=None) -> list[dict]:
    _disable_process_proxy()
    discovered = discover_start_date(product_code, end_date)
    start = datetime.strptime(discovered, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    records = []
    cursor = start
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


def fetch_index_history_etfirst(index_code: str, start_date: str, end_date: str) -> list[dict]:
    command = ["etfirst", "--json", "index-detail", "all", "--index-code", index_code,
               "--start-date", start_date, "--end-date", end_date]
    result = subprocess.run(command, capture_output=True, text=False, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or "ETFirst request failed")
    raw = result.stdout or b""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gb18030")
    payload = json.loads(text)
    rows = payload.get("results", {}).get("list", [])
    if not rows:
        raise RuntimeError(f"ETFirst returned no historical index points for {index_code}")
    return [{"tradeDate": row["JYR"], "indexCode": index_code, "closeValue": float(row["CLOSE"])} for row in rows]


def fetch_index_history(index_code: str, start_date: str, end_date: str, api_key=None) -> list[dict]:
    """AkShare's CNI endpoint supplies the 480080/480081 total-return histories."""
    _disable_process_proxy()
    frame = ak.index_hist_cni(symbol=index_code, start_date=start_date, end_date=end_date)
    if frame is None or frame.empty:
        return []
    # AkShare may decode the Chinese column labels differently on Windows;
    # CNI's stable column order is date, open, high, low, close.
    return [{"tradeDate": row.iloc[0].strftime("%Y%m%d"), "indexCode": index_code, "closeValue": float(row.iloc[4])}
            for _, row in frame.iterrows()]


def fetch_csi_total_return_history(index_code: str, start_date: str, end_date: str, api_key=None) -> list[dict]:
    _disable_process_proxy()
    frame = ak.stock_zh_index_hist_csindex(symbol=index_code, start_date=start_date, end_date=end_date)
    if frame is None or frame.empty:
        return []
    return [{"tradeDate": row.iloc[0].strftime("%Y%m%d"), "indexCode": index_code, "closeValue": float(row.iloc[9])}
            for _, row in frame.iterrows()]


def current_end_date() -> str:
    return date.today().strftime("%Y%m%d")

