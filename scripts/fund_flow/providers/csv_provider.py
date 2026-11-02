from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
import csv
import io
import json
from pathlib import Path
from typing import BinaryIO
import uuid

from ..db import init_fund_flow_schema, open_fund_flow_connection, seed_default_fund_master
from ..models import ImportJob, RawETFRecord
from .base import ProviderSchemaError, as_exchange_code, as_float, now_iso, parse_date


@dataclass(frozen=True)
class ImportPreview:
    source_id: str
    rows: list[RawETFRecord]
    field_mapping: dict[str, str]
    warnings: list[str]
    errors: list[str]
    source_url: str | None = None


def _field(row: dict[str, str], *names: str) -> str | None:
    for name in names:
        if name in row and row[name] is not None and row[name].strip() != "":
            return row[name].strip()
    return None


def _code(value: str) -> str:
    code = value.strip().upper()
    if "." in code:
        return code
    exchange = "SZ" if code.startswith("15") else "SH"
    return as_exchange_code(code, exchange)


def _shares(row: dict[str, str]) -> tuple[float, str]:
    if _field(row, "total_share_wan", "份额(万份)") is not None:
        return as_float(_field(row, "total_share_wan", "份额(万份)"), "total_share_wan"), "万份"
    raw = _field(row, "total_share", "基金份额", "shares")
    unit = _field(row, "share_unit", "份额单位")
    if raw is None or unit not in {"份", "万份", "亿份"}:
        raise ProviderSchemaError("total_share and a known share_unit are required")
    value = as_float(raw, "total_share")
    return value / {"份": 10000, "万份": 1, "亿份": 10000}[unit], "万份"


def _size_yi(row: dict[str, str]) -> float | None:
    raw = _field(row, "total_size_yi", "资产规模(亿元)")
    if raw is not None:
        return as_float(raw, "total_size_yi")
    raw = _field(row, "total_size", "total_size_wan", "资产规模")
    if raw is None:
        return None
    unit = _field(row, "total_size_unit", "资产规模单位") or "万元"
    if unit not in {"万元", "亿元"}:
        raise ProviderSchemaError("unknown total_size_unit")
    value = as_float(raw, "total_size")
    return value / 10000 if unit == "万元" else value


def parse_csv(file: BinaryIO, source_id: str) -> ImportPreview:
    if not source_id.strip():
        raise ValueError("source_id is required")
    text = file.read().decode("utf-8-sig")
    # Allow a leading human-readable provenance comment in sample/import files
    # without treating it as the CSV header.
    csv_text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    reader = csv.DictReader(io.StringIO(csv_text))
    rows: list[RawETFRecord] = []
    errors: list[str] = []
    warnings: list[str] = []
    mapping: dict[str, str] = {}
    for line_number, row in enumerate(reader, start=2):
        try:
            code_raw = _field(row, "ts_code", "etf_code", "基金代码")
            day_raw = _field(row, "trade_date", "record_date", "日期")
            if not code_raw or not day_raw:
                raise ProviderSchemaError("ts_code and trade_date are required")
            code = _code(code_raw)
            day = parse_date(day_raw)
            shares, unit = _shares(row)
            nav_raw = _field(row, "nav", "单位净值")
            nav = None if nav_raw is None else as_float(nav_raw, "nav")
            if nav is not None and nav <= 0:
                raise ProviderSchemaError("nav must be positive")
            close_raw = _field(row, "close", "收盘")
            close = None if close_raw is None else as_float(close_raw, "close")
            rows.append(
                RawETFRecord(
                    etf_code=code,
                    record_date=day,
                    effective_trade_date=day,
                    published_at=now_iso(),
                    total_share=shares,
                    share_unit=unit,
                    share_scope=_field(row, "share_scope", "份额口径") or "unknown",
                    share_date_basis=_field(row, "share_date_basis", "日期口径") or "unknown",
                    nav=nav,
                    close=close,
                    total_size=_size_yi(row),
                    source_id=source_id,
                    source_version="csv",
                    import_batch_id=f"batch-{source_id}",
                )
            )
            for key in ("ts_code", "trade_date", "total_share_wan", "nav"):
                if key in row:
                    mapping[key] = key
        except (ProviderSchemaError, ValueError) as exc:
            errors.append(f"line {line_number}: {exc}")
    source_url = None
    if rows:
        first_row = next(csv.DictReader(io.StringIO(csv_text)), {})
        source_url = _field(first_row, "source_url", "来源URL")
    return ImportPreview(source_id, rows, mapping, warnings, errors, source_url)


def commit_import(preview: ImportPreview, db_path: Path) -> ImportJob:
    if preview.errors:
        raise ValueError("cannot commit invalid import preview: " + "; ".join(preview.errors))
    init_fund_flow_schema(db_path)
    seed_default_fund_master(db_path)
    job_id = preview.rows[0].import_batch_id if preview.rows else f"batch-{uuid.uuid4().hex}"
    with open_fund_flow_connection(db_path) as connection:
        with connection:
            connection.execute(
                """INSERT INTO fund_flow_data_sources
                   (source_id,url,retrieved_at,field_mapping,row_count)
                   VALUES (?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
                   url=excluded.url,retrieved_at=excluded.retrieved_at,
                   field_mapping=excluded.field_mapping,row_count=excluded.row_count""",
                (preview.source_id, preview.source_url, now_iso(), json.dumps(preview.field_mapping, ensure_ascii=False), len(preview.rows)),
            )
            connection.execute(
                "INSERT OR REPLACE INTO fund_flow_import_jobs(import_batch_id,source_id,status,started_at,finished_at) VALUES (?,?,?,?,?)",
                (job_id, preview.source_id, "completed", now_iso(), now_iso()),
            )
            for record in preview.rows:
                values = asdict(record)
                values["record_date"] = values["record_date"].isoformat()
                values["effective_trade_date"] = values["effective_trade_date"].isoformat()
                connection.execute(
                    """INSERT OR REPLACE INTO fund_flow_etf_daily_raw
                       (etf_code,record_date,effective_trade_date,published_at,total_share,share_unit,
                        share_scope,share_date_basis,nav,close,total_size,source_id,source_version,import_batch_id)
                       VALUES (:etf_code,:record_date,:effective_trade_date,:published_at,:total_share,:share_unit,
                        :share_scope,:share_date_basis,:nav,:close,:total_size,:source_id,:source_version,:import_batch_id)""",
                    values,
                )
    return ImportJob(job_id, preview.source_id, "completed")


class CsvProvider:
    def get_daily(self, codes: list[str], start: date, end: date):
        raise NotImplementedError("CSV provider is used through parse_csv/commit_import")

