from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import hashlib
import akshare as ak
import json
import math
import os
import subprocess
import time
from typing import Any, Iterator
from .config import INDEX_START_DATE, PRODUCT_START_DATES
from .credential_settings import get_credential


@dataclass(frozen=True)
class FetchResult:
    """Rows plus immutable provenance for one upstream request.

    The sequence methods retain compatibility with existing callers while new
    code can persist the source metadata and raw response hash.
    """

    rows: list[dict]
    provider: str
    upstream: str
    request: dict[str, Any]
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw_bytes: bytes = b""
    status: str = "success"
    source_url: str | None = None
    fetch_batch_id: str | None = None

    @property
    def raw_sha256(self) -> str | None:
        return hashlib.sha256(self.raw_bytes).hexdigest() if self.raw_bytes else None

    def __iter__(self) -> Iterator[dict]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]


def _frame_bytes(frame) -> bytes:
    return frame.to_json(orient="records", date_format="iso", force_ascii=False).encode("utf-8")


def validate_fetch_result(result: FetchResult, start: date, end: date, expected_trading_days: int | None = None) -> None:
    """Reject an empty response when the requested interval should contain data."""
    if result.status != "success":
        raise ValueError(f"fetch status is {result.status}")
    if result.rows:
        return
    if expected_trading_days is None:
        expected_trading_days = sum(1 for offset in range((end - start).days + 1) if (start + timedelta(days=offset)).weekday() < 5)
    if expected_trading_days > 0:
        raise ValueError(f"empty response for expected trading interval {start}..{end}")


def _result(rows, provider, upstream, request, raw_bytes=b"", source_url=None):
    return FetchResult(rows=list(rows), provider=provider, upstream=upstream, request=request, raw_bytes=raw_bytes, source_url=source_url)


def map_index_frame(frame, index_code: str, provider: str, upstream: str) -> FetchResult:
    """Map index history using named columns; unknown schemas are blocked."""
    date_column = next((name for name in ("日期", "交易日期", "date", "tradeDate", "JYR") if name in frame.columns), None)
    value_column = next((name for name in ("收盘", "收盘价", "close", "closeValue", "CLOSE") if name in frame.columns), None)
    if date_column is None or value_column is None:
        raise ValueError(f"index provider schema is unrecognized for {index_code}: {list(frame.columns)}")
    rows = []
    for _, row in frame.iterrows():
        raw_day = row[date_column]
        day = raw_day.strftime("%Y%m%d") if hasattr(raw_day, "strftime") else str(raw_day).replace("-", "")[:8]
        mapped = {"tradeDate": day, "indexCode": index_code, "closeValue": float(row[value_column])}
        if "数据状态" in frame.columns and row.get("数据状态"):
            mapped["dataStatus"] = row["数据状态"]
        rows.append(mapped)
    return _result(rows, provider, upstream, {"index_code": index_code}, _frame_bytes(frame))


def fetch_exchange_trading_dates(start_date: str, end_date: str) -> list[str]:
    """Return the observed mainland exchange calendar from AkShare/Sina."""
    frame = ak.tool_trade_date_hist_sina()
    if frame is None or frame.empty or "trade_date" not in frame.columns:
        raise RuntimeError("exchange trading calendar is unavailable")
    dates = sorted({value.strftime("%Y%m%d") for value in frame["trade_date"].dropna()})
    return [value for value in dates if start_date <= value <= end_date]


def recover_zero_close_from_next_change(frame, index_code: str):
    """Recover a corrupt CSI zero close from the next published close/change.

    This is an algebraic recovery using two official fields, not interpolation
    or carry-forward.  The source defect seen for H20180 on 2013-06-28 is
    recoverable because the next row publishes both close and absolute change.
    """
    repaired = frame.copy()
    if "数据状态" not in repaired.columns:
        repaired["数据状态"] = None
    required = {"收盘", "涨跌"}
    if not required.issubset(repaired.columns):
        return repaired
    for position in range(len(repaired) - 1):
        close = repaired.iloc[position]["收盘"]
        if close is None or not math.isfinite(float(close)) or float(close) != 0:
            continue
        next_close = repaired.iloc[position + 1]["收盘"]
        next_change = repaired.iloc[position + 1]["涨跌"]
        if next_close is None or next_change is None:
            continue
        if not math.isfinite(float(next_close)) or not math.isfinite(float(next_change)):
            continue
        recovered = round(float(next_close) - float(next_change), 8)
        if recovered <= 0:
            continue
        repaired.iat[position, repaired.columns.get_loc("收盘")] = recovered
        repaired.iat[position, repaired.columns.get_loc("数据状态")] = "RECOVERED_FROM_NEXT_DAY_ABSOLUTE_CHANGE"
    return repaired


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


def _etfirst_command(command: list[str], api_key: str | None) -> list[str]:
    if api_key:
        return command + ["--api-key", api_key]
    configured = get_credential("etfirst")
    return command + (["--api-key", configured] if configured else [])


def fetch_product_history_etfirst(product_code: str, start_date: str, end_date: str, api_key=None) -> FetchResult:
    command = _etfirst_command(["etfirst", "--json", "etf-detail", "all", "--product-code", product_code,
               "--start-date", start_date, "--end-date", end_date], api_key)
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
    result_block = payload.get("results", {}).get("getReturnTrendList")
    if result_block is None:
        raise RuntimeError("ETFirst response schema missing getReturnTrendList")
    rows = result_block.get(product_code, [])
    return _result(
        [{"tradeDate": row["tradeDate"], "productCode": product_code, "closePrice": float(row["closePrice"])} for row in rows],
        "ETFirst", "ETFirst", {"product_code": product_code, "start_date": start_date, "end_date": end_date}, raw,
    )


def fetch_product_history(product_code: str, start_date: str, end_date: str, api_key=None) -> FetchResult:
    _disable_process_proxy()
    # The caller owns the incremental cursor. Discovering inception here would
    # silently turn every fallback refresh into a full-history request.
    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    records = []
    raw_frames = []
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
            try:
                sina = ak.fund_etf_hist_sina(symbol="sh" + product_code)
                if sina is None or not {"date", "close"}.issubset(sina.columns):
                    raise ValueError("Sina ETF response is missing date or close")
                rows = [{"tradeDate": str(row.date).replace("-", "")[:8], "productCode": product_code,
                         "closePrice": float(row.close)} for row in sina.itertuples()
                        if start_date <= str(row.date).replace("-", "")[:8] <= end_date]
                return _result(rows, "AkShare", "Sina", {"product_code": product_code,
                    "start_date": start_date, "end_date": end_date, "eastmoney_error": str(last_error)},
                    _frame_bytes(sina), "https://finance.sina.com.cn")
            except Exception as sina_error:
                raise RuntimeError(f"AkShare ETF history failed for {product_code}: Eastmoney: {last_error}; Sina: {sina_error}") from sina_error
        if not frame.empty:
            if not {"日期", "收盘"}.issubset(frame.columns):
                raise RuntimeError(f"AkShare response for {product_code} is missing required columns")
            records.extend({"tradeDate": str(row["日期"]).replace("-", ""), "productCode": product_code, "closePrice": float(row["收盘"])} for _, row in frame.iterrows())
            raw_frames.append(frame)
        cursor = chunk_end + timedelta(days=1)
    raw = b"\n".join(_frame_bytes(frame) for frame in raw_frames)
    return _result(records, "AkShare", "Eastmoney", {"product_code": product_code, "start_date": start_date, "end_date": end_date}, raw, "https://akshare.akfamily.xyz")


def fetch_index_history_etfirst(index_code: str, start_date: str, end_date: str, api_key=None) -> FetchResult:
    command = _etfirst_command(["etfirst", "--json", "index-detail", "all", "--index-code", index_code,
               "--start-date", start_date, "--end-date", end_date], api_key)
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
    if "results" not in payload or "list" not in payload.get("results", {}):
        raise RuntimeError("ETFirst index response schema missing results.list")
    if not rows:
        return _result([], "ETFirst", "ETFirst", {"index_code": index_code, "start_date": start_date, "end_date": end_date}, raw)
    return _result([{ "tradeDate": row["JYR"], "indexCode": index_code, "closeValue": float(row["CLOSE"]) } for row in rows], "ETFirst", "ETFirst", {"index_code": index_code, "start_date": start_date, "end_date": end_date}, raw)


def fetch_index_history(index_code: str, start_date: str, end_date: str, api_key=None) -> FetchResult:
    """AkShare's CNI endpoint supplies the 480080/480081 total-return histories."""
    _disable_process_proxy()
    request = {"index_code": index_code, "start_date": start_date, "end_date": end_date}
    try:
        frame = ak.index_hist_cni(symbol=index_code, start_date=start_date, end_date=end_date)
    except ValueError as error:
        # AkShare raises this pandas error when CNI returns no rows for a range
        # whose latest close has not been published yet.
        if "Length mismatch" not in str(error):
            raise
        return _result([], "AkShare", "CNI", request)
    if frame is None or frame.empty:
        return _result([], "AkShare", "CNI", request)
    return map_index_frame(frame, index_code, "AkShare", "CNI")


def fetch_csi_total_return_history(index_code: str, start_date: str, end_date: str, api_key=None) -> FetchResult:
    _disable_process_proxy()
    upstream_end = (datetime.strptime(end_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    for attempt in range(3):
        try:
            frame = ak.stock_zh_index_hist_csindex(symbol=index_code, start_date=start_date, end_date=upstream_end)
            if frame is None or frame.empty:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                return _result([], "AkShare", "CSI", {"index_code": index_code, "start_date": start_date, "end_date": end_date})
            if "日期" in frame.columns:
                frame = frame[
                    frame["日期"].map(lambda value: value.strftime("%Y%m%d") if hasattr(value, "strftime") else str(value).replace("-", "")[:8]) <= end_date
                ].reset_index(drop=True)
            frame = recover_zero_close_from_next_change(frame, index_code)
            return map_index_frame(frame, index_code, "AkShare", "CSI")
        except ValueError as error:
            # AkShare currently raises this when the upstream endpoint returns
            # an empty response and then tries to assign the normal columns.
            if "Length mismatch" not in str(error):
                raise
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return _result([], "AkShare", "CSI", {"index_code": index_code, "start_date": start_date, "end_date": end_date})
    return _result([], "AkShare", "CSI", {"index_code": index_code, "start_date": start_date, "end_date": end_date})


def current_end_date() -> str:
    return date.today().strftime("%Y%m%d")

