from datetime import date, timedelta
import json
import math
import sqlite3

import pandas as pd
import pytest

from scripts.fetch_data import FetchResult, fetch_csi_total_return_history, fetch_index_history, fetch_product_history, map_index_frame, recover_zero_close_from_next_change, validate_fetch_result
from scripts.prism_metrics import calculate_prism_metrics, trim_to_analysis_ready
from scripts.storage import init_database, record_observations, publish_snapshot, upsert_market_records_atomic
from scripts.validate_data import validate_index_records, validate_records


def test_bad_index_zero_is_blocked_and_preserved_as_issue():
    rows = [{"tradeDate": "20130628", "indexCode": "H20180", "closeValue": 0.0}]
    errors = validate_index_records(rows, {"H20180"})
    assert any("invalid closeValue" in error for error in errors)


def test_csi_zero_close_is_recovered_from_next_official_absolute_change():
    frame = pd.DataFrame([
        {"日期": date(2013, 6, 27), "收盘": 4130.47, "涨跌": math.nan},
        {"日期": date(2013, 6, 28), "收盘": 0.0, "涨跌": 0.0},
        {"日期": date(2013, 7, 1), "收盘": 4283.64, "涨跌": -20.35},
    ])

    repaired = recover_zero_close_from_next_change(frame, "H20180")

    assert repaired.loc[1, "收盘"] == pytest.approx(4303.99)
    assert repaired.loc[1, "数据状态"] == "RECOVERED_FROM_NEXT_DAY_ABSOLUTE_CHANGE"


def test_csi_fetch_makes_upstream_exclusive_end_date_inclusive(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scripts.fetch_data.ak.stock_zh_index_hist_csindex",
        lambda **kwargs: calls.append(kwargs) or pd.DataFrame([
            {"日期": date(2013, 7, 1), "收盘": 4283.64, "涨跌": -20.35},
        ]),
    )

    result = fetch_csi_total_return_history("H20180", "20130628", "20130701")

    assert calls[0]["end_date"] == "20130702"
    assert result.rows == [{"tradeDate": "20130701", "indexCode": "H20180", "closeValue": 4283.64}]


def test_cni_empty_upstream_length_mismatch_is_an_empty_fetch(monkeypatch):
    def empty_response(**_kwargs):
        raise ValueError("Length mismatch: Expected axis has 0 elements, new values have 11 elements")

    monkeypatch.setattr("scripts.fetch_data.ak.index_hist_cni", empty_response)

    result = fetch_index_history("480080", "20261031", "20261102")

    assert isinstance(result, FetchResult)
    assert result.rows == []
    assert result.request == {
        "index_code": "480080",
        "start_date": "20261031",
        "end_date": "20261102",
    }


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), float("-inf"), "NaN"])
def test_finite_positive_values_are_required(value):
    errors = validate_records([{"tradeDate": "20260105", "productCode": "510330", "closePrice": value}], {"510330"})
    assert any("invalid closePrice" in error for error in errors)


def test_fetch_fallback_honors_start_date(monkeypatch):
    import akshare as ak

    calls = []
    monkeypatch.setattr("scripts.fetch_data.discover_start_date", lambda *_: "20180101")
    monkeypatch.setattr(
        ak,
        "fund_etf_hist_em",
        lambda **kwargs: calls.append(kwargs) or pd.DataFrame([{"日期": "20260105", "收盘": 1.2}]),
    )
    result = fetch_product_history("512530", "20260105", "20260105")
    assert isinstance(result, FetchResult)
    assert calls[0]["start_date"] == "20260105"


def test_empty_fetch_requires_calendar_check():
    empty = FetchResult(rows=[], provider="AkShare", upstream="Eastmoney", request={"start_date": "20260105", "end_date": "20260105"})
    with pytest.raises(ValueError, match="empty response"):
        validate_fetch_result(empty, date(2026, 1, 5), date(2026, 1, 5), expected_trading_days=1)
    holiday = FetchResult(rows=[], provider="AkShare", upstream="Eastmoney", request={"start_date": "20260101", "end_date": "20260101"})
    validate_fetch_result(holiday, date(2026, 1, 1), date(2026, 1, 1), expected_trading_days=0)


def test_provider_schema_change_blocks_instead_of_using_column_position():
    frame = pd.DataFrame([{"日期": "2026-01-05", "错误列": 99, "收盘": 1.23}])
    result = map_index_frame(frame, "H00300", "AkShare", "CSI")
    assert result.rows[0]["closeValue"] == 1.23
    with pytest.raises(ValueError, match="schema"):
        map_index_frame(pd.DataFrame([["2026-01-05", 99, 1.23]], columns=["日期", "错误列", "未知"]), "H00300", "AkShare", "CSI")


def test_raw_provenance_is_truthful_and_unknown_legacy_is_not_akshare(tmp_path):
    path = tmp_path / "data.db"
    init_database(path)
    record_observations(path, [{"symbol": "510330", "kind": "etf", "trade_date": "2026-01-05", "value_raw": "1.2", "unit_raw": "元/份", "provider": "ETFirst", "upstream_publisher": "ETFirst", "raw_sha256": "abc", "fetch_batch_id": "b1"}])
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO etf_prices(trade_date,product_code,close_price,source,updated_at) VALUES ('2020-01-01','510330',1.0,'akshare','x')")
        row = conn.execute("SELECT provider FROM raw_observations WHERE symbol='510330'").fetchone()
    assert row[0] == "ETFirst"


def test_rsi_missing_breaks_chain_and_flat_series_is_fifty():
    rows = [
        {"tradeDate": "20260101", "values": {"480080": 100, "480081": 100}},
        {"tradeDate": "20260102", "values": {}},
        {"tradeDate": "20260103", "values": {"480080": 100, "480081": 100}},
    ]
    result = calculate_prism_metrics(rows)
    assert result[2]["rsi14"] is None
    flat = [{"tradeDate": f"2026-01-{i:02d}", "values": {"480080": 100, "480081": 100}} for i in range(1, 18)]
    assert calculate_prism_metrics(flat)[-1]["rsi14"] == 50.0


def test_analysis_ready_slice_removes_only_leading_warmup():
    rows = [
        {"tradeDate": f"2025{i:04d}", "values": {"A": 100 + i, "B": 200 + i}}
        for i in range(1, 330)
    ]
    metrics = calculate_prism_metrics(rows, "A", "B")

    ready = trim_to_analysis_ready(metrics)

    assert ready
    assert all(ready[0][field] is not None for field in ("ratioMa242", "return40Ma242", "rsi14", "rsiMa242"))
    assert ready[-1]["tradeDate"] == metrics[-1]["tradeDate"]


def test_40d_calendar_endpoint_does_not_use_40th_array_row():
    rows = []
    trading_dates = []
    current = date(2026, 1, 1)
    while len(rows) < 60:
        if current.weekday() < 5:
            trading_dates.append(current.isoformat())
            if current != date(2026, 1, 15):
                rows.append({"tradeDate": current.isoformat(), "values": {"480080": 100 + len(rows), "480081": 100}})
        current += timedelta(days=1)
    result = calculate_prism_metrics(rows, trading_dates=trading_dates)
    missing_index = trading_dates.index("2026-01-15")
    assert result[missing_index]["return40Spread"] is None
    assert result[missing_index]["return40CoverageStatus"] == "INSUFFICIENT_HISTORY"
    assert result[missing_index + 40]["return40Spread"] is None
    assert result[missing_index + 40]["return40CoverageStatus"] == "MISSING_ENDPOINT"
    assert result[40]["return40Spread"] is not None
    assert result[40]["return40CoverageStatus"] == "INTERMEDIATE_GAP"


def test_publishing_is_atomic_when_json_write_fails(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    current = root / "current_manifest.json"
    current.write_text(json.dumps({"snapshot_id": "old"}), encoding="utf-8")
    with pytest.raises(RuntimeError):
        publish_snapshot(root, "new", {"records": []}, {"records": []}, fail_at="json")
    assert json.loads(current.read_text(encoding="utf-8"))["snapshot_id"] == "old"


def test_sqlite_failure_rolls_back_both_market_tables(tmp_path):
    path = tmp_path / "market.db"
    upsert_market_records_atomic(path, [{"tradeDate": "2026-01-05", "productCode": "510330", "closePrice": 1.0}], [], "old")
    with pytest.raises(sqlite3.OperationalError):
        upsert_market_records_atomic(path, [{"tradeDate": "2026-01-06", "productCode": "510330", "closePrice": 2.0}], [{"tradeDate": "2026-01-06", "indexCode": "H00300", "closeValue": 100.0}], "new", fail_at="sqlite")
    with sqlite3.connect(path) as connection:
        assert connection.execute("select count(*) from etf_prices where trade_date='2026-01-06'").fetchone()[0] == 0
        assert connection.execute("select count(*) from index_prices where trade_date='2026-01-06'").fetchone()[0] == 0
