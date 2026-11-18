"""Non-destructive Huatai PineBridge index-reference probe.

Runs the installed, authorized skill client, saves its original JSON response,
and compares returned daily closes to the registered local index series.
It does not promote observations into the official verification store.
Run with Python >=3.10, e.g. ``python -m scripts.htbr_index_probe --codes H00919``.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from .config import DATABASE_PATH, DATA_ROOT, INDEXES

SKILL = Path.home() / ".codex" / "skills" / "htbr-etf-skill"


def skill_call(api_id, params, root):
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    command = [sys.executable, str(SKILL / "scripts" / "api_client.py"),
               "invoke", api_id, json.dumps(params, ensure_ascii=False, separators=(",", ":"))]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=environment, timeout=120)
    captured_at = datetime.now(timezone.utc).isoformat()
    if completed.returncode:
        raise RuntimeError(f"{api_id} client exit {completed.returncode}; see authorized skill client")
    response = json.loads(completed.stdout.decode("utf-8-sig"))
    digest = hashlib.sha256(completed.stdout).hexdigest()
    raw_directory = root / "raw"
    raw_directory.mkdir(parents=True, exist_ok=True)
    raw_path = raw_directory / f"{digest}.json"
    if not raw_path.exists():
        raw_path.write_bytes(completed.stdout)
    evidence = {"api_id": api_id, "request": params, "captured_at": captured_at,
                "raw_sha256": digest, "raw_path": str(raw_path),
                "data_source": response.get("meta", {}).get("dataSource"),
                "trace_id": response.get("meta", {}).get("traceId"),
                "success": response.get("success"),
                "error_code": (response.get("error") or {}).get("code")}
    if not response.get("success") or response.get("meta", {}).get("degraded"):
        raise RuntimeError(f"{api_id} returned {evidence['error_code'] or 'DEGRADED'}; response hash {digest}")
    return response, evidence


def probe(codes, start, end, *, database=DATABASE_PATH, root=DATA_ROOT / "verification" / "htbr"):
    if sys.version_info < (3, 10):
        raise RuntimeError("The installed HTBR skill requires Python >=3.10")
    if not (SKILL / "scripts" / "api_client.py").is_file():
        raise RuntimeError("HTBR skill client is not installed")
    status = subprocess.run([sys.executable, str(SKILL / "config.py"), "status"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    if status.returncode:
        raise RuntimeError(f"HTBR credential status {status.returncode}; follow skill key guide")
    root.mkdir(parents=True, exist_ok=True)
    run_id = hashlib.sha256(json.dumps([codes,start,end],sort_keys=True).encode()).hexdigest()[:24]
    evidence = []
    mappings = {}
    for code in codes:
        response, item = skill_call("index-resolve", {"secuCode": code}, root)
        evidence.append(item)
        candidates = response.get("data", {}).get("candidates", [])
        if len(candidates) == 1 and candidates[0].get("secuCode") == code:
            mappings[code] = candidates[0]
        time.sleep(3)
    basic = {}
    if mappings:
        response, item = skill_call("index-basic-info",
                                    {"indexObject": [m["innerCode"] for m in mappings.values()]}, root)
        evidence.append(item)
        basic = {str(row.get("indexcode")): row for row in response.get("data", {}).get("records", [])}
        time.sleep(3)
    reference = {}
    if mappings:
        response, item = skill_call("index-daily-quote",
                                    {"indexCodes": [m["gilCode"] for m in mappings.values()],
                                     "beginDate": datetime.strptime(start, "%Y%m%d").strftime("%Y-%m-%d"),
                                     "endDate": datetime.strptime(end, "%Y%m%d").strftime("%Y-%m-%d")}, root)
        evidence.append(item)
        for row in response.get("data", {}).get("records", []):
            code = row.get("indexCode")
            if code in mappings and row.get("gilcode") == mappings[code]["gilCode"]:
                reference.setdefault(code, {})[str(row["tradingDay"]).replace("-", "")] = row.get("closePrice")
    with sqlite3.connect(database) as db:
        local = {code: {day: value for day,value in db.execute(
            "SELECT trade_date,close_value FROM index_prices WHERE index_code=? AND trade_date BETWEEN ? AND ?",
            (code,start,end))} for code in codes}
    results = {}
    for code in codes:
        points = []
        for day in sorted(set(local[code]) | set(reference.get(code, {}))):
            own, other = local[code].get(day), reference.get(code, {}).get(day)
            # This vendor publishes two decimals even when the issuer's own
            # CNI feed publishes four. Assess the vendor at its own precision.
            tolerance = Decimal("0.005")
            state = ("NO_LOCAL" if own is None else "NO_PROVIDER" if other is None else
                     "INVALID_VALUE" if Decimal(str(other)) <= 0 else
                     "MATCH" if abs(Decimal(str(own))-Decimal(str(other))) <= tolerance else "MISMATCH")
            points.append({"trade_date": day, "local_close": own, "reference_close": other, "status": state})
        results[code] = {"mapping": mappings.get(code), "basic_info": basic.get(code),
                         "local_count": len(local[code]), "reference_count": len(reference.get(code, {})),
                         "counts": {state: sum(p["status"] == state for p in points)
                                    for state in ("MATCH","MISMATCH","NO_LOCAL","NO_PROVIDER","INVALID_VALUE")},
                         "points": points}
    report = {"run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(),
              "codes": codes, "start": start, "end": end, "evidence": evidence, "results": results,
              "note": "HTBR/Gildata corroboration only; issuer identity and original upstream remain separate."}
    (root / f"probe-{run_id}.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report


def reassess_saved_report(path):
    """Correct vendor-precision assessments using immutable saved responses."""
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    for item in report["evidence"]:
        raw = Path(item["raw_path"])
        if not raw.is_file() or hashlib.sha256(raw.read_bytes()).hexdigest() != item["raw_sha256"]:
            raise ValueError(f"reference response missing or changed: {item['raw_sha256']}")
    for result in report["results"].values():
        for point in result["points"]:
            own, other = point["local_close"], point["reference_close"]
            if own is not None and other is not None and Decimal(str(other)) > 0:
                point["status"] = ("MATCH" if abs(Decimal(str(own))-Decimal(str(other))) <= Decimal("0.005")
                                   else "MISMATCH")
        result["counts"] = {state: sum(p["status"] == state for p in result["points"])
                            for state in ("MATCH","MISMATCH","NO_LOCAL","NO_PROVIDER","INVALID_VALUE")}
    report["reassessed_at"] = datetime.now(timezone.utc).isoformat()
    report["comparison_precision"] = "vendor two-decimal closes; 0.005 point tolerance"
    Path(path).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", nargs="+", choices=tuple(INDEXES))
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--reassess", type=Path)
    args = parser.parse_args()
    if args.reassess:
        result = reassess_saved_report(args.reassess)
        print(json.dumps({code:item["counts"] for code,item in result["results"].items()},ensure_ascii=False))
        return
    if not (args.codes and args.start and args.end):
        parser.error("--codes, --start, and --end are required for a live probe")
    result = probe(args.codes,args.start,args.end)
    print(json.dumps({code:result["results"][code]["counts"] for code in args.codes},ensure_ascii=False))


if __name__ == "__main__":
    main()
