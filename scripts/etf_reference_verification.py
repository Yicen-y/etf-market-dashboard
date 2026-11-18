"""Non-destructive, repeatable ETF close verification against HTBR quotes."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .config import DATA_ROOT, DATABASE_PATH, PRODUCTS
from .etf_corroboration import fetch_htbr_closes
from .snapshot import read_dataset, read_manifest


SCHEMA = """CREATE TABLE IF NOT EXISTS etf_reference_checks (
 product_code TEXT NOT NULL, trade_date TEXT NOT NULL, provider TEXT NOT NULL,
 local_close REAL NOT NULL, reference_close REAL NOT NULL, delta REAL NOT NULL,
 status TEXT NOT NULL, matched_dates INTEGER NOT NULL, raw_path TEXT NOT NULL,
 raw_sha256 TEXT NOT NULL, request_json TEXT NOT NULL, fetched_at TEXT NOT NULL,
 PRIMARY KEY(product_code,trade_date,provider)
);"""


def verified_close(connection, code: str, day: str, close: float) -> bool:
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='etf_reference_checks'").fetchone():
        return False
    row = connection.execute("""SELECT local_close,reference_close,status,matched_dates,raw_path,raw_sha256
        FROM etf_reference_checks WHERE product_code=? AND trade_date=? AND provider='HTBR'""",
        (code,day)).fetchone()
    if not row or row[2] != "PASS" or row[3] < 5 or Decimal(str(row[0])) != Decimal(str(close)):
        return False
    if abs(Decimal(str(row[0]))-Decimal(str(row[1]))) > Decimal("0.0005"):
        return False
    path = Path(row[4])
    return path.is_file() and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest() == row[5]


def verify_codes(database: Path = DATABASE_PATH, data_root: Path = DATA_ROOT,
                 codes: tuple[str, ...] = tuple(PRODUCTS), *, fetcher=fetch_htbr_closes) -> dict:
    manifest = read_manifest(data_root)
    snapshot = read_dataset(data_root,manifest,"etf")
    result = {}
    with sqlite3.connect(database) as connection:
        connection.executescript(SCHEMA)
        for number,code in enumerate(codes):
            if number:
                time.sleep(3)
            if code not in PRODUCTS:
                raise ValueError(f"unknown ETF code: {code}")
            local = sorted((row for row in snapshot["flatRecords"] if row["productCode"] == code),
                           key=lambda row: row["tradeDate"])[-7:]
            if len(local) < 5:
                result[code] = {"status":"INSUFFICIENT_LOCAL_HISTORY"}
                continue
            start,end = local[0]["tradeDate"],local[-1]["tradeDate"]
            try:
                quotes,raw = fetcher(code,start,end)
                if not raw or any(row["tradeDate"] not in quotes for row in local):
                    result[code] = {"status":"NO_REFERENCE"}
                    continue
                if len(quotes) < 5:
                    result[code] = {"status":"INSUFFICIENT_REFERENCE_HISTORY"}
                    continue
                digest = hashlib.sha256(raw).hexdigest()
                archive = data_root / "verification" / "etf-reference" / f"{digest}.json"
                archive.parent.mkdir(parents=True,exist_ok=True)
                if not archive.exists():
                    archive.write_bytes(raw)
                if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
                    raise ValueError("ETF reference archive hash mismatch")
                deltas = {row["tradeDate"]: abs(Decimal(str(row["closePrice"]))
                            - Decimal(str(quotes[row["tradeDate"]]))) for row in local}
                all_match = all(delta <= Decimal("0.0005") for delta in deltas.values())
                status = "PASS" if all_match else "MISMATCH"
                fetched_at = datetime.now(timezone.utc).isoformat()
                request = json.dumps({"secuCode":code,"beginDate":start,"endDate":end,
                                      "adjustingMethod":3,"upstream":"RAGAPI.FundsPerformanceHis"},sort_keys=True)
                connection.executemany("""INSERT INTO etf_reference_checks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(product_code,trade_date,provider) DO UPDATE SET
                    local_close=excluded.local_close,reference_close=excluded.reference_close,
                    delta=excluded.delta,status=excluded.status,matched_dates=excluded.matched_dates,
                    raw_path=excluded.raw_path,raw_sha256=excluded.raw_sha256,
                    request_json=excluded.request_json,fetched_at=excluded.fetched_at""",
                    [(code,row["tradeDate"],"HTBR",row["closePrice"],quotes[row["tradeDate"]],
                      float(deltas[row["tradeDate"]]),status,
                      len(local),str(archive),digest,request,fetched_at) for row in local])
                connection.commit()
                result[code] = {"status":status,"matched_dates":len(local),"latest_date":end,
                                "latest_delta":float(deltas[end]),"raw_sha256":digest}
            except (RuntimeError,ValueError,OSError) as error:
                result[code] = {"status":"SOURCE_UNAVAILABLE","error_type":type(error).__name__}
    return result


if __name__ == "__main__":
    print(json.dumps(verify_codes(),ensure_ascii=False))
