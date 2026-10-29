from datetime import date

import pandas as pd
import pytest

from scripts.fund_flow.providers.nav_provider import AkshareNavProvider
from scripts.fund_flow.providers.sse_provider import AkshareSSEProvider
from scripts.fund_flow.providers.szse_provider import AkshareSZSEProvider


def test_akshare_sse_maps_share_units_and_source(monkeypatch):
    import akshare as ak

    monkeypatch.setattr(
        ak,
        "fund_etf_scale_sse",
        lambda date: pd.DataFrame(
            [{"基金代码": "510300", "基金简称": "沪深300ETF", "基金份额": "123,456.78"}]
        ),
    )

    rows = AkshareSSEProvider().fetch(["510300.SH"], date(2024, 1, 2), date(2024, 1, 2))

    assert rows[0].total_share == pytest.approx(123456.78)
    assert rows[0].share_unit == "万份"
    assert rows[0].record_date == date(2024, 1, 2)
    assert rows[0].source_id.startswith("akshare:sse")


def test_akshare_szse_converts_source_shares_to_wan(monkeypatch):
    import akshare as ak

    monkeypatch.setattr(
        ak,
        "fund_scale_daily_szse",
        lambda start_date, end_date, symbol: pd.DataFrame(
            [{"日期": "2024-01-02", "基金代码": "159919", "基金简称": "沪深300ETF", "基金份额": 987654321}]
        ),
    )

    rows = AkshareSZSEProvider().fetch(["159919.SZ"], date(2024, 1, 2), date(2024, 1, 2))

    assert rows[0].total_share == pytest.approx(98765.4321)
    assert rows[0].share_unit == "万份"
    assert rows[0].source_id.startswith("akshare:szse")


def test_nav_provider_keeps_unit_nav_independent_from_share_provider(monkeypatch):
    import akshare as ak

    monkeypatch.setattr(
        ak,
        "fund_etf_fund_info_em",
        lambda fund, start_date, end_date: pd.DataFrame(
            [{"净值日期": "2024-01-02", "单位净值": 4.123, "累计净值": 4.123}]
        ),
    )

    rows = AkshareNavProvider().fetch_nav(["510300.SH"], date(2024, 1, 2), date(2024, 1, 2))

    assert rows[0].nav == pytest.approx(4.123)
    assert rows[0].source_id.startswith("akshare:nav")
    assert rows[0].unit == "元/份"

