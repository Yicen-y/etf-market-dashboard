from scripts.bond_value.metrics import build_rows


def test_build_rows_derives_implicit_roe_and_city_earnings_ratio():
    rows = build_rows(
        prices=[{"tradeDate": "20240102", "closeValue": 4000}],
        valuations=[{"tradeDate": "20240102", "pe": 10, "pb": 1}],
        bond_yields=[{"tradeDate": "20240102", "yieldPct": 2.5}],
    )

    row = rows[0]
    assert row["implicitRoePct"] == 10
    assert row["roeSource"] == "PE_PB_IMPLIED"
    assert row["cityEarningsRatio"] == 1
    assert row["earningsYieldPct"] == 10
    assert row["equityBondValuePp"] == 7.5


def test_build_rows_uses_wind_roe_and_previous_available_bond_yield():
    rows = build_rows(
        prices=[{"tradeDate": "20240102", "closeValue": 4000}, {"tradeDate": "20240103", "closeValue": 4050}],
        valuations=[{"tradeDate": "20240102", "pe": 10, "pb": 1}, {"tradeDate": "20240103", "pe": 12, "pb": 1.2}],
        bond_yields=[{"tradeDate": "20240101", "yieldPct": 2.5}],
        roe_by_date={"20240103": 8},
    )

    assert rows[0]["equityBondValuePp"] == 7.5
    assert rows[0]["bondYieldDate"] == "20240101"
    assert rows[1]["cityEarningsRatio"] == 1.5
    assert rows[1]["roeSource"] == "WIND"


def test_build_rows_preserves_missing_values_and_rejects_invalid_pe_pb():
    rows = build_rows(
        prices=[{"tradeDate": "20240102", "closeValue": 4000}],
        valuations=[{"tradeDate": "20240102", "pe": 0, "pb": 1}],
        bond_yields=[],
    )

    assert rows[0]["implicitRoePct"] is None
    assert rows[0]["cityEarningsRatio"] is None
    assert rows[0]["equityBondValuePp"] is None


def test_price_trading_days_define_the_join_calendar():
    rows = build_rows(
        prices=[{"tradeDate": "20240102", "closeValue": 4000}],
        valuations=[
            {"tradeDate": "20240102", "pe": 10, "pb": 1},
            {"tradeDate": "20240103", "pe": 11, "pb": 1.1},
        ],
        bond_yields=[],
    )

    assert [row["tradeDate"] for row in rows] == ["20240102"]
