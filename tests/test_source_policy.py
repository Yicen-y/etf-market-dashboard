import sqlite3

from scripts.source_policy import compare_backup, load_backup_policy, trusted_primary_overlaps
from scripts.storage import corroborating_raw_matches, init_reliability_schema, record_canonical_observations, record_observations, save_raw_payload


def _candidate(prices):
    return [{"tradeDate": f"2026010{i}", "productCode": "510330", "closePrice": value}
            for i, value in enumerate(prices, 1)]


def test_same_basis_backup_requires_overlap_and_both_price_and_return_checks():
    primary = {row["tradeDate"]: row["closePrice"] for row in _candidate([1, 1.01, 1.02, 1.03, 1.04])}
    policy = {"price_basis": "UNADJUSTED_CLOSE", "evidence_id": "review-1", "min_overlap": 5}
    assert compare_backup(_candidate([1, 1.01, 1.02, 1.03, 1.04]), primary, policy) == []
    assert compare_backup(_candidate([1, 1.01]), primary, policy) == ["INSUFFICIENT_PRIMARY_OVERLAP"]
    assert any(item.startswith("PRICE_BASIS_OR_CORPORATE_ACTION_REVIEW") for item in
               compare_backup(_candidate([1, 1.01, 1.20, 1.03, 1.04]), primary, policy))
    assert compare_backup(_candidate([1, 1.01, 1.02, 1.03, 1.04]), primary, None) == ["BASIS_UNVERIFIED"]


def test_primary_overlap_needs_real_raw_link_and_basis(tmp_path):
    database = tmp_path / "market.db"
    init_reliability_schema(database)
    _, digest = save_raw_payload(tmp_path, "b1", "etf-510330", b"real primary response")
    record_observations(database, [{"symbol": "510330", "kind": "etf", "trade_date": "20260101",
                                    "value_raw": "1.0", "provider": "AkShare", "upstream_publisher": "Eastmoney",
                                    "raw_sha256": digest, "fetch_batch_id": "b1", "source_version": "UNADJUSTED_CLOSE/v1"}])
    with sqlite3.connect(database) as connection:
        raw_id = connection.execute("SELECT raw_record_id FROM raw_observations").fetchone()[0]
    record_canonical_observations(database, [{"symbol": "510330", "kind": "etf", "trade_date": "20260101",
                                               "normalized_value": 1.0, "normalized_unit": "元/份", "selected_raw_id": raw_id,
                                               "selection_reason": "primary", "quality_status": "PASS", "batch_id": "b1"}])
    assert trusted_primary_overlaps(database, tmp_path, "510330", {"20260101"}) == {"20260101": 1.0}
    assert trusted_primary_overlaps(database, tmp_path, "510330", {"20260102"}) == {}
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE raw_observations SET value_raw='1.1' WHERE raw_record_id=?", (raw_id,))
    assert trusted_primary_overlaps(database, tmp_path, "510330", {"20260101"}) == {}
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE raw_observations SET value_raw='1.0' WHERE raw_record_id=?", (raw_id,))
    (tmp_path / "raw" / "market" / "b1" / f"etf-510330-{digest[:16]}.bin").write_bytes(b"tampered")
    assert trusted_primary_overlaps(database, tmp_path, "510330", {"20260101"}) == {}


def test_operator_policy_needs_explicit_evidence(tmp_path):
    path = tmp_path / "source_policy.json"
    path.write_text('{"etf":{"510330":{"backup_upstream":"Sina","price_basis":"UNADJUSTED_CLOSE"}}}', encoding="utf-8")
    assert load_backup_policy(tmp_path, "510330") is None
    path.write_text('{"etf":{"510330":{"backup_upstream":"Sina","price_basis":"UNADJUSTED_CLOSE","evidence_id":"review-1"}}}', encoding="utf-8")
    assert load_backup_policy(tmp_path, "510330")["policy_sha256"]


def test_historical_matching_raw_is_reported_without_fabricating_selection(tmp_path):
    database = tmp_path / "market.db"
    init_reliability_schema(database)
    _, digest = save_raw_payload(tmp_path, "batch1", "etf-510330", b"real upstream bytes")
    record_observations(database, [{"symbol": "510330", "kind": "etf", "trade_date": "20260101",
                                    "value_raw": "1.0", "provider": "AkShare", "upstream_publisher": "Eastmoney",
                                    "raw_sha256": digest, "fetch_batch_id": "batch1"}])
    matches = corroborating_raw_matches(database, tmp_path, "etf", "510330", "20260101", 1.0)
    assert matches[0]["link_status"] == "CORROBORATING_NOT_SELECTED"
    (tmp_path / "raw" / "market" / "batch1" / f"etf-510330-{digest[:16]}.bin").write_bytes(b"tampered")
    assert corroborating_raw_matches(database, tmp_path, "etf", "510330", "20260101", 1.0) == []
