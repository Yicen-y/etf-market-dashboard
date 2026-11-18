"""Independent, same-basis check for an AkShare/Sina ETF close candidate."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


SKILL = Path.home() / ".codex" / "skills" / "htbr-etf-skill"


def fetch_htbr_closes(symbol: str, start: str, end: str) -> tuple[dict[str, float], bytes]:
    """Fetch exchange closes, explicitly unadjusted; never use fund NAV."""
    executable = Path("D:/Anaconda3/envs/IStock/python.exe")
    python = str(executable) if executable.is_file() else sys.executable
    if not (SKILL / "scripts" / "api_client.py").is_file():
        raise RuntimeError("HTBR_SKILL_UNAVAILABLE")
    environment = os.environ.copy()
    environment["NO_PROXY"] = ",".join(filter(None, (environment.get("NO_PROXY"), "esa.huatai-pb.com")))
    status = subprocess.run([python, str(SKILL / "config.py"), "status"],
                            capture_output=True, timeout=15, env=environment, check=False)
    if status.returncode:
        raise RuntimeError("HTBR_CREDENTIAL_UNAVAILABLE")
    arguments = {"secuCode": symbol, "beginDate": datetime.strptime(start, "%Y%m%d").strftime("%Y-%m-%d"),
                 "endDate": datetime.strptime(end, "%Y%m%d").strftime("%Y-%m-%d"), "adjustingMethod": 3}
    response = subprocess.run([python, str(SKILL / "scripts" / "api_client.py"), "invoke",
                               "fund-daily-quote", json.dumps(arguments)], capture_output=True,
                              timeout=75, env=environment, check=False)
    if response.returncode:
        raise RuntimeError("HTBR_QUOTE_UNAVAILABLE")
    try:
        decoded = response.stdout.decode("utf-8")
    except UnicodeDecodeError:
        decoded = response.stdout.decode("gb18030")
    payload = json.loads(decoded)
    if payload.get("success") is not True or payload.get("meta", {}).get("degraded") or payload.get("error"):
        raise RuntimeError("HTBR_QUOTE_UNAVAILABLE")
    closes = {}
    for quote in payload.get("data", {}).get("quotes", []):
        if quote.get("fundcode") != symbol:
            raise ValueError("HTBR_SYMBOL_MISMATCH")
        day = datetime.strptime(quote["tradingday"], "%Y-%m-%d").strftime("%Y%m%d")
        price = float(quote["closeprice"])
        if not math.isfinite(price) or price <= 0 or day in closes:
            raise ValueError("HTBR_INVALID_QUOTE")
        closes[day] = price
    return closes, response.stdout


def compare_closes(candidate: list[dict], reference: dict[str, float], *, tolerance: float = 0.005) -> list[str]:
    """Require every candidate date and at least five dates to agree in price and return."""
    if len(candidate) < 5 or len({row["tradeDate"] for row in candidate}) != len(candidate):
        return ["INSUFFICIENT_CANDIDATE_HISTORY"]
    if any(row["tradeDate"] not in reference for row in candidate):
        return ["MISSING_INDEPENDENT_QUOTE"]
    pairs = sorted((row["tradeDate"], float(row["closePrice"]), reference[row["tradeDate"]]) for row in candidate)
    for day, price, confirmed in pairs:
        if not math.isfinite(price) or price <= 0 or abs(price / confirmed - 1) > tolerance:
            return [f"INDEPENDENT_PRICE_CONFLICT:{day}"]
    for previous, current in zip(pairs, pairs[1:]):
        if abs(current[1] / previous[1] - current[2] / previous[2]) > tolerance:
            return [f"INDEPENDENT_RETURN_CONFLICT:{current[0]}"]
    return []
