import hashlib

from scripts.dividend.research_sync import sync_research_sources
from scripts.dividend.research_store import read_research_series


def test_sync_persists_source_payload_hash_and_is_idempotent(tmp_path):
    db = tmp_path / "market.sqlite"
    raw_root = tmp_path / "data"

    def csi(*_args, **_kwargs):
        return ([{"tradeDate": "20261104", "value": 4.23}],
                {"provider": "Wind", "upstream": "Wind/CSI", "sourceUrl": "https://example.test/csi", "unit": "%"},
                b"official-csi-xls-sample")

    def ccdc(start, end):
        return ([{"tradeDate": "20261104", "value": 1.63}],
                {"provider": "Wind", "upstream": "Wind/ChinaBond", "sourceUrl": "https://example.test/ccdc", "unit": "%"},
                b"official-ccdc-sample")

    first = sync_research_sources(db, raw_root, "20261104", "20261104", csi_fetcher=csi, ccdc_fetcher=ccdc)
    second = sync_research_sources(db, raw_root, "20261104", "20261104", csi_fetcher=csi, ccdc_fetcher=ccdc)
    assert first["inserted"] == {"CSI_DIV_YIELD2_000922": 1, "CCDC_CN10Y": 1}
    assert second["inserted"] == {"CSI_DIV_YIELD2_000922": 0, "CCDC_CN10Y": 0}
    assert first["sources"]["CSI_DIV_YIELD2_000922"]["sourceHash"] == hashlib.sha256(b"official-csi-xls-sample").hexdigest()
    ref = first["sources"]["CSI_DIV_YIELD2_000922"]["rawPayloadRef"]
    assert (raw_root / ref).read_bytes() == b"official-csi-xls-sample"
    assert read_research_series(db, "CSI_DIV_YIELD2_000922", "20261104", "20261104")[0]["value"] == 4.23


def test_source_failure_does_not_prevent_other_provider_sync(tmp_path):
    def broken(**_):
        raise RuntimeError("CSI offline")

    def ccdc(start, end):
        return ([{"tradeDate": "20261104", "value": 1.63}],
                {"provider": "Wind", "upstream": "Wind/ChinaBond", "unit": "%"}, b"ccdc")

    result = sync_research_sources(tmp_path / "db.sqlite", tmp_path / "data", "20261104", "20261104",
                                   csi_fetcher=broken, ccdc_fetcher=ccdc)
    assert result["sources"]["CSI_DIV_YIELD2_000922"]["status"] == "FAILED"
    assert result["sources"]["CCDC_CN10Y"]["status"] == "READY"
    assert read_research_series(tmp_path / "db.sqlite", "CCDC_CN10Y", "20261104", "20261104")

