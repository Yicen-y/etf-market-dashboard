import pytest

from scripts.dividend import research_providers as providers


def test_wind_csi_provider_parses_historical_yield(monkeypatch):
    payload = {"data": {"data": [{"rows": [["000922.CSI", "中证红利", 4.23, "2026-11-04"], ["000922.CSI", "中证红利", 4.19, "2026-11-03"]]}]}}
    monkeypatch.setattr(providers, "_call", lambda *_args, **_kwargs: payload)
    rows, metadata, raw = providers.fetch_csi_dividend_yield2("20261103", "20261104")
    assert rows == [{"tradeDate": "20261103", "value": 4.19}, {"tradeDate": "20261104", "value": 4.23}]
    assert metadata["provider"] == "Wind"
    assert metadata["metric"] == "dividend_yield"
    assert raw


def test_wind_csi_provider_rejects_empty_history(monkeypatch):
    payload = {"data": {"data": [{"rows": []}]}}
    monkeypatch.setattr(providers, "_call", lambda *_args, **_kwargs: payload)
    with pytest.raises(ValueError, match="series is empty"):
        providers.fetch_csi_dividend_yield2("20261103", "20261104")


def test_wind_chinabond_provider_parses_10y_series(monkeypatch):
    payload = {"metrics": [{"date": ["2008-01-02", "2008-01-03"], "value": [4.4363, 4.4263]}]}
    monkeypatch.setattr(providers, "_call", lambda *_args, **_kwargs: payload)
    rows, metadata, raw = providers.fetch_chinabond_10y_yield("20080101", "20080131")
    assert rows == [{"tradeDate": "20080102", "value": 4.4363}, {"tradeDate": "20080103", "value": 4.4263}]
    assert metadata["provider"] == "Wind"
    assert metadata["metricCode"] == "S0059749"
    assert raw


def test_wind_chinabond_provider_rejects_empty_series(monkeypatch):
    monkeypatch.setattr(providers, "_call", lambda *_args, **_kwargs: {"metrics": [{"date": [], "value": []}]})
    with pytest.raises(ValueError, match="series is empty"):
        providers.fetch_chinabond_10y_yield("20080101", "20080131")
