"""Summarize saved HTBR/Gildata probes without contacting the provider."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .config import DATA_ROOT, INDEXES


def build_report(root=DATA_ROOT / "verification" / "htbr"):
    selected = {}
    identities = {}
    evidence = {}
    files = sorted(root.glob("probe-*.json"))
    for path in files:
        probe = json.loads(path.read_text(encoding="utf-8"))
        for item in probe["evidence"]:
            raw = Path(item["raw_path"])
            if not raw.is_file() or hashlib.sha256(raw.read_bytes()).hexdigest() != item["raw_sha256"]:
                raise ValueError(f"HTBR evidence hash mismatch: {item['raw_sha256']}")
            evidence[item["raw_sha256"]] = item
        for code,result in probe["results"].items():
            if result.get("mapping"):
                identities[code] = {"mapping": result["mapping"], "basic_info": result.get("basic_info")}
            for point in result["points"]:
                key = code, point["trade_date"]
                priority = (point["reference_close"] is not None, probe["created_at"])
                if key not in selected or priority > selected[key][0]:
                    selected[key] = priority, point
    grouped = defaultdict(list)
    for (code,_),(_,point) in selected.items():
        grouped[code].append(point)
    summary = {}
    for code in INDEXES:
        rows = sorted(grouped[code], key=lambda row: row["trade_date"])
        counts = Counter(row["status"] for row in rows)
        basic = identities.get(code, {}).get("basic_info") or {}
        summary[code] = {"first_date": rows[0]["trade_date"] if rows else None,
                         "last_date": rows[-1]["trade_date"] if rows else None,
                         "counts": dict(counts), "english_name": basic.get("indexengname"),
                         "base_date": basic.get("basedate"),
                         "exceptions": [row for row in rows if row["status"] != "MATCH"]}
    report = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "provider": "Huatai PineBridge authorized index API",
              "quote_data_sources": sorted({item["data_source"] for item in evidence.values()
                                             if item["api_id"] == "index-daily-quote" and item["data_source"]}),
              "note": "Vendor data corroborates values; it does not prove independent issuer publication or change official prices.",
              "probe_files": [str(path) for path in files],
              "response_hashes_verified": len(evidence), "indexes": summary}
    root.mkdir(parents=True, exist_ok=True)
    (root / "summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    lines = ["# 华泰柏瑞指数接口核对", "", "接口响应均保存哈希；行情数据通道为聚源。供应商响应不自动提升为编制机构原始发布证据。", "",
             "| 指数 | 已查日期最早–最晚（可能不连续） | 一致 | 差异 | 无供应商点位 |", "|---|---|---:|---:|---:|"]
    for code,item in summary.items():
        count = item["counts"]
        lines.append(f"| {code} | {item['first_date']}–{item['last_date']} | {count.get('MATCH',0)} | {count.get('MISMATCH',0)} | {count.get('NO_PROVIDER',0)} |")
    lines.extend(["", "全部差异日期及对应点位见 `summary.json`。"])
    (root / "summary.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return report


if __name__ == "__main__":
    result = build_report()
    print(json.dumps({"probes":len(result["probe_files"]),"responses":result["response_hashes_verified"]},ensure_ascii=False))
