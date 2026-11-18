from fastapi.testclient import TestClient

import server
from scripts.jobs import claim_job, get_job_detail, record_dataset_result, set_job


def test_legacy_partial_identifies_unrecorded_nikkei_reason(tmp_path):
    job, _ = claim_job(tmp_path, "all_prices", "2026-11-15", "manual")
    set_job(tmp_path, job["job_id"], state="PARTIAL", stage="PUBLISHED_WITH_PARTIAL_FAILURE",
            snapshot_id="published-v1", fetch_status="FETCH_OK", validation_status="VERIFIED",
            publication_status="PUBLISHED")
    detail = get_job_detail(tmp_path, job["job_id"])
    by_id = {row["dataset_id"]: row for row in detail["datasets"]}
    assert by_id["etf_prices"]["state"] == "PUBLISHED"
    assert by_id["index_prices"]["state"] == "PUBLISHED"
    assert by_id["nikkei225_anchor"]["state"] == "UNKNOWN"
    assert by_id["nikkei225_anchor"]["reason_code"] == "LEGACY_DETAIL_NOT_RECORDED"
    assert detail["historical_detail_incomplete"] is True


def test_dataset_outcome_is_idempotent_and_keeps_safe_reason(tmp_path):
    job, _ = claim_job(tmp_path, "all_prices", "2026-11-16", "manual")
    record_dataset_result(tmp_path, job["job_id"], "nikkei225_anchor", "日经225临时基准",
                          "FAILED", "Wind MCP", "UPSTREAM_HTTP_429", "HTTPError", 0, 0, None)
    record_dataset_result(tmp_path, job["job_id"], "nikkei225_anchor", "日经225临时基准",
                          "FAILED", "Wind MCP", "UPSTREAM_HTTP_429", "HTTPError", 0, 0, None)
    detail = get_job_detail(tmp_path, job["job_id"])
    assert len(detail["datasets"]) == 1
    assert detail["datasets"][0]["reason_code"] == "UPSTREAM_HTTP_429"


def test_legacy_failed_task_does_not_invent_a_symbol(tmp_path):
    job, _ = claim_job(tmp_path, "all_prices", "2026-11-14", "manual")
    set_job(tmp_path, job["job_id"], state="FAILED", stage="VALIDATING", error="ValueError")
    detail = get_job_detail(tmp_path, job["job_id"])
    assert detail["datasets"][0]["dataset_id"] == "all_prices"
    assert detail["datasets"][0]["state"] == "UNKNOWN"
    assert detail["datasets"][0]["reason_code"] == "LEGACY_DETAIL_NOT_RECORDED"


def test_legacy_success_shows_published_summary_without_inventing_dataset_details(tmp_path):
    job, _ = claim_job(tmp_path, "all_prices", "2026-11-16", "manual")
    set_job(tmp_path, job["job_id"], state="SUCCEEDED", stage="PUBLISHED",
            snapshot_id="published-v1", fetch_status="FETCH_OK",
            validation_status="VERIFIED", publication_status="PUBLISHED")
    detail = get_job_detail(tmp_path, job["job_id"])
    assert detail["historical_detail_incomplete"] is True
    assert len(detail["datasets"]) == 1
    assert detail["datasets"][0]["dataset_id"] == "all_prices"
    assert detail["datasets"][0]["state"] == "PUBLISHED"
    assert detail["datasets"][0]["reason_code"] == "LEGACY_SUMMARY_ONLY"


def test_http_partial_job_exposes_affected_dataset_without_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(server, "run_daily", lambda **kwargs: {"through": "20261118", "indexes": {}})
    monkeypatch.setattr(server, "update_dataset", lambda progress, **kwargs: {
        "snapshot_id": "published-v2", "etfLatestTradeDate": "20261113",
        "indexLatestTradeDate": "20261113",
        "nikkeiAnchor": {"status": "ERROR", "error_type": "HTTPError",
                         "message": "secret https://upstream.invalid?token=private HTTP 429"}})
    client = TestClient(server.app)
    job_id = client.post("/api/jobs/update").json()["job_id"]
    response = client.get(f"/api/jobs/{job_id}/details")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "PARTIAL"
    assert body["historical_detail_incomplete"] is False
    assert {row["dataset_id"] for row in body["datasets"]} == {
        "etf_prices", "index_prices", "nikkei225_anchor"}
    assert next(row for row in body["datasets"] if row["dataset_id"] == "nikkei225_anchor")["reason_code"] == "UPSTREAM_HTTP_429"
    assert "secret" not in response.text and "token" not in response.text
