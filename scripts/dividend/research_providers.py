"""Wind MCP adapters for the dividend research series."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import math
import os

from scripts.wind_mcp_client import WindMcpClient
from scripts.wind_credentials import get_authorization

INDEX_ENDPOINT = "https://mcp.wind.com.cn/vserver_index_data/mcp/"
ECONOMIC_ENDPOINT = "https://mcp.wind.com.cn/vserver_economic_data/mcp/"
CSI_YIELD_URL = "https://www.wind.com.cn/"
CN10Y_CODE = "S0059749"
CHINABOND_URL = "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery"


def _day(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return datetime.strptime(str(value).replace("-", "")[:8], "%Y%m%d").strftime("%Y%m%d")


def _positive_number(value, field: str, day: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} missing or invalid on {day}") from None
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{field} missing or invalid on {day}")
    return result


def _call(endpoint: str, tool: str, arguments: dict) -> dict:
    authorization = get_authorization()
    if not authorization:
        raise RuntimeError("Wind MCP credential is not configured; run python -m scripts.wind_credentials set")
    with WindMcpClient(endpoint, authorization, timeout=60) as client:
        client.initialize()
        result = client.call_tool(tool, arguments)
    text = next((item.get("text") for item in result.get("content", []) if item.get("type") == "text"), None)
    if not text:
        raise ValueError("Wind MCP response has no text content")
    return json.loads(text)


def fetch_csi_dividend_yield2(start_date: str | None = None, end_date: str | None = None):
    """Fetch Wind's historical CSI 000922 dividend-yield series in 90-day chunks."""
    start = start_date or "20080526"
    end = end_date or datetime.now().strftime("%Y%m%d")
    cursor = datetime.strptime(start, "%Y%m%d").date()
    finish = datetime.strptime(end, "%Y%m%d").date()
    rows, raw_chunks = [], []
    while cursor <= finish:
        chunk_end = min(cursor + timedelta(days=89), finish)
        question = f"查询中证红利指数（000922.CSI）在{cursor:%Y-%m-%d}至{chunk_end:%Y-%m-%d}期间的历史股息率，返回日期和股息率"
        payload = _call(INDEX_ENDPOINT, "get_index_fundamentals", {"question": question})
        raw_chunks.append(payload)
        table = payload["data"]["data"][0]
        for row in table.get("rows", []):
            day = _day(row[-1])
            if start <= day <= end:
                rows.append({"tradeDate": day, "value": _positive_number(row[-2], "Wind股息率", day)})
        cursor = chunk_end + timedelta(days=1)
    deduped = {row["tradeDate"]: row for row in rows}
    rows = [deduped[day] for day in sorted(deduped)]
    if not rows:
        raise ValueError("Wind CSI dividend-yield series is empty")
    metadata = {"provider": "Wind", "upstream": "Wind/CSI", "sourceUrl": CSI_YIELD_URL,
                "indexCode": "000922", "indexName": "中证红利", "metric": "dividend_yield",
                "unit": "%", "historyMode": "wind_mcp_incremental"}
    return rows, metadata, json.dumps(raw_chunks, ensure_ascii=False).encode("utf-8")


def fetch_chinabond_10y_yield(start_date: str, end_date: str):
    """Fetch the Wind EDB ChinaBond 10Y maturity series."""
    if end_date < start_date:
        raise ValueError("end_date must not precede start_date")
    payload = _call(ECONOMIC_ENDPOINT, "query_economic_indicator_data",
                    {"question": CN10Y_CODE, "beginDate": f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}",
                     "endDate": f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"})
    metric = payload["metrics"][0]
    rows = []
    for day, value in zip(metric.get("date", []), metric.get("value", [])):
        trade_date = _day(day)
        if start_date <= trade_date <= end_date:
            rows.append({"tradeDate": trade_date, "value": _positive_number(value, "CN10Y", trade_date)})
    if not rows:
        raise ValueError("Wind ChinaBond 10Y series is empty")
    metadata = {"provider": "Wind", "upstream": "Wind/ChinaBond", "sourceUrl": CHINABOND_URL,
                "curve": "中债国债到期收益率:10年", "tenor": "10Y", "unit": "%", "metricCode": CN10Y_CODE}
    return rows, metadata, json.dumps(payload, ensure_ascii=False).encode("utf-8")
