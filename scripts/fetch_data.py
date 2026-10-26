import json
import os
import subprocess
from datetime import date
from typing import Optional


def fetch_product_history(product_code: str, start_date: str, end_date: str, api_key: Optional[str] = None) -> list[dict]:
    env = os.environ.copy()
    if api_key:
        env["ETFIRST_API_KEY"] = api_key
    command = ["etfirst", "--json", "etf-detail", "all", "--product-code", product_code,
               "--start-date", start_date, "--end-date", end_date]
    result = subprocess.run(command, capture_output=True, text=False, env=env, check=False)
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(error or f"etfirst failed for {product_code}")
    raw = result.stdout or b""
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        payload = json.loads(raw.decode("gb18030"))
    rows = payload.get("results", {}).get("getReturnTrendList", {}).get(product_code, [])
    return [{"tradeDate": row["tradeDate"], "productCode": product_code, "closePrice": float(row["closePrice"])} for row in rows]


def current_end_date() -> str:
    return date.today().strftime("%Y%m%d")

