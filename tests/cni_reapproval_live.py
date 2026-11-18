"""Fetch and compare CNI direct/AkShare closes in a scratch database only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

from scripts.config import DATA_ROOT, DATABASE_PATH
from scripts.index_verification import collect_cni_route_approvals, gate_index_candidates, verify


ROOT = DATA_ROOT.resolve()
FORMAL = Path(__file__).resolve().parents[1] / "data"
if ROOT == FORMAL.resolve() or ".scratch" not in ROOT.parts:
    raise RuntimeError("live reconciliation requires an isolated scratch copy")
OUT = Path(os.environ["ETF_TEST_EVIDENCE_DIR"])
OUT.mkdir(parents=True, exist_ok=True)
START = os.environ.get("CNI_REAPPROVAL_START", "20261113")
END = os.environ.get("CNI_REAPPROVAL_END", "20261117")


def main():
    results = {}
    for code in ("480080", "480081"):
        failed = verify(DATABASE_PATH, ROOT, [code], "verify-daily",
                        start_date=START, end_date=END, request_delay=0)
        approved = collect_cni_route_approvals(DATABASE_PATH, ROOT, code, START, END) if not failed else []
        with sqlite3.connect(DATABASE_PATH) as connection:
            connection.row_factory = sqlite3.Row
            rows = [dict(row) for row in connection.execute("""SELECT a.index_code,a.trade_date,
                a.official_close,a.akshare_close,a.official_sha256,a.akshare_sha256,
                a.official_batch_id,a.akshare_path,a.checked_at,a.approval_basis,
                b.raw_path AS official_path,b.fetched_at AS official_fetched_at
                FROM index_route_approvals a JOIN index_reference_batches b
                  ON b.batch_id=a.official_batch_id
                WHERE a.index_code=? AND a.trade_date BETWEEN ? AND ? ORDER BY a.trade_date""",
                (code, START, END))]
        checks = [{"trade_date": row["trade_date"], "close_value": row["official_close"],
                   "gate": gate_index_candidates(DATABASE_PATH, [{"indexCode": code,
                       "tradeDate": row["trade_date"], "closeValue": row["official_close"]}])}
                  for row in rows]
        results[code] = {"failed_reference_batches": failed, "approved_dates": approved,
                         "evidence": rows, "gate_checks": checks}
    path = OUT / "live-route-check.json"
    path.write_text(json.dumps({"start": START, "end": END, "indexes": results},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": "PASS" if all(results[c]["approved_dates"] for c in results) else "INCOMPLETE",
                      "approved_dates": {code: item["approved_dates"] for code, item in results.items()},
                      "evidence": str(path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
