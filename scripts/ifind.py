"""iFinD HTTP adapter for index history.

The refresh token is kept in Windows Credential Manager (or IFIND_REFRESH_TOKEN).
Fetched rows are candidates; this module never publishes a dashboard snapshot.
"""
from __future__ import annotations

import json
import math
import argparse
import re
import sys
from datetime import datetime

import requests

from .credential_settings import get_credential
from .config import INDEXES
from .fetch_data import FetchResult

BASE_URL = "https://quantapi.51ifind.com/api/v1"


def _post(path: str, *, headers: dict, payload: dict | None = None, session=None):
    client = session or requests
    response = client.post(f"{BASE_URL}/{path}", headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("errorcode", data.get("errorCode", 0)) != 0:
        raise RuntimeError("iFinD request failed")
    return data, response.content


def access_token(refresh_token: str | None = None, *, session=None) -> str:
    secret = refresh_token or get_credential("ifind")
    if not secret:
        raise RuntimeError("iFinD refresh token is not configured")
    response, _ = _post("get_access_token", headers={"Content-Type": "application/json", "refresh_token": secret}, session=session)
    token_data = response.get("data")
    token = token_data.get("access_token") if isinstance(token_data, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("iFinD access token response is invalid")
    return token


def _points(payload: dict, code: str, start: str, end: str) -> list[tuple[str, float]]:
    tables = payload.get("tables")
    if not isinstance(tables, list):
        raise ValueError("iFinD history response is missing tables")
    result = []
    seen = set()
    for entry in tables:
        if not isinstance(entry, dict) or str(entry.get("thscode", "")).upper() != code.upper():
            raise ValueError("iFinD history response has an unexpected security code")
        table = entry.get("table")
        dates = entry.get("time")
        values = table.get("close") if isinstance(table, dict) else None
        if not isinstance(dates, list) or not isinstance(values, list) or len(dates) != len(values):
            raise ValueError("iFinD history response has invalid time/close columns")
        for raw_day, raw_value in zip(dates, values):
            day = str(raw_day).replace("-", "")[:8]
            if len(day) != 8 or not day.isdigit() or not start <= day <= end or day in seen:
                raise ValueError("iFinD history response has an invalid or duplicate date")
            value = float(raw_value)
            if not math.isfinite(value) or value <= 0:
                raise ValueError("iFinD history response has an invalid close")
            seen.add(day)
            result.append((day, value))
    return sorted(result)


def _history(code: str, start: str, end: str, *, session=None, refresh_token=None) -> tuple[list[tuple[str, float]], bytes, dict]:
    token = access_token(refresh_token, session=session)
    body = {"codes": code, "indicators": "close",
            "startdate": datetime.strptime(start, "%Y%m%d").strftime("%Y-%m-%d"),
            "enddate": datetime.strptime(end, "%Y%m%d").strftime("%Y-%m-%d"),
            "functionpara": {"Interval": "D", "CPS": "no", "Fill": "Omit"}}
    payload, raw = _post("cmd_history_quotation", headers={"Content-Type": "application/json", "access_token": token, "ifindlang": "cn"}, payload=body, session=session)
    return _points(payload, code, start, end), raw, body


def fetch_index_history(index_code: str, ifind_code: str, start_date: str, end_date: str,
                        *, session=None, refresh_token: str | None = None) -> FetchResult:
    """Fetch index close candidates using an explicitly verified iFinD symbol.

    No implicit code mapping or total-return claim is made by this adapter.
    """
    if index_code not in INDEXES or not re.fullmatch(r"[A-Za-z0-9]+\.[A-Za-z0-9]+", ifind_code):
        raise ValueError("known local index and explicit iFinD symbol are required")
    start = datetime.strptime(start_date, "%Y%m%d").strftime("%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d").strftime("%Y%m%d")
    if start > end:
        raise ValueError("invalid date range")
    points, raw, body = _history(ifind_code, start, end, session=session, refresh_token=refresh_token)
    rows = [{"tradeDate": day, "indexCode": index_code, "closeValue": value} for day, value in points]
    return FetchResult(rows, "iFinD", "Tonghuashun",
                       {**body, "local_index_code": index_code, "return_type": "UNKNOWN"},
                       raw_bytes=raw, source_url=f"{BASE_URL}/cmd_history_quotation",
                       price_basis="INDEX_CLOSE_UNVERIFIED_RETURN_TYPE")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fetch iFinD history candidates without publishing them")
    subparsers = parser.add_subparsers(dest="kind", required=True)
    index = subparsers.add_parser("index")
    index.add_argument("index_code", help="local dashboard index code")
    index.add_argument("ifind_code", help="verified iFinD code, including exchange suffix")
    index.add_argument("start", help="YYYYMMDD")
    index.add_argument("end", help="YYYYMMDD")
    args = parser.parse_args(argv)
    result = fetch_index_history(args.index_code, args.ifind_code, args.start, args.end)
    json.dump({"provider": result.provider, "priceBasis": result.price_basis,
               "rawSha256": result.raw_sha256, "rows": result.rows}, sys.stdout,
              ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
