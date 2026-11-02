from datetime import date

import pytest

from scripts.fund_flow.models import CleanETFRecord
from scripts.fund_flow.services.flows import aggregate_selected_etfs, calculate_daily_metric, calculate_series


def clean(code, day, shares, nav, size=None, status="PASS"):
    derived_size = None if shares is None or nav is None else shares * nav / 10000
    return CleanETFRecord(code, day, shares, nav, size if size is not None else derived_size, "on_exchange", status, (), "test")


def test_daily_flow_uses_wan_shares_and_nav():
    metric = calculate_daily_metric(clean("510300.SH", "2024-01-03", 110, 4), clean("510300.SH", "2024-01-02", 100, 4), "PASS")
    assert metric.delta_shares_wan == pytest.approx(10)
    assert metric.net_flow_yi == pytest.approx(0.004)


def test_missing_nav_blocks_flow_without_zero_fill():
    metric = calculate_daily_metric(clean("510300.SH", "2024-01-03", 110, None), clean("510300.SH", "2024-01-02", 100, 4), "BLOCKED")
    assert metric.net_flow_yi is None
    assert metric.status == "BLOCKED"


def test_multi_etf_aggregate_sums_money_not_shares():
    metrics = [
        calculate_daily_metric(clean("510300.SH", "2024-01-03", 110, 4), clean("510300.SH", "2024-01-02", 100, 4), "PASS"),
        calculate_daily_metric(clean("510310.SH", "2024-01-03", 220, 6), clean("510310.SH", "2024-01-02", 200, 6), "PASS"),
    ]
    result = aggregate_selected_etfs(metrics, ["510300.SH", "510310.SH"], date(2024, 1, 3), date(2024, 1, 3))
    assert result[0]["net_flow_yi"] == pytest.approx(0.004 + 0.012)
    assert result[0]["coverage_codes"] == ["510300.SH", "510310.SH"]


def test_first_observation_is_zero_base_not_fake_flow():
    result = calculate_series([clean("510300.SH", "2024-01-02", 100, 4)], [], date(2024, 1, 1), date(2024, 1, 3))
    assert result[0].net_flow_yi is None
    assert result[0].cum_flow_yi == 0


def test_series_uses_previous_observation_before_requested_start():
    result = calculate_series(
        [clean("510300.SH", "2023-12-29", 100, 4), clean("510300.SH", "2024-01-02", 110, 4)],
        [], date(2024, 1, 1), date(2024, 1, 3),
    )
    assert result[0].net_flow_yi == pytest.approx(0.004)
    assert result[0].cum_flow_yi == pytest.approx(0.004)


def test_blocked_gap_does_not_create_flow_from_invalid_previous_row():
    result = calculate_series(
        [clean("510300.SH", "2024-01-02", 100, 4), clean("510300.SH", "2024-01-03", 120, None), clean("510300.SH", "2024-01-04", 130, 4)],
        [], date(2024, 1, 1), date(2024, 1, 5),
    )
    assert result[1].net_flow_yi is None
    assert result[2].net_flow_yi is None
