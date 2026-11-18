"""Close superseded index reminders without deleting observations or changing prices."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DATA_ROOT, DATABASE_PATH
from .index_verification import gate_index_candidates
from .snapshot import read_dataset, read_manifest


SUPERSEDED = {"SOURCE_TRAILING_UNAVAILABLE", "REFERENCE_GATE_NO_REFERENCE"}


def resolve(database: Path = DATABASE_PATH, data_root: Path = DATA_ROOT, *, apply: bool = False) -> dict:
    manifest = read_manifest(data_root)
    snapshot = read_dataset(data_root, manifest, "index")
    published = {(row["indexCode"], row["tradeDate"]): row["closeValue"]
                 for row in snapshot["flatRecords"]}
    decisions = []
    with sqlite3.connect(database) as db:
        local = {(code,day):value for code,day,value in db.execute(
            "SELECT index_code,trade_date,close_value FROM index_prices")}
        canonical = {(code,day) for code,day in db.execute(
            "SELECT symbol,trade_date FROM canonical_observations WHERE kind='index'")}
        issues = db.execute("""SELECT issue_id,symbol,trade_date,issue_code FROM quality_issues
            WHERE kind='index' AND resolution_status='open' ORDER BY issue_id""").fetchall()
        for issue_id,code,day,kind in issues:
            key = code,day
            if kind in SUPERSEDED and key in local and published.get(key) == local[key]:
                failure = gate_index_candidates(database,[{"indexCode":code,"tradeDate":day,
                                                           "closeValue":local[key]}])
                if not failure:
                    decisions.append((issue_id,"resolved",f"PUBLISHED_REFERENCE:{manifest['snapshot_id']}:{code}:{day}"))
            elif kind == "NON_TRADING_DATE_OBSERVATION" and key not in local and key not in published and key not in canonical:
                decisions.append((issue_id,"excluded",f"SNAPSHOT_EXCLUDED:{manifest['snapshot_id']}:{code}:{day}"))
        if apply and decisions:
            db.executemany("""UPDATE quality_issues SET resolution_status=?,resolution_evidence_id=?
                WHERE issue_id=? AND resolution_status='open'""",
                [(status,evidence,issue_id) for issue_id,status,evidence in decisions])
    return {"eligible":len(decisions),"resolved":sum(status=="resolved" for _,status,_ in decisions),
            "excluded":sum(status=="excluded" for _,status,_ in decisions),"issue_ids":[row[0] for row in decisions],
            "applied":apply}


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true")
    args = parser.parse_args()
    print(json.dumps(resolve(apply=args.apply),ensure_ascii=False))
