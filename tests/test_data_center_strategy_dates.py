"""Published strategy dates must be supported by both input calendars."""

from scripts.data_center import strategy_calculations


def _row(code, day):
    return {"indexCode": code, "tradeDate": day, "closeValue": 1000.0}


def test_strategy_dates_expose_common_cutoff_and_do_not_claim_a_later_metric():
    payload = {
        "flatRecords": [_row("480080", "20261113"), _row("480081", "20261113"),
                        _row("H00821", "20261113"), _row("H00821", "20261116"),
                        _row("H00300", "20261113")],
        "records": [{"tradeDate": "20261113"}],
        "strategyMetrics": {"dividend-hs300": [{"tradeDate": "20261113"}]},
        "strategyInputStatus": {"dividend-hs300": {
            "inputDates": {"H00821": "20261116", "H00300": "20261113"},
            "effectiveDate": "20261113", "status": "LAGGING_INPUT"}},
    }
    rows = {item["id"]: item for item in strategy_calculations(payload, "snapshot-1")}
    assert rows["prism"]["calculation_date"] == "20261113"
    assert rows["prism"]["status"] == "MATCH"
    assert rows["dividend-hs300"]["input_dates"] == {"H00821": "20261116", "H00300": "20261113"}
    assert rows["dividend-hs300"]["common_date"] == "20261113"
    assert rows["dividend-hs300"]["status"] == "MATCH"
    payload["strategyMetrics"]["dividend-hs300"].append({"tradeDate": "20261116"})
    conflict = next(item for item in strategy_calculations(payload, "snapshot-1")
                    if item["id"] == "dividend-hs300")
    assert conflict["status"] == "INPUT_DATE_CONFLICT"
    assert conflict["out_of_calendar_rows"] == 1


def test_strategy_dates_detect_stale_claim_even_with_valid_metric_rows():
    payload = {"flatRecords": [_row("H00821", "20261116"), _row("H00300", "20261116")],
               "strategyMetrics": {"dividend-hs300": [{"tradeDate": "20261116"}]},
               "strategyInputStatus": {"dividend-hs300": {
                   "inputDates": {"H00821": "20261113", "H00300": "20261116"},
                   "effectiveDate": "20261116"}}}
    row = next(item for item in strategy_calculations(payload, "snapshot-2")
               if item["id"] == "dividend-hs300")
    assert row["status"] == "INPUT_DATE_CONFLICT"
