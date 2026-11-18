"""Read-only series, anomaly, and version views for the data center."""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import json
import sqlite3

from .config import INDEXES, PRODUCTS, STRATEGIES
from .snapshot import read_dataset, read_manifest


def _table_names(connection):
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _issue_counts(connection, tables):
    if "quality_issues" not in tables:
        return {}
    return {(kind,symbol):count for kind,symbol,count in connection.execute(
        "SELECT kind,symbol,COUNT(*) FROM quality_issues WHERE resolution_status='open' GROUP BY kind,symbol")}


def _index_failures(connection, tables):
    if not {"index_reference_batches","index_reference_failures"} <= tables:
        return {}
    successes = {code:at for code,at in connection.execute(
        "SELECT index_code,MAX(fetched_at) FROM index_reference_batches WHERE status='FETCHED' GROUP BY index_code")}
    failures = {}
    for code,provider,upstream,at,diagnostic in connection.execute("""SELECT b.index_code,b.provider,b.upstream,
        f.observed_at,f.diagnostic_json FROM index_reference_failures f
        JOIN index_reference_batches b ON b.batch_id=f.batch_id ORDER BY f.observed_at DESC"""):
        if code in failures:
            continue
        info = json.loads(diagnostic)
        failures[code] = {"observed_at":at,"provider":provider,"upstream":upstream,
                          "http_status":info.get("http_status"),"error_type":info.get("error_type")
                                       or (f"HTTP_{info['http_status']}" if info.get("http_status") else "REFERENCE_FAILURE"),
                          "endpoint":info.get("endpoint"),"response_hash":info.get("body_sha256"),
                          "unresolved":at > successes.get(code,"")}
    return failures


def _trailing_market_failures(connection, tables):
    if "quality_issues" not in tables:
        return {}
    failures = {}
    for kind, code, day, at in connection.execute("""SELECT kind,symbol,trade_date,detected_at
        FROM quality_issues WHERE issue_code='SOURCE_TRAILING_UNAVAILABLE'
        AND resolution_status='open' ORDER BY issue_id DESC"""):
        failures.setdefault((kind, code), {"trade_date": day, "observed_at": at,
                                            "error_type": "SOURCE_TRAILING_UNAVAILABLE", "unresolved": True})
    return failures


def _convergence_counts(connection, tables):
    if "index_converged_status" not in tables:
        return {}
    rows = connection.execute("""SELECT index_code,COUNT(*),
        SUM(CASE WHEN official_close IS NOT NULL OR vendor_close IS NOT NULL THEN 1 ELSE 0 END),
        SUM(CASE WHEN quality_status='PASS' THEN 1 ELSE 0 END),
        SUM(CASE WHEN vendor_status='ONE_CENT_DIFFERENCE' THEN 1 ELSE 0 END),
        SUM(CASE WHEN quality_status NOT IN ('PASS','SOURCE_EVIDENCE_INCOMPLETE') THEN 1 ELSE 0 END)
        FROM index_converged_status GROUP BY index_code""")
    return {code:{"records":count,"reference_covered":covered or 0,"fully_verified":passed or 0,
                  "precision_differences":precision or 0,"attention_count":attention or 0}
            for code,count,covered,passed,precision,attention in rows}


def _latest_sources(connection, tables, kind):
    if "raw_observations" not in tables:
        return {}
    return {symbol:{"provider":provider,"upstream":upstream,"fetched_at":at}
            for symbol,provider,upstream,at in connection.execute("""SELECT symbol,provider,upstream_publisher,fetched_at
            FROM raw_observations r WHERE kind=? AND raw_record_id=(SELECT MAX(raw_record_id)
            FROM raw_observations newer WHERE newer.symbol=r.symbol AND newer.kind=r.kind)""",(kind,))}


def _latest_issuer_references(connection, tables):
    if not {"index_reference_batches", "index_reference_observations"} <= tables:
        return {}
    rows = connection.execute("""SELECT b.index_code,MAX(o.trade_date),MAX(b.fetched_at)
        FROM index_reference_batches b JOIN index_reference_observations o ON o.batch_id=b.batch_id
        WHERE b.status='FETCHED' AND b.provider IN ('CSI official HTTP','CNI official HTTPS')
        AND b.raw_sha256 IS NOT NULL AND b.raw_path IS NOT NULL GROUP BY b.index_code""")
    return {code:{"latest_date":day,"fetched_at":at,"provider":"CNI official HTTPS" if code in ('480080','480081') else 'CSI official HTTP'}
            for code,day,at in rows}


def _current_etf_checks(connection, tables, latest_rows):
    from .etf_reference_verification import verified_close
    checks = {}
    for code, local in latest_rows.items():
        day = local.get("latest_date")
        if not day:
            continue
        open_issue = (connection.execute("""SELECT 1 FROM quality_issues
            WHERE kind='etf' AND symbol=? AND trade_date=? AND resolution_status='open' LIMIT 1""",
            (code, day)).fetchone() if "quality_issues" in tables else None)
        corroborated = False
        if "raw_observations" in tables:
            request = connection.execute("""SELECT provider_request_id FROM raw_observations
                WHERE kind='etf' AND symbol=? AND trade_date=? ORDER BY raw_record_id DESC LIMIT 1""",
                (code, day)).fetchone()
            if request:
                try:
                    verification = json.loads(request[0] or "{}").get("independent_verification", {})
                    corroborated = bool(verification.get("provider") and verification.get("raw_sha256")
                                        and verification.get("matched_dates", 0) > 0)
                except (TypeError, ValueError, AttributeError):
                    pass
        price = (connection.execute("SELECT close_price FROM etf_prices WHERE product_code=? AND trade_date=?",
                                    (code,day)).fetchone() if "etf_prices" in tables else None)
        verified = verified_close(connection,code,day,price[0]) if price else False
        checks[code] = "ANOMALY" if open_issue else "PASS" if corroborated or verified else "UNVERIFIED"
    return checks


def _latest_rows(connection, tables, table, code_column):
    if table not in tables:
        return {}
    return {code:{"records":count,"latest_date":day,"original_source":source}
            for code,count,day,source in connection.execute(f"""SELECT {code_column},COUNT(*),MAX(trade_date),
              (SELECT source FROM {table} last WHERE last.{code_column}=t.{code_column}
               ORDER BY trade_date DESC LIMIT 1) FROM {table} t GROUP BY {code_column}""")}


def _simple_rows(connection,tables,table,code_column,date_column):
    if table not in tables:
        return {}
    return {code:{"records":count,"latest_date":day}
            for code,count,day in connection.execute(
                f"SELECT {code_column},COUNT(*),MAX({date_column}) FROM {table} GROUP BY {code_column}")}


def _flow_evidence(connection, tables, codes):
    if not {"fund_flow_etf_daily_clean","fund_flow_data_sources"} <= tables:
        return {}
    result = {}
    for code, local in codes.items():
        row = connection.execute("""SELECT m.status,c.validation_status,c.source_id,
            s.retrieved_at,s.error_message FROM fund_flow_etf_daily_metrics m
            LEFT JOIN fund_flow_etf_daily_clean c ON c.etf_code=m.etf_code AND c.trade_date=m.trade_date
            LEFT JOIN fund_flow_data_sources s ON s.source_id=c.source_id
            WHERE m.etf_code=? AND m.trade_date=? LIMIT 1""",(code,local["latest_date"])).fetchone()
        if row:
            result[code] = {"metric_status":row[0],"validation_status":row[1],
                            "source_id":row[2],"retrieved_at":row[3],
                            "source_error":bool(row[4])}
    return result


def _dividend_evidence(connection, tables, codes):
    if not {"dividend_revisions","source_documents"} <= tables:
        return {}
    result = {}
    for code, local in codes.items():
        row = connection.execute("""SELECT e.state,d.publisher,d.verification_level,
            d.published_at,d.source_id FROM dividend_events e
            LEFT JOIN dividend_revisions r ON r.revision_id=e.current_revision_id
            LEFT JOIN source_documents d ON d.id=r.source_document_id
            WHERE e.security_id=? AND e.ex_date=? LIMIT 1""",(code,local["latest_date"])).fetchone()
        if row:
            result[code] = {"event_state":row[0],"publisher":row[1],
                            "verification_level":row[2],"document_date":row[3],
                            "source_id":row[4]}
    return result


def _overall_status(fetch_failed=False, stale=False, quality="UNKNOWN"):
    if fetch_failed:
        return "FETCH_FAILED"
    if stale:
        return "STALE"
    if quality == "ANOMALY":
        return "ANOMALY"
    if quality in ("UNKNOWN", None):
        return "UNKNOWN"
    return "NORMAL"


def _bond_file(data_root):
    path = data_root / "research" / "bond_value_hs300.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("rows",[])
        if not isinstance(rows,list):
            raise ValueError("invalid rows")
        return {"records":len(rows),"latest_date":rows[-1].get("tradeDate") if rows else None,
                "updated_at":payload.get("updatedAt"),"source":payload.get("sources"),
                "status":payload.get("status")}
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def build_detail(data_root: Path, database: Path, snapshot_id: str | None, expected_mainland: str | None):
    if not database.exists():
        return {"series":[],"series_summary":{"total":0,"normal":0,"stale":0,"anomaly":0},
                "versions":[],"provider_diagnostics":[],"index_anomalies":[]}
    with sqlite3.connect(database.as_uri()+"?mode=ro",uri=True) as connection:
        tables = _table_names(connection)
        index_rows = _latest_rows(connection,tables,"index_prices","index_code")
        etf_rows = _latest_rows(connection,tables,"etf_prices","product_code")
        etf_current_checks = _current_etf_checks(connection,tables,etf_rows)
        etf_reference_rows = (dict((code,{"trade_date":day,"matched_dates":matched,"fetched_at":fetched})
             for code,day,matched,fetched in connection.execute("""SELECT product_code,trade_date,matched_dates,fetched_at
             FROM etf_reference_checks WHERE status='PASS' ORDER BY fetched_at"""))
             if "etf_reference_checks" in tables else {})
        flows = _simple_rows(connection,tables,"fund_flow_etf_daily_metrics","etf_code","trade_date")
        dividends = _simple_rows(connection,tables,"dividend_events","security_id","ex_date")
        flow_evidence = _flow_evidence(connection,tables,flows)
        dividend_evidence = _dividend_evidence(connection,tables,dividends)
        issue_counts = _issue_counts(connection,tables)
        failures = _index_failures(connection,tables)
        trailing_failures = _trailing_market_failures(connection,tables)
        verified = _convergence_counts(connection,tables)
        anomalies = ([dict(zip(("index_code","trade_date","quality_status","local_close","official_close",
                                  "vendor_close","official_raw_sha256","vendor_raw_sha256"),row))
                      for row in connection.execute("""SELECT index_code,trade_date,quality_status,local_close,
                        official_close,vendor_close,official_raw_sha256,vendor_raw_sha256
                        FROM index_converged_status WHERE quality_status NOT IN ('PASS','SOURCE_EVIDENCE_INCOMPLETE')
                        ORDER BY CASE quality_status
                          WHEN 'VENDOR_DISAGREEMENT' THEN 0
                          WHEN 'CALENDAR_EXCEPTION' THEN 1
                          WHEN 'CALENDAR_REVIEW' THEN 2
                          WHEN 'NO_REFERENCE' THEN 3
                          WHEN 'INVALID_VALUE' THEN 4
                          WHEN 'IDENTITY_UNCONFIRMED' THEN 5
                          ELSE 6 END, trade_date DESC,index_code LIMIT 100""")]
                     if "index_converged_status" in tables else [])
        index_sources = _latest_sources(connection,tables,"index")
        etf_sources = _latest_sources(connection,tables,"etf")
        issuer_references = _latest_issuer_references(connection,tables)
        route_approvals = (dict(connection.execute("SELECT index_code,MAX(trade_date) FROM index_route_approvals GROUP BY index_code"))
                           if "index_route_approvals" in tables else {})
        unknown_original = (dict(connection.execute("SELECT index_code,COUNT(*) FROM index_prices WHERE source='PROVENANCE_UNKNOWN' GROUP BY index_code"))
                            if "index_prices" in tables else {})
        versions = ([dict(zip(("snapshot_id","status","published_at","created_at"),row)) for row in connection.execute(
            "SELECT snapshot_id,status,published_at,created_at FROM release_manifest ORDER BY created_at DESC LIMIT 20")]
            if "release_manifest" in tables else [])
    series = []
    published_dates = {"index": {}, "etf": {}}
    if snapshot_id:
        try:
            manifest = read_manifest(data_root)
            for kind in ("index", "etf"):
                payload = read_dataset(data_root, manifest, kind)
                code_key = "indexCode" if kind == "index" else "productCode"
                for row in payload.get("flatRecords", []):
                    code, day = row.get(code_key), row.get("tradeDate")
                    if code and day:
                        published_dates[kind][code] = max(day, published_dates[kind].get(code, ""))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            published_dates = {"index": {}, "etf": {}}
    for code,item in INDEXES.items():
        local = index_rows.get(code,{})
        projection = verified.get(code,{})
        failure = failures.get(code)
        trailing = trailing_failures.get(("index",code))
        if trailing and local.get("latest_date") and trailing["trade_date"] > local["latest_date"]:
            failure = trailing
        recent = index_sources.get(code,{})
        issuer = issuer_references.get(code,{})
        fetch_failed = bool(failure and failure["unresolved"])
        stale = bool(expected_mainland and code != "H20915" and local.get("latest_date")
                     and local["latest_date"] < expected_mainland)
        quality = "ANOMALY" if projection.get("attention_count",0) else "UNKNOWN" if not projection else "PASS"
        operational = _overall_status(fetch_failed,stale,quality) if local else "UNKNOWN"
        series.append({"id":f"index:{code}","code":code,"name":item["name"],"type":"index",
                       "records":local.get("records",0),"latest_date":local.get("latest_date"),
                       "primary_source":"CSI" if code == "H00922" else "ETFirst",
                       "actual_source":local.get("original_source"),"last_provider":recent.get("provider"),
                       "last_upstream":recent.get("upstream"),"last_collected_at":recent.get("fetched_at"),
                       "latest_reference_date":issuer.get("latest_date"),"last_reference_at":issuer.get("fetched_at"),
                       "last_reference_provider":issuer.get("provider"),
                       "original_unknown_count":unknown_original.get(code,0),
                       "fetch_status":"FAILED" if fetch_failed else "RECORDED" if recent else "UNKNOWN",
                       "fetch_error":failure if fetch_failed else None,"quality_status":quality,
                       "source_evidence_level": "ISSUER_HTTP_COVERAGE" if projection.get("fully_verified",0) == local.get("records",-1)
                           else "PARTIAL_REFERENCE" if projection.get("reference_covered",0) else "UNKNOWN",
                       "operational_status":operational,"verification_coverage":
                           projection.get("fully_verified",0)/local["records"] if local.get("records") else 0,
                       "reference_covered":projection.get("reference_covered",0),
                       "fully_verified":projection.get("fully_verified",0),
                       "precision_differences":projection.get("precision_differences",0),
                       "open_issue_count":issue_counts.get(("index",code),0)+projection.get("attention_count",0),
                       "last_valid_date":local.get("latest_date"),"previous_release_available":bool(snapshot_id),
                       "affected_dashboards":[s["name"] for s in STRATEGIES if code in (s["a"],s["b"])]})
    for code,item in PRODUCTS.items():
        local = etf_rows.get(code,{})
        recent = etf_sources.get(code,{})
        reference = etf_reference_rows.get(code,{})
        reference_current = (etf_current_checks.get(code) == "PASS" and
                             reference.get("trade_date") == local.get("latest_date"))
        stale = bool(expected_mainland and local.get("latest_date") and local["latest_date"] < expected_mainland)
        issues = issue_counts.get(("etf",code),0)
        series.append({"id":f"etf:{code}","code":code,"name":item["name"],"type":"etf",
                       "records":local.get("records",0),"latest_date":local.get("latest_date"),
                       "primary_source":"ETFirst","actual_source":local.get("original_source"),
                       "last_provider":recent.get("provider"),"last_upstream":recent.get("upstream"),
                       "last_collected_at":recent.get("fetched_at"),
                       "last_reference_at":reference.get("fetched_at") if reference_current else None,
                       "last_reference_provider":"HTBR" if reference_current else None,
                       "fetch_status":"RECORDED" if recent else "UNKNOWN",
                       "quality_status":"ANOMALY" if issues else "UNKNOWN",
                       "source_evidence_level":f"HTBR_RAW_MATCH_{reference['matched_dates']}D" if reference_current else
                           "PROVIDER_TABLE" if recent else "UNKNOWN",
                       "operational_status":_overall_status(False,stale,"ANOMALY" if issues else "UNKNOWN") if local else "UNKNOWN",
                       "verification_coverage":None,"open_issue_count":issues,
                       "last_valid_date":local.get("latest_date"),"previous_release_available":bool(snapshot_id),
                       "affected_dashboards":["主看板","轮动总览"]})
    for code,local in flows.items():
        evidence = flow_evidence.get(code,{})
        quality = "PASS" if evidence.get("metric_status") == evidence.get("validation_status") == "PASS" else "ANOMALY" if evidence else "UNKNOWN"
        stale = bool(expected_mainland and local["latest_date"] and local["latest_date"].replace("-","") < expected_mainland)
        source_id = evidence.get("source_id")
        series.append({"id":f"flow:{code}","code":code,"name":f"ETF 份额与资金流 {code}","type":"flow",
                       "records":local["records"],"latest_date":local["latest_date"],"primary_source":"exchange shares + NAV",
                       "actual_source":source_id,"last_provider":source_id.split(":")[0] if source_id else None,
                       "last_upstream":"SSE" if source_id and ":sse:" in source_id else "SZSE" if source_id and ":szse:" in source_id else None,
                       "last_collected_at":evidence.get("retrieved_at"),
                       "fetch_status":"FAILED" if evidence.get("source_error") else "RECORDED" if evidence.get("retrieved_at") else "UNKNOWN",
                       "quality_status":quality,"source_evidence_level":"SOURCE_ID_LINKED" if source_id else "UNKNOWN",
                       "operational_status":_overall_status(evidence.get("source_error"),stale,quality),
                       "verification_coverage":None,"open_issue_count":0,
                       "last_valid_date":local["latest_date"],"previous_release_available":bool(snapshot_id),
                       "affected_dashboards":["资金流向"]})
    for code,local in dividends.items():
        evidence = dividend_evidence.get(code,{})
        official = evidence.get("verification_level") == "OFFICIAL_VERIFIED"
        quality = "PASS" if official else "UNKNOWN"
        series.append({"id":f"dividend:{code}","code":code,"name":f"股息事件 {code}","type":"dividend",
                       "records":local["records"],"latest_date":local["latest_date"],"primary_source":"official distribution notice",
                       "actual_source":evidence.get("source_id"),"last_upstream":evidence.get("publisher"),
                       "last_collected_at":None,"fetch_status":"RECORDED" if official else "UNKNOWN",
                       "quality_status":quality,"source_evidence_level":evidence.get("verification_level") or "UNKNOWN",
                       "operational_status":_overall_status(quality=quality),
                       "verification_coverage":None,"open_issue_count":0,
                       "last_valid_date":local["latest_date"],"previous_release_available":bool(snapshot_id),
                       "affected_dashboards":["股息率","红利研究"]})
    bond = _bond_file(data_root)
    bond_stale = bool(bond and expected_mainland and bond.get("latest_date") and bond["latest_date"] < expected_mainland)
    bond_quality = "STRUCTURE_PASS" if bond and bond["status"] == "READY" else "UNKNOWN"
    series.append({"id":"bond_value:hs300","code":"hs300","name":"股债估值","type":"valuation",
                   "records":bond["records"] if bond else None,"latest_date":bond["latest_date"] if bond else None,
                   "primary_source":"bond-value pipeline",
                   "actual_source":", ".join(sorted({str(value).split(" / ")[0] for value in bond["source"].values()}))
                       if bond and isinstance(bond["source"],dict) else None,
                   "last_collected_at":bond["updated_at"] if bond else None,
                   "fetch_status":"LOCAL_FILE" if bond else "UNKNOWN","quality_status":bond_quality,
                   "source_evidence_level":"LOCAL_DERIVED" if bond else "UNKNOWN",
                   "operational_status":_overall_status(False,bond_stale,bond_quality),
                   "verification_coverage":None,"open_issue_count":0,
                   "last_valid_date":bond["latest_date"] if bond else None,"previous_release_available":bool(snapshot_id),
                   "affected_dashboards":["股债性价比"]})
    for row in series:
        kind, code = row["type"], row["code"]
        latest = row.get("last_valid_date")
        published = published_dates.get(kind, {}).get(code)
        expected = (row.get("latest_reference_date") if code == "H20915" else expected_mainland
                    if kind in ("index", "etf") else None)
        row["published_date"] = published
        row["snapshot_id"] = snapshot_id if published else None
        row["acquisition_status"] = ("FAILED" if row["fetch_status"] == "FAILED" else
                                     "SUCCEEDED" if row.get("last_collected_at") or row.get("last_reference_at") else "NOT_RUN")
        row["freshness_status"] = ("NO_VALID_DATA" if not latest else
                                   "UNKNOWN" if not expected else
                                   "CURRENT" if latest.replace("-", "") >= expected else "STALE")
        row["historical_quality_status"] = row["quality_status"]
        if kind == "index" and latest:
            from .index_verification import gate_index_candidates
            # A current close must come from the database, never from a vendor
            # response or a historical projection counter.
            with sqlite3.connect(database.as_uri()+"?mode=ro", uri=True) as connection:
                close = connection.execute("SELECT close_value FROM index_prices WHERE index_code=? AND trade_date=?",
                                           (code, latest)).fetchone()
                current_issue = (connection.execute("SELECT 1 FROM quality_issues WHERE kind='index' AND symbol=? AND trade_date=? AND resolution_status='open' LIMIT 1",
                                                    (code, latest)).fetchone() if "quality_issues" in tables else None)
            candidate = {"indexCode": code, "tradeDate": latest, "closeValue": close[0] if close else None}
            reference_ready = {"index_reference_batches", "index_reference_observations"} <= tables
            row["current_quality_status"] = ("PASS" if close and reference_ready and not gate_index_candidates(database, [candidate])
                                             else "ANOMALY" if current_issue else "UNVERIFIED")
            row["identity_status"] = ("ROUTE_APPROVED_CURRENCY_UNCONFIRMED" if row["current_quality_status"] == "PASS"
                                      and code in ("480080", "480081") and route_approvals.get(code) == latest else
                                      "CONFIRMED" if row["current_quality_status"] == "PASS" else "UNCONFIRMED")
            row["historical_provenance_status"] = ("ORIGINAL_UNKNOWN_REFERENCE_PARTIAL" if row["original_unknown_count"] and row.get("verification_coverage", 0) < 1 else
                                                    "ORIGINAL_UNKNOWN_REFERENCE_COVERED" if row["original_unknown_count"] else
                                                    "PARTIAL_REFERENCE" if row.get("verification_coverage", 0) < 1 else "REFERENCE_COVERED")
        elif kind == "etf":
            row["current_quality_status"] = etf_current_checks.get(code, "UNVERIFIED")
            row["identity_status"] = "NOT_APPLICABLE"
            row["historical_provenance_status"] = row["source_evidence_level"]
        else:
            row["current_quality_status"] = ("PASS" if row["quality_status"] in ("PASS", "STRUCTURE_PASS")
                                             else "ANOMALY" if row["quality_status"] == "ANOMALY" else "UNVERIFIED")
            row["identity_status"] = "NOT_APPLICABLE"
            row["historical_provenance_status"] = row["source_evidence_level"]
        row["release_status"] = ("NOT_APPLICABLE" if kind not in ("index", "etf") else
                                 "NOT_PUBLISHED" if not published else
                                 "USING_PREVIOUS" if expected and published < expected else "PUBLISHED")
    counts = Counter(row["operational_status"] for row in series)
    dimensions = {name:dict(Counter(row.get(name, "UNKNOWN") for row in series))
                  for name in ("acquisition_status", "freshness_status", "current_quality_status", "release_status")}
    return {"series":series,"series_summary":{"total":len(series),"normal":counts["NORMAL"],
            "stale":counts["STALE"],"fetch_failed":counts["FETCH_FAILED"],
            "anomaly":counts["ANOMALY"],"unknown":counts["UNKNOWN"],"dimensions":dimensions},
            "versions":versions,"index_anomalies":anomalies,
            "provider_diagnostics":[{"index_code":code,**info} for code,info in failures.items()
                                    if info["unresolved"]]}


def read_index_detail(database: Path, code: str, *, status: str | None = None, limit: int = 200):
    if code not in INDEXES:
        raise KeyError(code)
    limit = max(1,min(limit,500))
    with sqlite3.connect(database.as_uri()+"?mode=ro",uri=True) as connection:
        connection.row_factory = sqlite3.Row
        if "index_converged_status" not in _table_names(connection):
            return {"code":code,"rows":[],"status":"NOT_BUILT"}
        sql = "SELECT * FROM index_converged_status WHERE index_code=?"
        params = [code]
        if status:
            sql += " AND quality_status=?"
            params.append(status)
        sql += " ORDER BY trade_date DESC LIMIT ?"
        params.append(limit)
        rows = [dict(row) for row in connection.execute(sql,params)]
    for row in rows:
        row["detail"] = json.loads(row.pop("detail_json"))
    return {"code":code,"status":"AVAILABLE","rows":rows}
