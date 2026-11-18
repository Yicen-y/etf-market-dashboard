import pytest

from scripts.fetch_data import FetchResult
from scripts.providers import DataProviderManager, LegacyEtfAdapter, etf_close_request


def test_etf_request_has_explicit_basis_and_keeps_actual_upstream():
    calls = []

    def legacy(code, start, end, api_key):
        calls.append((code, start, end, api_key))
        return FetchResult([{"tradeDate": end, "productCode": code, "closePrice": 1.0}],
                           "AkShare", "Sina", {"code": code}, price_basis="UNKNOWN")

    manager = DataProviderManager([LegacyEtfAdapter(legacy)])
    result = manager.fetch("akshare_etf_history", etf_close_request("512530", "20261111", "20261112"))
    assert calls == [("512530", "20261111", "20261112", None)]
    assert result.upstream == "Sina"
    assert result.price_basis == "UNKNOWN"  # fetch success cannot grant publication permission


def test_provider_rejects_wrong_basis_and_opens_circuit_after_transport_failures():
    valid = etf_close_request("512530", "20261111", "20261112")
    with pytest.raises(ValueError, match="unsupported"):
        from dataclasses import replace
        replace(valid, adjustment="total_return")

    def timeout(*_):
        raise TimeoutError("unreachable")

    manager = DataProviderManager([LegacyEtfAdapter(timeout)])
    for _ in range(3):
        with pytest.raises(TimeoutError):
            manager.fetch("akshare_etf_history", valid)
    with pytest.raises(ConnectionError, match="circuit"):
        manager.fetch("akshare_etf_history", valid)
