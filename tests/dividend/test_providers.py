from datetime import date
from decimal import Decimal

import pandas as pd

from scripts.dividend.providers import normalize_etf_quotes, normalize_stock_dividends, normalize_etf_dividends
from scripts.dividend.providers import fetch_quotes_with_fallback


def test_normalize_etf_quotes_uses_unadjusted_close_and_trade_date():
    frame = pd.DataFrame([['2026-01-21', 3.10], ['2026-01-22', 3.12]], columns=['日期', '收盘'])
    rows = normalize_etf_quotes(frame, 'ETF:510880')
    assert rows == [('ETF:510880', date(2026, 1, 21), Decimal('3.10')), ('ETF:510880', date(2026, 1, 22), Decimal('3.12'))]


def test_normalize_stock_dividend_converts_per_ten_cash_to_per_share():
    frame = pd.DataFrame([['2026-06-22', 280.242, '实施', '2026-06-26', '2026-06-25']], columns=['公告日期', '派息', '方案', '除权除息日', '股权登记日'])
    rows = normalize_stock_dividends(frame, 'STOCK:600519')
    assert rows[0]['amount_per_unit'] == Decimal('28.02420')
    assert rows[0]['ex_date'] == date(2026, 6, 26)
    assert rows[0]['status'] == 'PAID'


def test_quotes_fallback_records_secondary_provider(monkeypatch):
    class FakeAk:
        def fund_etf_hist_em(self, *args):
            raise RuntimeError('eastmoney blocked')
        def fund_etf_hist_sina(self, *args):
            return pd.DataFrame([['2026-01-21', 3.1]], columns=['日期', '收盘'])
    monkeypatch.setitem(__import__('sys').modules, 'akshare', FakeAk())
    rows, provider, errors = fetch_quotes_with_fallback('ETF:510880', '20260101', '20260131')
    assert rows[0][2] == Decimal('3.10000')
    assert provider == 'akshare:sina'
    assert 'eastmoney blocked' in errors[0]


def test_normalize_etf_dividends_turns_cumulative_distribution_into_events():
    frame = pd.DataFrame([["2025-01-10", 0.10], ["2026-01-21", 0.243]], columns=['日期', '累计分红'])
    rows = normalize_etf_dividends(frame, 'ETF:510880')
    assert rows[-1]['amount_per_unit'] == Decimal('0.14300')
    assert rows[-1]['status'] == 'PAID'
