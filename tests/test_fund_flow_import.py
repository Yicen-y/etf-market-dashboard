import io

import pytest

from scripts.fund_flow.providers.csv_provider import commit_import, parse_csv


def test_csv_preview_normalizes_wan_and_yyyy_mm_dd():
    csv_text = (
        "trade_date,ts_code,total_share_wan,nav,close,total_size_wan,"
        "share_scope,share_date_basis,source_url\n"
        "2024-01-02,510300.SH,100000,4.0,,400000,on_exchange,post_close,https://example.test\n"
    )

    preview = parse_csv(io.BytesIO(csv_text.encode()), source_id="test-csv")

    assert preview.errors == []
    assert preview.rows[0].total_share == 100000
    assert preview.rows[0].record_date.isoformat() == "2024-01-02"
    assert preview.rows[0].share_scope == "on_exchange"


def test_csv_preview_rejects_unknown_unit_and_keeps_blank_nav():
    csv_text = (
        "trade_date,ts_code,total_share,share_unit,nav\n"
        "2024-01-02,510300.SH,100,箱,\n"
    )

    preview = parse_csv(io.BytesIO(csv_text.encode()), source_id="test-csv")

    assert preview.errors
    assert any("share_unit" in error for error in preview.errors)
    assert preview.rows == []


def test_sample_provenance_comment_is_ignored():
    from pathlib import Path

    sample = Path("data/samples/fund_flow_demo.csv").read_bytes()
    preview = parse_csv(io.BytesIO(sample), source_id="sample")
    assert preview.errors == []
    assert preview.rows[0].record_date.isoformat() == "2099-01-04"
    assert preview.source_url == "SIMULATED"


def test_commit_import_is_transactional_and_creates_source(tmp_path):
    csv_text = (
        "trade_date,ts_code,total_share_wan,nav,share_scope,share_date_basis\n"
        "2024-01-02,510300.SH,100000,4.0,on_exchange,post_close\n"
    )
    preview = parse_csv(io.BytesIO(csv_text.encode()), source_id="test-csv")

    job = commit_import(preview, tmp_path / "flow.db")

    assert job.status == "completed"

