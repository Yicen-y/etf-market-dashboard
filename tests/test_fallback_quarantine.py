import pytest

from scripts.fetch_data import FetchResult
from scripts import update_data
from scripts.storage import init_database


@pytest.mark.parametrize("archived,issue_code", [
    (True, "UNVERIFIED_FALLBACK_SOURCE"),
    (False, "MISSING_ARCHIVED_PAYLOAD"),
])
def test_sina_candidate_cannot_replace_published_price(monkeypatch, tmp_path, archived, issue_code):
    monkeypatch.setattr(update_data, "fetch_htbr_closes", lambda *args: (_ for _ in ()).throw(RuntimeError("unavailable")))
    data = tmp_path / "data"
    data.mkdir()
    published = data / "current_manifest.json"
    published.write_text('{"snapshot_id":"trusted"}', encoding="utf-8")
    monkeypatch.setattr(update_data, "DATA_PATH", data / "etf_prices.json")
    monkeypatch.setattr(update_data, "DATABASE_PATH", data / "market.db")
    init_database(data / "market.db")
    monkeypatch.setattr(update_data, "PRODUCTS", {"510330": {}})
    monkeypatch.setattr(update_data, "read_records", lambda _: [])
    monkeypatch.setattr(update_data, "read_index_records", lambda _: [])
    monkeypatch.setattr(update_data, "fetch_product_history", lambda *args: FetchResult(
        rows=[{"tradeDate": "20260105", "productCode": "510330", "closePrice": 9.0}],
        provider="AkShare", upstream="Sina", request={}, raw_bytes=b"candidate"))
    monkeypatch.setattr(update_data, "save_raw_payload", lambda *args: (data / "raw.bin", "hash") if archived else None)
    captured = []
    monkeypatch.setattr(update_data, "record_observations", lambda _, rows: captured.extend(rows))
    monkeypatch.setattr(update_data, "record_quality_issues", lambda _, rows: captured.extend(rows))
    with pytest.raises(ValueError, match="quarantined"):
        update_data.update_dataset(end_date="20260105")
    assert any(row.get("upstream_publisher") == "Sina" for row in captured)
    assert any(row.get("issue_code") == issue_code for row in captured)
    assert published.read_text(encoding="utf-8") == '{"snapshot_id":"trusted"}'
