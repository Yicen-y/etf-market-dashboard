"""Replay archived prices in an isolated Windows data copy; never use formal data as output.

ETF_DATA_DIR and ETF_TEST_ARCHIVE_DIR must point to separate scratch copies.
This is an offline publication/recovery acceptance, not a live Provider test.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3

from scripts import daily_verified, update_data
from scripts.config import DATA_ROOT, DATABASE_PATH, INDEXES, PRODUCTS
from scripts.data_center import build_data_center
from scripts.fetch_data import FetchResult
from scripts.index_verification import ReferenceHTTPError, migrate
from scripts.snapshot import read_dataset, read_manifest
from scripts.storage import init_reliability_schema


ROOT = DATA_ROOT.resolve()
ARCHIVE = Path(os.environ["ETF_TEST_ARCHIVE_DIR"]).resolve()
FORMAL = Path(__file__).resolve().parents[1] / "data"
if ROOT == FORMAL.resolve() or ARCHIVE == FORMAL.resolve() or ROOT == ARCHIVE:
    raise RuntimeError("scratch copies required; formal data is read-only")
if ".scratch" not in ROOT.parts or ".scratch" not in ARCHIVE.parts:
    raise RuntimeError("both data roots must be under .scratch")

TARGET = "20261116"
OUT = Path(os.environ.get("ETF_TEST_EVIDENCE_DIR", str(ROOT / "acceptance")))
OUT.mkdir(parents=True, exist_ok=True)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _market_hash(connection: sqlite3.Connection, table: str, order: str) -> str:
    rows = connection.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _capture(label: str, result: dict | None = None, error: str | None = None) -> dict:
    manifest = read_manifest(ROOT)
    with sqlite3.connect(DATABASE_PATH) as connection:
        market = {"etf": _market_hash(connection, "etf_prices", "trade_date,product_code"),
                  "index": _market_hash(connection, "index_prices", "trade_date,index_code"),
                  "canonical": _market_hash(connection, "canonical_observations", "symbol,kind,trade_date")}
        counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("etf_prices", "index_prices", "canonical_observations",
                                "raw_observations", "market_price_revisions")}
        releases = connection.execute("SELECT snapshot_id,status FROM release_manifest ORDER BY created_at DESC LIMIT 3").fetchall()
    center = build_data_center(ROOT, DATABASE_PATH)
    h00918 = next(row for row in center["series"] if row["id"] == "index:H00918")
    index_dataset = next(row for row in center["datasets"] if row["id"] == "index_prices")
    return {"phase": label, "result": result, "error": error,
            "snapshot_id": manifest["snapshot_id"],
            "manifest_sha256": _sha(ROOT / "current_manifest.json"),
            "json_sha256": {key: _sha(ROOT / manifest["files"][key]) for key in ("etf", "index")},
            "market_sha256": market, "counts": counts, "release_rows": releases,
            "data_center": {"snapshot_id": center["current_snapshot_id"],
                            "snapshot_database_consistency": center["snapshot_database_consistency"],
                            "series_count": len(center["series"]),
                            "h00918_acquisition_status": h00918["acquisition_status"],
                            "h00918_fetch_error": h00918.get("fetch_error"),
                            "h00918_published_date": h00918.get("published_date"),
                            "index_published_latest": index_dataset.get("latest_trade_date"),
                            "index_metric_latest": index_dataset.get("metric_latest_trade_date"),
                            "last_daily_verification": center.get("last_daily_verification")},
            "strategy_dates": [{key: row[key] for key in ("id", "calculation_date", "status")}
                               for row in center["strategy_calculations"]]}


def _copy_archived_references() -> dict:
    """Copy genuine archived CSI Nov 16 observations into the old scratch DB."""
    copied = {}
    with sqlite3.connect(ARCHIVE / "etf_market.db") as source, sqlite3.connect(DATABASE_PATH) as target:
        source.row_factory = sqlite3.Row
        for code in INDEXES:
            if code in ("480080", "480081"):
                continue
            row = source.execute("""SELECT b.* FROM index_reference_batches b
                JOIN index_reference_observations o ON o.batch_id=b.batch_id
                WHERE b.index_code=? AND o.trade_date=? AND b.status='FETCHED'
                  AND b.provider='CSI official HTTP' ORDER BY b.fetched_at DESC LIMIT 1""",
                (code, TARGET)).fetchone()
            assert row is not None, code
            batch = dict(row)
            raw = ROOT / "verification" / "raw" / f"{batch['raw_sha256']}.json"
            assert raw.is_file() and _sha(raw) == batch["raw_sha256"], code
            batch["raw_path"] = str(raw)
            run = source.execute("SELECT * FROM index_verification_runs WHERE run_id=?", (batch["run_id"],)).fetchone()
            if run:
                target.execute("INSERT OR IGNORE INTO index_verification_runs VALUES (?,?,?,?,?,?)", tuple(run))
            columns = list(batch)
            target.execute(f"INSERT OR REPLACE INTO index_reference_batches ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                           tuple(batch.values()))
            for observation in source.execute("SELECT * FROM index_reference_observations WHERE batch_id=?",
                                              (batch["batch_id"],)):
                target.execute("INSERT OR REPLACE INTO index_reference_observations VALUES (?,?,?,?,?)",
                               tuple(observation))
            copied[code] = {"batch_id": batch["batch_id"], "raw_sha256": batch["raw_sha256"],
                            "raw_path": str(raw)}
    return copied


def main() -> None:
    assert read_manifest(ROOT)["snapshot_id"] == "20261116T194338-32527f07"
    init_reliability_schema(DATABASE_PATH)
    with sqlite3.connect(DATABASE_PATH) as connection:
        migrate(connection)
    archive_manifest = read_manifest(ARCHIVE)
    archive_index = read_dataset(ARCHIVE, archive_manifest, "index")
    archived_index = {(row["indexCode"], row["tradeDate"]): row
                      for row in archive_index["flatRecords"]}
    with sqlite3.connect(ARCHIVE / "etf_market.db") as connection:
        archived_etf = {(code, day): price for day, code, price in connection.execute(
            "SELECT trade_date,product_code,close_price FROM etf_prices")}
    references = _copy_archived_references()
    calendar = json.loads((ROOT / "verification" / "mainland_calendar.json").read_text(encoding="utf-8"))["dates"]
    state = {"etf_failure": None, "etf_revision": None}
    attempts = []

    def etf_fetch(code, start, end, _api_key):
        attempts.append({"kind": "etf", "code": code, "start": start, "end": end})
        if state["etf_failure"] == code:
            raise TimeoutError("fixed-sample provider timeout")
        rows = [{"tradeDate": day, "productCode": code,
                 "closePrice": (price + 0.001 if state["etf_revision"] == (code, day) else price)}
                for (symbol, day), price in archived_etf.items()
                if symbol == code and start <= day <= end]
        rows.sort(key=lambda row: row["tradeDate"])
        return FetchResult(rows, "AkShare", "Eastmoney", {"code": code, "start": start, "end": end},
                           raw_bytes=json.dumps(rows, ensure_ascii=False).encode(),
                           price_basis="UNADJUSTED_CLOSE")

    def index_result(code, start, end, provider, upstream):
        attempts.append({"kind": "index", "code": code, "start": start, "end": end,
                         "provider": provider})
        rows = [dict(row) for (symbol, day), row in archived_index.items()
                if symbol == code and start <= day <= end]
        rows.sort(key=lambda row: row["tradeDate"])
        if code == "H00821" and provider == "ETFirst":
            raw = json.dumps(rows, ensure_ascii=False).encode()
        elif code in references:
            raw = Path(references[code]["raw_path"]).read_bytes()
        else:
            raw = b""
        return FetchResult(rows, provider, upstream, {"code": code, "start": start, "end": end},
                           raw_bytes=raw, price_basis="OFFICIAL_DAILY_CLOSE")

    def official(code, start, end):
        if code == "H00821":
            attempts.append({"kind": "index", "code": code, "start": start, "end": end,
                             "provider": "CSI official HTTP", "outcome": "HTTP_403"})
            raise ReferenceHTTPError(403, "0" * 64, "text/html", request_params={"indexCode": code})
        if code in ("480080", "480081"):
            return FetchResult([], "CNI official HTTPS", "CNI", {"code": code}, raw_bytes=b"{}")
        return index_result(code, start, end, "CSI official HTTP", "CSI")

    def etfirst(code, start, end):
        if code == "H00821":
            return index_result(code, start, end, "ETFirst", "UNDISCLOSED")
        raise ConnectionError("fixed-sample ETFirst unavailable")

    def fallback(*_args):
        raise ConnectionError("fixed-sample fallback unavailable")

    update_data.fetch_product_history = etf_fetch
    update_data.fetch_index_history_official = official
    update_data.fetch_index_history_etfirst = etfirst
    update_data.fetch_index_history = fallback
    update_data.fetch_csi_total_return_history = fallback
    update_data.fetch_exchange_trading_dates = lambda start, end: [day for day in calendar if start <= day <= end]
    update_data.sync_nikkei_anchor = lambda: {"status": "NOT_REQUESTED_OFFLINE_FIXTURE"}

    phases = [_capture("baseline")]
    if os.environ.get("ETF_TEST_INDEX_ONLY") == "1":
        state["etf_failure"] = "510330"
        independent = update_data.update_dataset(end_date=TARGET, index_only=True,
                                                 require_reference_verification=True)
        phases.append(_capture("index_only_during_etf_outage", independent))
        assert independent["publicationStatus"] == "PUBLISHED"
        assert phases[1]["counts"]["etf_prices"] == phases[0]["counts"]["etf_prices"]
        assert phases[1]["counts"]["index_prices"] == phases[0]["counts"]["index_prices"] + 12
        assert not any(attempt["kind"] == "etf" for attempt in attempts)
        assert all(row["status"] == "MATCH" for row in phases[1]["strategy_dates"])
        destination = OUT / "index-only-outage.json"
        destination.write_text(json.dumps({"mode": "OFFLINE_INDEX_ONLY_WITH_ETF_OUTAGE",
                                           "references": references, "attempts": attempts,
                                           "phases": phases}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"result": "PASS", "snapshot": phases[1]["snapshot_id"],
                          "evidence": str(destination)}, ensure_ascii=True))
        return
    first = update_data.update_dataset(end_date=TARGET, require_reference_verification=True)
    phases.append(_capture("first_publish", first))
    assert first["publicationStatus"] == "PUBLISHED"
    second = update_data.update_dataset(end_date=TARGET, require_reference_verification=True)
    phases.append(_capture("same_data_repeat", second))
    assert second["publicationStatus"] == "UNCHANGED"
    assert phases[2]["snapshot_id"] == phases[1]["snapshot_id"]
    assert phases[2]["market_sha256"] == phases[1]["market_sha256"]
    assert phases[2]["json_sha256"] == phases[1]["json_sha256"]
    assert phases[2]["counts"]["market_price_revisions"] == phases[1]["counts"]["market_price_revisions"]

    state["etf_failure"] = "510330"
    try:
        update_data.update_dataset(end_date=TARGET, require_reference_verification=True)
    except TimeoutError as error:
        failure = type(error).__name__
    else:
        raise AssertionError("fixed-source timeout should block publication")
    def one_reference_failure(_db, _root, codes, _mode, **_kwargs):
        if codes == ["H00918"]:
            raise ReferenceHTTPError(403, "0" * 64, "text/html",
                                     request_params={"indexCode": "H00918"})
        return 0
    daily_verified.report = lambda *_args: None
    partial = daily_verified.run_daily(database=DATABASE_PATH, data_root=ROOT,
                                       through=TARGET, publish=False, verifier=one_reference_failure)
    phases.append(_capture("source_failure", {"daily_status": {
        code: item["status"] for code, item in partial["indexes"].items()}}, failure))
    assert phases[3]["snapshot_id"] == phases[2]["snapshot_id"]
    assert phases[3]["market_sha256"] == phases[2]["market_sha256"]
    assert partial["indexes"]["H00918"]["diagnostic"]["http_status"] == 403
    assert phases[3]["data_center"]["h00918_acquisition_status"] == "FAILED"
    assert phases[3]["data_center"]["h00918_published_date"] == TARGET
    assert all(row["status"] == "CHECKED" for code, row in partial["indexes"].items()
               if code != "H00918")

    state["etf_failure"] = None
    state["etf_revision"] = ("510330", TARGET)
    original_activate = update_data.activate_snapshot
    update_data.activate_snapshot = lambda *_args: (_ for _ in ()).throw(OSError("fixed pointer interruption"))
    try:
        update_data.update_dataset(end_date=TARGET, require_reference_verification=True)
    except OSError as error:
        interruption = type(error).__name__
    else:
        raise AssertionError("pointer interruption should stop the updater")
    finally:
        update_data.activate_snapshot = original_activate
    phases.append(_capture("publication_interrupted", error=interruption))
    assert phases[4]["snapshot_id"] == phases[3]["snapshot_id"]
    assert phases[4]["json_sha256"] == phases[3]["json_sha256"]
    assert phases[4]["data_center"]["snapshot_database_consistency"] == "MISMATCH"
    assert any(status == "prepared" for _snapshot, status in phases[4]["release_rows"])
    old = read_dataset(ROOT, read_manifest(ROOT), "etf")
    assert old["snapshot_id"] == phases[3]["snapshot_id"]

    recovered = update_data.update_dataset(end_date=TARGET, require_reference_verification=True)
    daily_verified.run_daily(database=DATABASE_PATH, data_root=ROOT,
                             through=TARGET, publish=False,
                             verifier=lambda *_args, **_kwargs: 0)
    phases.append(_capture("recovered_repeat", recovered))
    assert recovered["publicationStatus"] == "UNCHANGED"
    assert phases[5]["snapshot_id"] != phases[4]["snapshot_id"]
    assert phases[5]["data_center"]["snapshot_database_consistency"] == "MATCH"
    assert phases[5]["data_center"]["h00918_acquisition_status"] == "SUCCEEDED"
    assert phases[5]["counts"]["market_price_revisions"] == phases[4]["counts"]["market_price_revisions"] == 1
    assert all(row["status"] == "MATCH" for phase in phases[1:] for row in phase["strategy_dates"])
    payload = {"mode": "OFFLINE_ARCHIVED_RESPONSE_REPLAY", "references": references,
               "attempts": attempts, "phases": phases}
    destination = OUT / "isolated-cycle.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": "PASS", "phases": [p["phase"] for p in phases],
                      "first_snapshot": phases[1]["snapshot_id"],
                      "recovered_snapshot": phases[5]["snapshot_id"],
                      "evidence": str(destination)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
