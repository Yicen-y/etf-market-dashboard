from scripts.dividend.research_store import read_research_series, record_research_series


def test_research_store_is_idempotent_and_preserves_provider_revisions(tmp_path):
    db = tmp_path / "research.sqlite"
    meta = {"provider": "AkShare", "upstream": "CSI", "unit": "%", "metric": "dividend_yield2"}
    rows = [{"tradeDate": "20261104", "value": 4.23}]
    assert record_research_series(db, "CSI_DIV_YIELD2_000922", rows, meta, "hash-a", "raw/a.json") == 1
    assert record_research_series(db, "CSI_DIV_YIELD2_000922", rows, meta, "hash-a", "raw/a.json") == 0
    revised = [{"tradeDate": "20261104", "value": 4.25}]
    assert record_research_series(db, "CSI_DIV_YIELD2_000922", revised, meta, "hash-b", "raw/b.json") == 1
    history = read_research_series(db, "CSI_DIV_YIELD2_000922", "20261101", "20261105", include_revisions=True)
    current = read_research_series(db, "CSI_DIV_YIELD2_000922", "20261101", "20261105")
    assert len(history) == 2
    assert current == [{"tradeDate": "20261104", "value": 4.25, "availableAt": None, "qualityStatus": "VALID", "provider": "AkShare"}]


def test_research_store_does_not_store_missing_values(tmp_path):
    db = tmp_path / "research.sqlite"
    meta = {"provider": "AkShare", "upstream": "CSI", "unit": "%"}
    assert record_research_series(db, "CSI_DIV_YIELD2_000922", [{"tradeDate": "20261104", "value": None}], meta, "hash", "raw.json") == 0
    assert read_research_series(db, "CSI_DIV_YIELD2_000922", "20261101", "20261105") == []
