"""Recheck saved reference evidence and published-market immutability offline."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from .config import DATA_ROOT, DATABASE_PATH
from .snapshot import read_manifest, resolve_file


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_summary(database=DATABASE_PATH, data_root=DATA_ROOT):
    verification = data_root / "verification"
    destination = verification / "phase2-summary.json"
    existing = json.loads(destination.read_text(encoding="utf-8")) if destination.exists() else {}
    baseline = verification / "baseline" / "audit.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("ATTACH DATABASE ? AS baseline", (str(baseline),))
        columns = "trade_date,index_code,close_value,source,updated_at"
        added = db.execute(f"SELECT COUNT(*) FROM (SELECT {columns} FROM main.index_prices EXCEPT SELECT {columns} FROM baseline.index_prices)").fetchone()[0]
        removed = db.execute(f"SELECT COUNT(*) FROM (SELECT {columns} FROM baseline.index_prices EXCEPT SELECT {columns} FROM main.index_prices)").fetchone()[0]
        prices_rows = db.execute("SELECT COUNT(*) FROM index_prices").fetchone()[0]
        def price_digest(schema):
            rows = db.execute(f"SELECT {columns} FROM {schema}.index_prices ORDER BY index_code,trade_date").fetchall()
            return hashlib.sha256(json.dumps(rows,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
        current_price_digest = price_digest("main")
        baseline_price_digest = price_digest("baseline")
        reference = db.execute("SELECT batch_id,raw_path,raw_sha256 FROM index_reference_batches WHERE status='FETCHED'").fetchall()
        batch_counts = dict(db.execute("SELECT status,COUNT(*) FROM index_reference_batches GROUP BY status").fetchall())
        http_403_diagnostics = [{"diagnostic_json": diagnostic, "attempts": count}
                                for diagnostic,count in db.execute("SELECT diagnostic_json,COUNT(*) FROM index_reference_failures WHERE json_extract(diagnostic_json,'$.http_status')=403 GROUP BY diagnostic_json")]
    reference_failures = [batch_id for batch_id,path,digest in reference
                          if not path or not Path(path).is_file() or sha256(Path(path)) != digest]
    identity = json.loads((verification / "identity" / "identity-evidence.json").read_text(encoding="utf-8"))
    identity_failures = [code for code,item in identity["indexes"].items()
                         if not Path(item["path"]).is_file() or sha256(Path(item["path"])) != item["sha256"]]
    manifest = read_manifest(data_root)
    paths = (data_root / "current_manifest.json", resolve_file(data_root, manifest["files"]["index"]))
    file_digests = {path.relative_to(data_root.parent).as_posix(): sha256(path) for path in paths}
    original_files = existing.get("file_digests_at_start", {})
    report = json.loads((verification / "verification-report.json").read_text(encoding="utf-8"))
    if "prices_digest_at_start" in existing and "legacy_prices_digest_at_start" not in existing:
        existing["legacy_prices_digest_at_start"] = existing.pop("prices_digest_at_start")
    existing.update({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prices_rows": prices_rows,
        "prices_digest": current_price_digest,
        "baseline_prices_digest": baseline_price_digest,
        "prices_digest_method": "SHA256 compact JSON of index_prices five columns ordered by index_code,trade_date",
        "prices_baseline_added_or_changed": added,
        "prices_baseline_removed_or_changed": removed,
        "prices_unchanged_from_consistent_backup": added == removed == 0 and current_price_digest == baseline_price_digest,
        "file_digests": file_digests,
        "published_files_unchanged_from_start": (
            all(file_digests[key] == value for key, value in original_files.items())
            if set(file_digests) == set(original_files) else None),
        "published_file_baseline_comparison": (
            "COMPARABLE" if set(file_digests) == set(original_files) else "PATH_SET_CHANGED"),
        "reference_batches_hashed": len(reference),
        "reference_batch_statuses": batch_counts,
        "reference_hash_failures": reference_failures,
        "identity_pdfs_hashed": len(identity["indexes"]),
        "identity_hash_failures": identity_failures,
        "indexes": report["indexes"],
        "source_inventory": report["source_inventory"],
        "http_403_diagnostics": http_403_diagnostics,
    })
    destination.write_text(json.dumps(existing,ensure_ascii=False,indent=2),encoding="utf-8")
    return existing


if __name__ == "__main__":
    summary = build_summary()
    print(json.dumps({key:summary[key] for key in (
        "prices_unchanged_from_consistent_backup","published_files_unchanged_from_start",
        "reference_batches_hashed","reference_hash_failures","identity_hash_failures")},ensure_ascii=False))
