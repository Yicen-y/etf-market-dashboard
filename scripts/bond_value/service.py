from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta

import pandas as pd

from scripts.config import ROOT
from scripts.wind_credentials import get_authorization
from scripts.wind_mcp_client import WindMcpClient
from .metrics import build_rows


DATA_FILE = ROOT / "data" / "research" / "bond_value_hs300.json"
INDEX_ENDPOINT = "https://mcp.wind.com.cn/vserver_index_data/mcp/"


def _mcp_call(endpoint, name, arguments):
    auth = get_authorization()
    if not auth:
        raise RuntimeError("未配置 Wind MCP 授权")
    endpoint_env = "WIND_INDEX_MCP_URL" if "vserver_index_data" in endpoint else "WIND_MCP_URL"
    with WindMcpClient(os.environ.get(endpoint_env, endpoint), auth, timeout=60) as client:
        client.initialize()
        result = client.call_tool(name, arguments)
    content = result.get("content", [])
    text = next((item.get("text") for item in content if isinstance(item, dict) and item.get("text")), None)
    if not text:
        raise RuntimeError(f"Wind MCP {name}未返回文本数据")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Wind MCP {name}返回格式无法识别") from exc


def _rows(payload):
    if isinstance(payload, dict):
        if isinstance(payload.get("rows"), list):
            return payload.get("columns", []), payload["rows"]
        data = payload.get("data")
        if isinstance(data, dict):
            if isinstance(data.get("rows"), list) and data["rows"]:
                return data.get("columns", []), data["rows"]
            nested = data.get("data")
            if isinstance(nested, list) and nested and isinstance(nested[0], dict):
                populated = next((table for table in nested if table.get("rows")), nested[0])
                return populated.get("columns", []), populated.get("rows", [])
            if isinstance(data.get("rows"), list):
                return data.get("columns", []), data["rows"]
    return [], []


def _column_index(columns, tokens):
    names = [str(col.get("name", col) if isinstance(col, dict) else col).lower() for col in columns]
    return next((i for i, name in enumerate(names) if any(token in name for token in tokens)), None)


def _as_date(value):
    match = re.search(r"\d{4}[-/]?\d{2}[-/]?\d{2}", str(value))
    if not match:
        return None
    return match.group(0).replace("-", "").replace("/", "")


def _numeric(value):
    try:
        result = float(value)
        return result if pd.notna(result) else None
    except (TypeError, ValueError):
        return None


def _fetch_wind_prices(start, end):
    payload = _mcp_call(INDEX_ENDPOINT, "get_index_kline", {
        "windcode": "000300.SH", "begin_date": start, "end_date": end,
        "period": "10", "count": 0,
    })
    columns, rows = _rows(payload)
    date_i = _column_index(columns, ("time", "date"))
    close_i = _column_index(columns, ("match", "close"))
    if date_i is None or close_i is None:
        raise RuntimeError("Wind沪深300日线缺少日期或收盘点位字段")
    return [{"tradeDate": day, "closeValue": _numeric(row[close_i])}
            for row in rows if len(row) > max(date_i, close_i) and (day := _as_date(row[date_i]))]


def _fetch_wind_valuations(start, end):
    payload = _mcp_call(INDEX_ENDPOINT, "get_index_fundamentals", {
        "question": f"查询沪深300（000300.SH）在{start}至{end}期间每日PE TTM、PB历史时间序列，返回日期、PE TTM、PB",
    })
    columns, rows = _rows(payload)
    date_i = _column_index(columns, ("日期", "date", "时间"))
    pe_i = _column_index(columns, ("pe_ttm", "pe ttm", "ttm pe", "市盈率ttm", "市盈率", "pe"))
    pb_i = _column_index(columns, ("pb", "市净率"))
    if date_i is None or pe_i is None or pb_i is None:
        raise RuntimeError("Wind沪深300估值历史缺少日期、PE或PB字段")
    return [{"tradeDate": day, "pe": _numeric(row[pe_i]), "pb": _numeric(row[pb_i])}
            for row in rows if len(row) > max(date_i, pe_i, pb_i) and (day := _as_date(row[date_i]))]


def _fetch_wind_latest_roe(end):
    try:
        payload = _mcp_call(INDEX_ENDPOINT, "get_index_fundamentals", {
            "question": f"查询沪深300（000300.SH）截至{end}最新ROE，返回指标值和数据日期",
        })
        columns, rows = _rows(payload)
        roe_i = _column_index(columns, ("roe", "净资产收益率"))
        if roe_i is None or not rows:
            return {}
        value = _numeric(rows[0][roe_i])
        date_i = _column_index(columns, ("日期", "date", "时间"))
        day = _as_date(rows[0][date_i]) if date_i is not None else end.replace("-", "")
        return {day: value} if day and value else {}
    except Exception:
        return {}


def _fetch_bond_yields(start, end):
    import akshare as ak

    begin = date.fromisoformat(start)
    finish = date.fromisoformat(end)
    rows = []
    cursor = begin
    while cursor <= finish:
        chunk_end = min(cursor + timedelta(days=350), finish)
        frame = ak.bond_china_yield(cursor.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d"))
        curve_col = next((c for c in frame.columns if "曲线名称" in str(c)), None)
        date_col = next((c for c in frame.columns if "日期" in str(c)), None)
        yield_col = next((c for c in frame.columns if "10年" in str(c) or "10Y" in str(c).upper()), None)
        if curve_col is None or date_col is None or yield_col is None:
            raise RuntimeError("AkShare中债收益率结果缺少曲线名称、日期或10年期字段")
        sovereign = frame[frame[curve_col].astype(str).str.contains("中债国债收益率曲线", regex=False)]
        for raw_day, value in zip(sovereign[date_col], sovereign[yield_col]):
            day = _as_date(raw_day)
            if day:
                rows.append({"tradeDate": day, "yieldPct": _numeric(value)})
        cursor = chunk_end + timedelta(days=1)
    return rows


def load_payload():
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "EMPTY", "rows": [], "sources": {}, "coverage": {}}


def _date_chunks(start, end, max_days=89):
    cursor, finish = date.fromisoformat(start), date.fromisoformat(end)
    while cursor <= finish:
        chunk_end = min(cursor + timedelta(days=max_days), finish)
        yield cursor.isoformat(), chunk_end.isoformat()
        cursor = chunk_end + timedelta(days=1)


def _merge_by_date(existing, updates, key):
    result = {str(row["tradeDate"]): row for row in existing}
    result.update({str(row["tradeDate"]): row for row in updates})
    return [result[day] for day in sorted(result)]


def refresh(start="2010-01-04", end=None):
    end = end or date.today().isoformat()
    old_payload = load_payload()
    old_rows = old_payload.get("rows", [])
    prices = [{"tradeDate": row["tradeDate"], "closeValue": row.get("close")}
              for row in old_rows if row.get("close") is not None]
    valuations = [{"tradeDate": row["tradeDate"], "pe": row.get("pe"), "pb": row.get("pb")}
                  for row in old_rows if row.get("pe") is not None and row.get("pb") is not None]
    yields = {}
    roe = {row["tradeDate"]: row["roePct"] for row in old_rows
           if row.get("roeSource") == "WIND" and row.get("roePct") is not None}
    for row in old_rows:
        if row.get("bondYieldDate") and row.get("bondYieldPct") is not None:
            yields[row["bondYieldDate"]] = {"tradeDate": row["bondYieldDate"], "yieldPct": row["bondYieldPct"]}

    cached_dates = {row["tradeDate"] for row in prices}
    if not cached_dates:
        price_start = start
    else:
        latest_cached_day = max(cached_dates)
        last_cached = date.fromisoformat(f"{latest_cached_day[:4]}-{latest_cached_day[4:6]}-{latest_cached_day[6:]}")
        price_start = max(date.fromisoformat(start), last_cached - timedelta(days=7)).isoformat()
    new_prices = []
    for a, b in _date_chunks(price_start, end):
        new_prices.extend(_fetch_wind_prices(a, b))
    prices = _merge_by_date(prices, new_prices, "tradeDate")

    valuation_dates = {row["tradeDate"] for row in valuations}
    price_dates = [row["tradeDate"] for row in prices if start.replace("-", "") <= row["tradeDate"] <= end.replace("-", "")]
    missing_dates = [day for day in price_dates if day not in valuation_dates]
    missing_set = set(missing_dates)
    for a, b in _date_chunks(start, end):
        if any(a.replace("-", "") <= day <= b.replace("-", "") for day in missing_set):
            valuations = _merge_by_date(valuations, _fetch_wind_valuations(a, b), "tradeDate")

    old_yield_dates = sorted(yields)
    if not old_yield_dates:
        bond_start = start
    else:
        last_yield = old_yield_dates[-1]
        bond_date = date.fromisoformat(f"{last_yield[:4]}-{last_yield[4:6]}-{last_yield[6:]}")
        bond_start = max(date.fromisoformat(start), bond_date - timedelta(days=7)).isoformat()
    new_yields = []
    for a, b in _date_chunks(bond_start, end, max_days=350):
        new_yields.extend(_fetch_bond_yields(a, b))
    for row in new_yields:
        yields[row["tradeDate"]] = row

    roe.update(_fetch_wind_latest_roe(end))
    bonds = [yields[day] for day in sorted(yields)]
    rows = build_rows(prices, valuations, bonds, roe)
    if not rows:
        raise RuntimeError("Wind未返回沪深300有效历史记录")
    valid_valuation_count = sum(row["pe"] is not None and row["pb"] is not None for row in rows)
    valuation_coverage_pct = round(valid_valuation_count / len(rows) * 100, 2)
    if valuation_coverage_pct < 60:
        raise RuntimeError(f"Wind PE/PB日期覆盖率仅{valuation_coverage_pct}%，低于60%；已保留上次快照")
    payload = {
        "status": "READY", "updatedAt": date.today().isoformat(), "rows": rows,
        "sources": {"index": "Wind MCP / 000300.SH", "valuation": "Wind MCP / 指数成分加权口径",
                    "bond": "AkShare / 中债国债收益率曲线10年到期收益率"},
        "coverage": {"start": rows[0]["tradeDate"], "end": rows[-1]["tradeDate"], "count": len(rows),
                     "valuationCount": valid_valuation_count, "valuationCoveragePct": valuation_coverage_pct},
        "roeNote": "历史ROE为PE/PB推导的隐含ROE；Wind直接ROE仅在其有效数据日优先采用。",
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = DATA_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    os.replace(temp, DATA_FILE)
    return payload
