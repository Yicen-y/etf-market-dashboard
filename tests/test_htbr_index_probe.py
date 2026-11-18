import hashlib
import json

import pytest

from scripts.htbr_index_probe import reassess_saved_report
from scripts.htbr_index_report import build_report


def test_saved_vendor_precision_and_response_hash(tmp_path):
    raw = tmp_path / "response.json"
    raw.write_bytes(b'{"success":true}')
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    probe = tmp_path / "probe-test.json"
    probe.write_text(json.dumps({
        "created_at": "2026-11-15T00:00:00+00:00",
        "evidence": [{"api_id":"index-daily-quote","raw_path":str(raw),"raw_sha256":digest,
                      "data_source":"gildata-jydb"}],
        "results": {"480080": {"mapping":{"secuCode":"480080"},"basic_info":{},
            "points":[{"trade_date":"20261111","local_close":9612.4862,
                       "reference_close":9612.49,"status":"MISMATCH"}]}}
    }), encoding="utf-8")
    reassessed = reassess_saved_report(probe)
    assert reassessed["results"]["480080"]["counts"]["MATCH"] == 1
    summary = build_report(tmp_path)
    assert summary["indexes"]["480080"]["counts"]["MATCH"] == 1
    assert summary["quote_data_sources"] == ["gildata-jydb"]
    raw.write_bytes(b"changed")
    with pytest.raises(ValueError,match="hash mismatch"):
        build_report(tmp_path)
