"""Ingest official dividend research series with immutable raw payloads."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import argparse
from pathlib import Path
from typing import Callable

from scripts.dividend.research_providers import fetch_csi_dividend_yield2, fetch_chinabond_10y_yield
from scripts.dividend.research_store import record_research_series


DEFAULT_RESEARCH_START_DATE = "20080101"


def _save_raw(data_root: Path, series_id: str, payload: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(payload).hexdigest()
    relative = Path("raw") / "research" / series_id.lower() / f"{digest}.json"
    target = data_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(payload)
    return relative.as_posix(), digest


def sync_research_sources(db_path: Path, data_root: Path, start_date: str, end_date: str, *,
                          csi_fetcher: Callable | None = None, ccdc_fetcher: Callable | None = None) -> dict:
    """Fetch both independent sources; a failure in one does not discard the other."""
    csi_fetcher = csi_fetcher or fetch_csi_dividend_yield2
    ccdc_fetcher = ccdc_fetcher or fetch_chinabond_10y_yield
    output = {"startedAt": datetime.now(timezone.utc).isoformat(), "range": {"start": start_date, "end": end_date},
              "sources": {}, "inserted": {}}
    for series_id, fetch in (("CSI_DIV_YIELD2_000922", lambda: csi_fetcher(start_date, end_date)),
                             ("CCDC_CN10Y", lambda: ccdc_fetcher(start_date, end_date))):
        try:
            rows, metadata, raw = fetch()
            if not raw:
                raise ValueError("empty raw source payload; refusing to record unauditable observations")
            raw_ref, digest = _save_raw(data_root, series_id, raw)
            inserted = record_research_series(db_path, series_id, rows, metadata, digest, raw_ref)
            output["sources"][series_id] = {"status": "READY", "rowCount": len(rows),
                                                  "sourceHash": digest, "rawPayloadRef": raw_ref,
                                                  "provider": metadata.get("provider"), "upstream": metadata.get("upstream"),
                                                  "sourceUrl": metadata.get("sourceUrl"), "unit": metadata.get("unit")}
            output["inserted"][series_id] = inserted
        except Exception as exc:  # independently report each provider failure
            output["sources"][series_id] = {"status": "FAILED", "error": str(exc)}
            output["inserted"][series_id] = 0
    output["completedAt"] = datetime.now(timezone.utc).isoformat()
    output["status"] = "READY" if all(v["status"] == "READY" for v in output["sources"].values()) else "PARTIAL"
    return output


def export_sync_report(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="增量采集中证红利股息率2和中债国债10年收益率")
    parser.add_argument("--start", help="开始日期 YYYYMMDD；默认回填近五年")
    parser.add_argument("--end", help="结束日期 YYYYMMDD；默认今天")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args(argv)
    from scripts.config import DATABASE_PATH, ROOT
    end = args.end or datetime.now().strftime("%Y%m%d")
    start = args.start or DEFAULT_RESEARCH_START_DATE
    result = sync_research_sources(args.database or DATABASE_PATH, args.data_root or ROOT / "data", start, end)
    report_path = (args.data_root or ROOT / "data") / "research" / "last_sync.json"
    export_sync_report(report_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Report: {report_path}")
    return 0 if any(item["status"] == "READY" for item in result["sources"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

