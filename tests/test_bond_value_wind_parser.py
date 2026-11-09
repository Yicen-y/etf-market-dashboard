from scripts.bond_value import service


def test_wind_valuation_parser_handles_chinese_daily_columns(monkeypatch):
    payload = {
        "data": {"data": [{
            "columns": [
                {"name": "Wind代码"},
                {"name": "2026年10月30日至2026年11月6日每日的市盈率"},
                {"name": "日期"},
                {"name": "每日的市净率"},
            ],
            "rows": [["000300.SH", 12.8654, "2026-10-30", 1.3461]],
        }]},
        "error": None,
    }
    monkeypatch.setattr(service, "_mcp_call", lambda *args, **kwargs: payload)

    result = service._fetch_wind_valuations("2026-10-30", "2026-11-06")

    assert result == [{"tradeDate": "20261030", "pe": 12.8654, "pb": 1.3461}]


def test_wind_parser_prefers_populated_rows_over_empty_nested_table():
    payload = {
        "data": {
            "columns": [{"name": "TIME"}, {"name": "MATCH"}],
            "rows": [["2026-11-06T00:00:00+08:00", "4054.28"]],
            "data": [{"columns": [{"name": "TIME"}], "rows": []}],
        },
        "error": None,
    }

    columns, rows = service._rows(payload)

    assert columns[1]["name"] == "MATCH"
    assert rows == [["2026-11-06T00:00:00+08:00", "4054.28"]]
