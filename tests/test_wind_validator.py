import sqlite3

import pytest

from scripts.wind_config import load_wind_config
from scripts.wind_validator import compare_index_rows, load_local_index_rows, normalize_wind_rows


def test_config_uses_official_endpoint_and_keeps_unmapped_codes_explicit():
    config = load_wind_config({"WIND_MCP_AUTH": "Bearer hidden"})
    assert config.endpoint == "https://mcp.wind.com.cn/vserver_wind_tools/mcp/"
    assert config.mappings["480080"].wind_code is None
    assert "H20180" in config.mappings


def test_config_supports_endpoint_override_and_requires_auth_for_query():
    config = load_wind_config({"WIND_MCP_URL": "https://example.test/mcp", "WIND_MCP_AUTH": "x"})
    assert config.endpoint == "https://example.test/mcp"
    assert load_wind_config({}).authorization is None


def test_normalize_rows_requires_explicit_schema_and_valid_market_facts():
    from scripts.wind_config import WindIndexMapping
    mapping = WindIndexMapping("H00300", "000300.SH", "沪深300", "price_return")
    rows = normalize_wind_rows({"rows": [{"date": "2026-01-05", "close": 4000}]}, mapping, date_field="date", close_field="close")
    assert rows == [{"tradeDate": "20260105", "indexCode": "H00300", "closeValue": 4000.0}]
    with pytest.raises(ValueError, match="invalid"):
        normalize_wind_rows({"rows": [{"date": "bad", "close": 0}]}, mapping, date_field="date", close_field="close")


def test_compare_uses_exact_date_keys_without_filling_missing_rows():
    result = compare_index_rows({("H00300", "20260105"): 4000}, [
        {"indexCode": "H00300", "tradeDate": "20260105", "closeValue": 4001},
        {"indexCode": "H00300", "tradeDate": "20260106", "closeValue": 4010},
    ])
    assert [r["status"] for r in result] == ["VALUE_MISMATCH", "LOCAL_MISSING"]
    assert result[0]["absoluteDelta"] == 1


def test_local_loader_reads_requested_range_read_only(tmp_path):
    db = tmp_path / "prices.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE index_prices(trade_date TEXT,index_code TEXT,close_value REAL)")
        conn.executemany("INSERT INTO index_prices VALUES (?,?,?)", [("20260105", "H00300", 4000), ("20260106", "H00300", 4010)])
    assert load_local_index_rows(db, "20260105", "20260105") == {("H00300", "20260105"): 4000.0}
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM index_prices").fetchone()[0] == 2
