"""Read-only before/after guard for the user-approved CNI route release."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from scripts.data_center import build_data_center
from scripts.index_verification import gate_index_candidates
from scripts.snapshot import read_dataset, read_manifest


def rows(path: Path, query: str):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        return connection.execute(query).fetchall()


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(before: Path, after: Path) -> dict:
    before_manifest = read_manifest(before)
    after_manifest = read_manifest(after)
    before_db = before / "etf_market.db"
    after_db = after / "etf_market.db"
    etf_sql = "SELECT * FROM etf_prices ORDER BY trade_date,product_code"
    index_sql = "SELECT * FROM index_prices ORDER BY trade_date,index_code"
    old_etf = rows(before_db, etf_sql)
    new_etf = rows(after_db, etf_sql)
    old_index = {(r[0], r[1]): r for r in rows(before_db, index_sql)}
    new_index = {(r[0], r[1]): r for r in rows(after_db, index_sql)}
    added = [list(new_index[key]) for key in sorted(new_index.keys() - old_index.keys())]
    removed = [list(old_index[key]) for key in sorted(old_index.keys() - new_index.keys())]
    revised = [{"before": old_index[key], "after": new_index[key]} for key in sorted(old_index.keys() & new_index.keys())
               if old_index[key] != new_index[key]]
    index_payload = read_dataset(after, after_manifest, "index")
    etf_payload = read_dataset(after, after_manifest, "etf")
    center = build_data_center(after, after_db)
    cni = {}
    for code in ("480080", "480081"):
        local = max((row for row in index_payload["flatRecords"] if row["indexCode"] == code),
                    key=lambda row: row["tradeDate"])
        series = next(item for item in center["series"] if item["id"] == f"index:{code}")
        cni[code] = {"latest": local, "quality": series["current_quality_status"],
                     "identity": series["identity_status"], "published_date": series["published_date"],
                     "gate": gate_index_candidates(after_db, [local])}
    old_files = {key: sha(before / before_manifest["files"][key]) for key in ("etf", "index")}
    old_immutable = all((after / before_manifest["files"][key]).is_file() and
                        sha(after / before_manifest["files"][key]) == old_files[key] for key in old_files)
    result = {"before_snapshot": before_manifest["snapshot_id"],
              "after_snapshot": after_manifest["snapshot_id"],
              "etf_business_rows_unchanged": old_etf == new_etf,
              "etf_rows": len(new_etf), "index_rows_before": len(old_index),
              "index_rows_after": len(new_index), "index_added": added,
              "index_removed": removed, "index_revised": revised,
              "cni": cni, "old_release_files_unchanged": old_immutable,
              "snapshot_database_consistency": center["snapshot_database_consistency"],
              "strategies": center["strategy_calculations"],
              "etf_flat_record_count": len(etf_payload["flatRecords"]),
              "after_manifest_sha256": sha(after / "current_manifest.json"),
              "after_json_sha256": {key: sha(after / after_manifest["files"][key])
                                    for key in ("etf", "index")}}
    result["pass"] = (old_etf == new_etf and not removed and not revised and old_immutable and
                      sorted((row[0], row[1]) for row in added) ==
                      [("20261116", "480080"), ("20261116", "480081")] and
                      all(item["quality"] == "PASS" and item["gate"] == [] and
                          item["published_date"] == "20261116" for item in cni.values()) and
                      result["snapshot_database_consistency"] == "MATCH" and
                      all(item["status"] == "MATCH" for item in result["strategies"]))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.before, args.after)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "before": report["before_snapshot"],
                      "after": report["after_snapshot"], "added": report["index_added"],
                      "cni": {code: {key: value for key, value in item.items() if key != "latest"}
                              for code, item in report["cni"].items()}}, ensure_ascii=False))
    if not report["pass"]:
        raise SystemExit(2)
