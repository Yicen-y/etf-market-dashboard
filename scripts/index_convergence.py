"""A date-unique, non-destructive projection of all saved index evidence."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3

from .config import DATA_ROOT, DATABASE_PATH, INDEXES, STRATEGIES
from .htbr_index_report import build_report as build_htbr_report
from .index_verification import (USER_CHANNEL_POINT_TOLERANCE, _archived_channel_matches,
                                 report as official_report, expected_identity, identity_status)
from .prism_metrics import calculate_prism_metrics
from .snapshot import read_dataset, read_manifest


SCHEMA = """CREATE TABLE IF NOT EXISTS index_converged_status (
 index_code TEXT NOT NULL, trade_date TEXT NOT NULL, local_close REAL NOT NULL,
 original_source TEXT NOT NULL, official_close REAL, official_status TEXT NOT NULL,
 official_provider TEXT, official_raw_sha256 TEXT, vendor_close REAL,
 vendor_status TEXT NOT NULL, vendor_raw_sha256 TEXT,
 numeric_status TEXT NOT NULL, identity_status TEXT NOT NULL,
 source_status TEXT NOT NULL, calendar_status TEXT NOT NULL,
 quality_status TEXT NOT NULL, detail_json TEXT NOT NULL,
 assessed_at TEXT NOT NULL, PRIMARY KEY(index_code,trade_date)
);
CREATE INDEX IF NOT EXISTS ix_converged_quality ON index_converged_status(quality_status,index_code,trade_date);"""


def _numeric(local, reference, decimals):
    if reference is None:
        return "NO_REFERENCE"
    if Decimal(str(reference)) <= 0:
        return "INVALID_REFERENCE"
    tolerance = Decimal(1).scaleb(-decimals) / 2
    delta = abs(Decimal(str(local)) - Decimal(str(reference)))
    if delta <= tolerance:
        return "MATCH"
    if decimals == 2 and delta == Decimal("0.01"):
        return "ONE_CENT_DIFFERENCE"
    return "MISMATCH"


def _calendar_status(code, day, official_state):
    if code == "H20915" and datetime.strptime(day, "%Y%m%d").weekday() >= 5:
        return "CALENDAR_REVIEW"
    return official_state if official_state in ("CALENDAR_EXCEPTION", "CALENDAR_REVIEW") else "NO_EXCEPTION"


def _htbr_points(root):
    if not root.exists():
        return {}
    build_htbr_report(root)  # checks every saved response hash before use
    selected = {}
    for path in sorted(root.glob("probe-*.json")):
        probe = json.loads(path.read_text(encoding="utf-8"))
        quote_hash = next((item["raw_sha256"] for item in probe["evidence"]
                           if item["api_id"] == "index-daily-quote"), None)
        for code,result in probe["results"].items():
            for point in result["points"]:
                if point["reference_close"] is None:
                    continue
                key = code, point["trade_date"]
                candidate = (probe["created_at"], point["reference_close"], quote_hash)
                if key not in selected or candidate[0] > selected[key][0]:
                    selected[key] = candidate
    return selected


def _official_points(connection):
    selected = {}
    rows = connection.execute("""SELECT v.index_code,v.trade_date,v.status,v.reference_close,
       b.provider,b.raw_sha256,b.identity_json,r.started_at
       FROM index_verification_results v JOIN index_verification_runs r ON r.run_id=v.run_id
       LEFT JOIN index_reference_batches b ON b.batch_id=v.batch_id
       WHERE r.status='COMPLETED'""")
    for code,day,status,close,provider,digest,identity,started in rows:
        key = code, day
        score = (close is not None, provider in ("CSI official HTTP","CNI official HTTPS"), started)
        if key not in selected or score > selected[key][0]:
            selected[key] = score, {"status": status, "close": close, "provider": provider,
                                    "sha256": digest, "identity": json.loads(identity or "{}")}
    return {key:value for key,(_,value) in selected.items()}


def _strategy_impact(local_by_code, vendor_by_code, data_root):
    try:
        snapshot = read_dataset(data_root, read_manifest(data_root), "index")
        calendar = snapshot["tradingCalendar"]["dates"]
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "SNAPSHOT_UNAVAILABLE", "strategies": {}}
    affected = {}
    for strategy in STRATEGIES:
        a,b = strategy["a"],strategy["b"]
        if not vendor_by_code.get(a) and not vendor_by_code.get(b):
            continue
        base_rows, alternative_rows = [], []
        for day in calendar:
            original = {code:local_by_code.get(code,{}).get(day) for code in (a,b)}
            alternative = {code:vendor_by_code.get(code,{}).get(day, original[code]) for code in (a,b)}
            base_rows.append({"tradeDate":day,"values":original})
            alternative_rows.append({"tradeDate":day,"values":alternative})
        base = calculate_prism_metrics(base_rows,a,b,trading_dates=calendar)
        alternative = calculate_prism_metrics(alternative_rows,a,b,trading_dates=calendar)
        differences = []
        for old,new in zip(base,alternative):
            x,y = old["return40Spread"],new["return40Spread"]
            if x is None or y is None or abs(x-y) < 1e-14:
                continue
            differences.append({"trade_date":old["tradeDate"],"local_spread":x,"vendor_spread":y,
                                "delta_pp":(y-x)*100,"direction_flip":(x > 0) != (y > 0)})
        affected[strategy["id"]] = {"affected_dates":len(differences),
                                    "max_abs_spread_delta_pp":max((abs(row["delta_pp"]) for row in differences),default=0),
                                    "direction_flips":[row for row in differences if row["direction_flip"]],
                                    "details":differences}
    return {"status":"COMPUTED_WITH_PUBLISHED_FORMULA","strategies":affected}


def _return_impact(local_by_code, vendor_by_code):
    """Hypothetical effect of substituting vendor closes; no market writes."""
    result = {}
    for code, local in local_by_code.items():
        if not vendor_by_code.get(code):
            continue
        dates = sorted(local)
        alternative = vendor_by_code[code]
        daily, rolling = [], []
        for i, day in enumerate(dates):
            for lag, target in ((1,daily),(40,rolling)):
                if i < lag:
                    continue
                old, current = dates[i-lag], dates[i]
                a0,a1 = local[old],local[current]
                b0,b1 = alternative.get(old,a0),alternative.get(current,a1)
                if min(a0,a1,b0,b1) <= 0:
                    continue
                difference_bps = ((b1/b0-1) - (a1/a0-1))*10000
                if abs(difference_bps) > 1e-10:
                    target.append({"trade_date":day,"delta_bps":difference_bps})
        result[code] = {"daily_affected":len(daily),
                        "daily_max_abs_delta_bps":max((abs(row["delta_bps"]) for row in daily),default=0),
                        "return40_affected":len(rolling),
                        "return40_max_abs_delta_bps":max((abs(row["delta_bps"]) for row in rolling),default=0)}
    return result


def build_convergence(database=DATABASE_PATH, data_root=DATA_ROOT):
    verification = data_root / "verification"
    official = official_report(database, verification)
    exception_status = {(r["index_code"],r["trade_date"]):r["status"] for r in official["anomalies"]}
    vendor = _htbr_points(verification / "htbr")
    assessed_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        source = _official_points(connection)
        local = [dict(row) for row in connection.execute(
            "SELECT index_code,trade_date,close_value,source FROM index_prices ORDER BY index_code,trade_date")]
        connection.executescript(SCHEMA)
        output = []
        local_by_code = defaultdict(dict)
        vendor_by_code = defaultdict(dict)
        for own in local:
            code,day = own["index_code"],own["trade_date"]
            key = code,day
            local_by_code[code][day] = own["close_value"]
            ref = source.get(key,{})
            alternative = vendor.get(key)
            vclose = alternative[1] if alternative else None
            if alternative:
                vendor_by_code[code][day] = vclose
            official_numeric = _numeric(own["close_value"],ref.get("close"),4 if code in ("480080","480081") else 2)
            vendor_numeric = _numeric(own["close_value"],vclose,2)
            observed = ref.get("identity",{}).get("observed",{})
            identity = identity_status(expected_identity(code), observed)
            official_state = exception_status.get(key,ref.get("status","NO_REFERENCE"))
            origin = "UNKNOWN_ORIGINAL_SOURCE" if own["source"] == "PROVENANCE_UNKNOWN" else "ORIGINAL_SOURCE_RECORDED"
            source_state = ("ISSUER_RESPONSE" if ref.get("provider") in ("CSI official HTTP","CNI official HTTPS")
                            else "VENDOR_AND_PARSED_RESPONSE" if alternative and ref.get("close") is not None
                            else "VENDOR_RESPONSE" if alternative else "PARSED_RESPONSE" if ref.get("close") is not None
                            else "NO_USABLE_RESPONSE")
            calendar = _calendar_status(code, day, official_state)
            numeric = official_numeric if official_numeric not in ("NO_REFERENCE","INVALID_REFERENCE") else vendor_numeric
            provider_disagreement = (ref.get("close") is not None and vclose is not None
                                     and _numeric(ref["close"],vclose,2) not in ("MATCH","INVALID_REFERENCE"))
            official_delta = (abs(Decimal(str(own["close_value"]))-Decimal(str(ref["close"])))
                              if ref.get("close") is not None else None)
            vendor_delta = (abs(Decimal(str(vclose))-Decimal(str(ref["close"])))
                            if vclose is not None and ref.get("close") is not None else None)
            accepted_local = (official_numeric in ("ONE_CENT_DIFFERENCE", "MISMATCH")
                              and own["source"] in ("AkShare", "ETFirst", "HTBR", "Wind MCP")
                              and official_delta is not None and official_delta < USER_CHANNEL_POINT_TOLERANCE
                              and identity == "MATCH" and source_state == "ISSUER_RESPONSE"
                              and _archived_channel_matches(Path(database),connection,code,day,
                                                             Decimal(str(own["close_value"]))))
            accepted_vendor = (provider_disagreement and vendor_delta is not None
                               and vendor_delta < USER_CHANNEL_POINT_TOLERANCE
                               and identity == "MATCH" and source_state == "ISSUER_RESPONSE"
                               and bool(alternative[2] if alternative else None))
            quality = (calendar if calendar != "NO_EXCEPTION" else
                       "NUMERIC_CONFLICT" if official_numeric in ("ONE_CENT_DIFFERENCE","MISMATCH") and not accepted_local else
                       "VENDOR_DISAGREEMENT" if (provider_disagreement or vendor_numeric in ("ONE_CENT_DIFFERENCE","MISMATCH"))
                           and not accepted_vendor else
                       "INVALID_REFERENCE" if official_numeric == "INVALID_REFERENCE" else
                       "IDENTITY_UNCONFIRMED" if identity != "MATCH" else
                       "NO_REFERENCE" if numeric == "NO_REFERENCE" else
                       "SOURCE_EVIDENCE_INCOMPLETE" if source_state != "ISSUER_RESPONSE" else "PASS")
            detail = {"official_numeric":official_numeric,"vendor_numeric":vendor_numeric,
                      "provider_disagreement":provider_disagreement,
                      "official_delta":float(official_delta) if official_delta is not None else None,
                      "vendor_delta":float(vendor_delta) if vendor_delta is not None else None,
                      "accepted_by_user_point_rule":accepted_local or accepted_vendor,
                      "official_evidence":ref.get("sha256"),"vendor_evidence":alternative[2] if alternative else None}
            output.append((code,day,own["close_value"],own["source"],ref.get("close"),official_state,
                           ref.get("provider"),ref.get("sha256"),vclose,vendor_numeric,
                           alternative[2] if alternative else None,numeric,identity,source_state,calendar,quality,
                           json.dumps(detail,ensure_ascii=False),assessed_at))
        with connection:
            connection.executemany("""INSERT INTO index_converged_status VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(index_code,trade_date) DO UPDATE SET
                local_close=excluded.local_close,original_source=excluded.original_source,
                official_close=excluded.official_close,official_status=excluded.official_status,
                official_provider=excluded.official_provider,official_raw_sha256=excluded.official_raw_sha256,
                vendor_close=excluded.vendor_close,vendor_status=excluded.vendor_status,
                vendor_raw_sha256=excluded.vendor_raw_sha256,numeric_status=excluded.numeric_status,
                identity_status=excluded.identity_status,source_status=excluded.source_status,
                calendar_status=excluded.calendar_status,quality_status=excluded.quality_status,
                detail_json=excluded.detail_json,assessed_at=excluded.assessed_at""",output)
    summaries = {}
    for code in INDEXES:
        rows = [row for row in output if row[0] == code]
        quality = Counter(row[15] for row in rows)
        summaries[code] = {"local_records":len(rows),"reference_covered":sum(row[4] is not None or row[8] is not None for row in rows),
                           "issuer_numeric_match":sum(row[6] in ("CSI official HTTP","CNI official HTTPS")
                                                      and json.loads(row[16])["official_numeric"] == "MATCH" for row in rows),
                           "vendor_numeric_match":sum(row[9] == "MATCH" for row in rows),
                           "precision_differences":sum(row[9] == "ONE_CENT_DIFFERENCE" for row in rows),
                           "numeric_conflicts":quality["NUMERIC_CONFLICT"],
                           "missing_reference":quality["NO_REFERENCE"],
                           "original_source_unknown":sum(row[3] == "PROVENANCE_UNKNOWN" for row in rows),
                           "identity_status":"CURRENCY_UNCONFIRMED" if code in ("480080","480081") else
                               "CONFIRMED_BY_ISSUER_DOCUMENT_AND_REFERENCE" if any(row[12] == "MATCH" for row in rows) else "UNCONFIRMED",
                           "quality_statuses":dict(quality),
                           "current_publication_policy":"REQUIRE_IDENTITY_EVIDENCE" if code in ("480080","480081") else
                               "VERIFY_NEW_CANDIDATE_ONLY"}
    impact = _strategy_impact(local_by_code,vendor_by_code,data_root)
    one_cent = [row for row in output if row[9] == "ONE_CENT_DIFFERENCE"]
    precision = {"total":len(one_cent),
                 "vendor_higher":sum(Decimal(str(row[8])) > Decimal(str(row[2])) for row in one_cent),
                 "vendor_lower":sum(Decimal(str(row[8])) < Decimal(str(row[2])) for row in one_cent),
                 "by_year":dict(sorted(Counter(row[1][:4] for row in one_cent).items())),
                 "issuer_agrees_with_local":sum(row[6] in ("CSI official HTTP","CNI official HTTPS")
                    and json.loads(row[16])["official_numeric"] == "MATCH" for row in one_cent),
                 "classification":"USER_TOLERANCE_ACCEPTED_WHEN_OFFICIAL_IDENTITY_AND_EVIDENCE_PASS",
                 "reason":"The raw one-cent discrepancy remains recorded; acceptance below 0.05 point is a user publication rule, not an official precision claim."}
    payload = {"generated_at":assessed_at,"indexes":summaries,"strategy_impact":impact,
               "return_impact":_return_impact(local_by_code,vendor_by_code),
               "one_cent_analysis":precision,
               "unique_local_days":len(output),"vendor_precision":"two decimals; 0.005 point tolerance",
               "status_rule":"issuer response governs identity; archived alternate responses within strictly 0.05 point can pass while raw deltas remain visible"}
    (verification / "convergence-summary.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    lines = ["# 14 条指数核验收敛", "", f"按代码、日期唯一记录：{len(output)} 条。正式行情未更改。", "",
             "| 指数 | 本地 | 参考覆盖 | 官方数值一致 | 供应商数值一致 | 一分差异 | 原始来源未知 | 质量状态 |",
             "|---|---:|---:|---:|---:|---:|---:|---|"]
    for code,item in summaries.items():
        lines.append(f"| {code} | {item['local_records']} | {item['reference_covered']} | {item['issuer_numeric_match']} | {item['vendor_numeric_match']} | {item['precision_differences']} | {item['original_source_unknown']} | {item['quality_statuses']} |")
    (verification / "convergence-summary.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = build_convergence()
    print(json.dumps({"indexes":len(result["indexes"]),"unique_local_days":result["unique_local_days"]},ensure_ascii=False))
