"""One-time Wind backfill for the CSI Dividend index yield series."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

import requests

from scripts.config import DATABASE_PATH, ROOT
from scripts.dividend.research_store import record_research_series


URL = "https://mcp.wind.com.cn/vserver_index_data/mcp/"
SERIES_ID = "CSI_DIV_YIELD2_000922"


def _call(question: str, request_id: int) -> dict:
    token = os.environ.get("WIND_MCP_TOKEN")
    if not token:
        raise RuntimeError("WIND_MCP_TOKEN is not set")
    response = requests.post(
        URL,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
        json={"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": "get_index_fundamentals", "arguments": {"question": question}}},
        timeout=60,
    )
    response.raise_for_status()
    line = next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
    envelope = json.loads(line)
    if envelope.get("result", {}).get("isError"):
        raise RuntimeError(envelope["result"].get("structuredContent", {}).get("message") or envelope["result"].get("content", [{}])[0].get("text"))
    text = envelope["result"]["content"][0]["text"]
    payload = json.loads(text)
    return payload["data"]["data"][0]


def fetch(start: str = "20080526", end: str = "20261106") -> tuple[list[dict], bytes]:
    begin = date.fromisoformat(f"{start[:4]}-{start[4:6]}-{start[6:]}")
    finish = date.fromisoformat(f"{end[:4]}-{end[4:6]}-{end[6:]}")
    rows = []
    raw_chunks = []
    request_id = 1
    cursor = begin
    while cursor <= finish:
        chunk_end = min(cursor + timedelta(days=89), finish)
        question = f"查询中证红利指数（000922.CSI）在{cursor:%Y-%m-%d}至{chunk_end:%Y-%m-%d}期间的历史股息率，返回日期和股息率"
        table = _call(question, request_id)
        request_id += 1
        raw_chunks.append(table)
        for row in table.get("rows", []):
            day, value = row[-1], row[-2]
            if value is not None:
                rows.append({"tradeDate": str(day).replace("-", ""), "value": float(value)})
        cursor = chunk_end + timedelta(days=1)
    deduped = {row["tradeDate"]: row for row in rows}
    return [deduped[day] for day in sorted(deduped)], json.dumps(raw_chunks, ensure_ascii=False).encode("utf-8")


def main() -> None:
    rows, raw = fetch()
    digest = hashlib.sha256(raw).hexdigest()
    raw_ref = Path("raw") / "research" / "csi_div_yield2_000922" / f"{digest}.json"
    target = ROOT / "data" / raw_ref
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    inserted = record_research_series(
        DATABASE_PATH,
        SERIES_ID,
        rows,
        {"provider": "Wind", "upstream": "Wind/CSI", "sourceUrl": "https://www.wind.com.cn/", "unit": "%"},
        digest,
        raw_ref.as_posix(),
    )
    print(json.dumps({"rows": len(rows), "inserted": inserted, "first": rows[0], "last": rows[-1], "raw": raw_ref.as_posix()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
