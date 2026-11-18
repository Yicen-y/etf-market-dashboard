from fastapi.testclient import TestClient
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import server
from scripts.jobs import claim_job, get_job, recent_jobs, set_job
from scripts.storage import init_reliability_schema, publish_snapshot


@pytest.fixture(autouse=True)
def stub_daily_reference_checks(monkeypatch):
    monkeypatch.setattr(server, "run_daily", lambda **kwargs: {"through": "20261118", "indexes": {}})


def test_atomic_claim_reuses_active_window(tmp_path):
    first, created = claim_job(tmp_path, "all_prices", "2026-11-13", "manual")
    second, duplicate = claim_job(tmp_path, "all_prices", "2026-11-13", "timer")
    assert created and not duplicate
    assert first["job_id"] == second["job_id"]
    set_job(tmp_path, first["job_id"], state="FAILED", stage="STOPPED", error="TimeoutError")
    third, created_again = claim_job(tmp_path, "all_prices", "2026-11-13", "manual")
    assert created_again and third["job_id"] != first["job_id"]
    set_job(tmp_path, third["job_id"], state="SUCCEEDED", stage="PUBLISHED", snapshot_id="fixture")
    fourth, created_after_success = claim_job(tmp_path, "all_prices", "2026-11-13", "timer")
    assert not created_after_success and fourth["job_id"] == third["job_id"]


def test_manual_retry_can_create_new_job_after_same_day_success(tmp_path):
    first, created = claim_job(tmp_path, "all_prices", "2026-11-18", "manual")
    assert created
    set_job(tmp_path, first["job_id"], state="SUCCEEDED", stage="PUBLISHED", snapshot_id="etf-only")
    retry, created = claim_job(tmp_path, "all_prices", "2026-11-18", "manual", reuse_success=False)
    assert created and retry["job_id"] != first["job_id"]
    active, created = claim_job(tmp_path, "all_prices", "2026-11-18", "manual", reuse_success=False)
    assert not created and active["job_id"] == retry["job_id"]


def test_manual_update_verifies_references_before_publish_and_reports_index_lag(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(server, "DATABASE_PATH", tmp_path / "etf_market.db")
    calls = []

    def verify_first(**kwargs):
        calls.append("verify")
        assert kwargs["publish"] is False
        return {"through": "20261118", "indexes": {
            "480080": {"route_approval": {"status": "NO_TARGET_MATCH"}}},
            "latest_metrics": {"expected_trade_date": "20261118"}}

    def publish(progress, **kwargs):
        calls.append("publish")
        assert kwargs["end_date"] == "20261118"
        assert kwargs["require_reference_verification"] is True
        return {"snapshot_id": "etf-18-index-17", "publicationStatus": "PUBLISHED",
                "etfLatestTradeDate": "20261118", "indexLatestTradeDate": "20261117",
                "nikkeiAnchor": {"status": "NO_NEW_ROWS"}}

    monkeypatch.setattr(server, "run_daily", verify_first, raising=False)
    monkeypatch.setattr(server, "update_dataset", publish)
    response = TestClient(server.app).post("/api/jobs/update")
    assert response.status_code == 202
    assert calls == ["verify", "publish"]
    job = get_job(tmp_path, response.json()["job_id"])
    assert job["state"] == "PARTIAL"
    detail = TestClient(server.app).get(f"/api/jobs/{job['job_id']}/details").json()
    index = next(item for item in detail["datasets"] if item["dataset_id"] == "index_prices")
    assert index["latest_date"] == "20261117"
    assert index["reason_code"] == "CNI_ROUTE_PENDING"
    route = next(item for item in detail["datasets"] if item["dataset_id"] == "index:480080")
    assert route["reason_code"] == "CNI_ROUTE_PENDING"


def test_cross_process_claim_has_one_winner(tmp_path):
    script = """import json,sys
from pathlib import Path
from scripts.jobs import claim_job
job, created = claim_job(Path(sys.argv[1]), 'all_prices', '2026-11-13', 'timer')
print(json.dumps({'job_id': job['job_id'], 'created': created}))
"""
    root = Path(__file__).resolve().parents[1]
    commands = [[sys.executable, "-c", script, str(tmp_path)] for _ in range(2)]
    processes = [subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True) for command in commands]
    results = []
    for process in processes:
        out, err = process.communicate(timeout=15)
        assert process.returncode == 0, err
        results.append(json.loads(out))
    assert sum(row["created"] for row in results) == 1
    assert results[0]["job_id"] == results[1]["job_id"]


def test_orphaned_worker_is_reported_and_retryable(tmp_path):
    old, _ = claim_job(tmp_path, "all_prices", "2026-11-13", "manual")
    set_job(tmp_path, old["job_id"], state="RUNNING", stage="FETCH_VALIDATE_PUBLISH")
    with sqlite3.connect(tmp_path / "jobs.db") as connection:
        connection.execute("UPDATE update_jobs SET heartbeat_at='2000-01-01T00:00:00+00:00'")
    assert get_job(tmp_path, old["job_id"])["stage"] == "ORPHANED"
    new, created = claim_job(tmp_path, "all_prices", "2026-11-13", "manual")
    assert created and new["job_id"] != old["job_id"]
    assert get_job(tmp_path, old["job_id"])["state"] == "FAILED"


def test_existing_job_database_gets_heartbeat_column(tmp_path):
    with sqlite3.connect(tmp_path / "jobs.db") as connection:
        connection.execute("""CREATE TABLE update_jobs (
            job_id TEXT PRIMARY KEY, dataset TEXT NOT NULL, update_window TEXT NOT NULL,
            trigger TEXT NOT NULL, state TEXT NOT NULL, stage TEXT NOT NULL,
            started_at TEXT NOT NULL, finished_at TEXT, snapshot_id TEXT, error TEXT)""")
    job, created = claim_job(tmp_path, "all_prices", "2026-11-13", "manual")
    assert created
    assert get_job(tmp_path, job["job_id"])["heartbeat_at"]


def test_market_update_lock_rejects_second_process(tmp_path):
    holder = """import sys,time
from pathlib import Path
from scripts.update_data import _exclusive_update
with _exclusive_update(Path(sys.argv[1])):
    print('locked', flush=True)
    time.sleep(15)
"""
    contender = """import sys
from pathlib import Path
from scripts.update_data import _exclusive_update
try:
    with _exclusive_update(Path(sys.argv[1])): print('unexpected')
except (BlockingIOError, OSError): print('blocked')
"""
    root = Path(__file__).resolve().parents[1]
    process = subprocess.Popen([sys.executable, "-c", holder, str(tmp_path)], cwd=root,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "locked"
        result = subprocess.run([sys.executable, "-c", contender, str(tmp_path)], cwd=root,
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "blocked"
    finally:
        process.terminate()
        process.communicate(timeout=10)


def test_http_job_persists_result_without_exposing_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA_ROOT", tmp_path)
    def verified_update(progress, **kwargs):
        assert kwargs["require_reference_verification"] is True
        return {"snapshot_id": "fixture-v2"}
    monkeypatch.setattr(server, "update_dataset", verified_update)
    client = TestClient(server.app)
    response = client.post("/api/jobs/update")
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "SUCCEEDED"
    assert get_job(tmp_path, job_id)["snapshot_id"] == "fixture-v2"
    assert recent_jobs(tmp_path)[0]["stage"] == "PUBLISHED"


def test_optional_sync_failure_is_partial_not_full_success(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(server, "update_dataset", lambda progress, **kwargs: {
        "snapshot_id": "fixture-v2", "nikkeiAnchor": {"status": "ERROR", "message": "secret"}})
    response = TestClient(server.app).post("/api/jobs/update")
    job = get_job(tmp_path, response.json()["job_id"])
    assert job["state"] == "PARTIAL"
    assert job["snapshot_id"] == "fixture-v2"
    assert "secret" not in str(job)


def test_unchanged_refresh_keeps_release_state_separate_from_source_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(server, "update_dataset", lambda progress, **kwargs: {
        "snapshot_id": "old", "publicationStatus": "UNCHANGED",
        "sourceIssues": [{"kind": "index", "symbol": "H00300", "trade_date": "20261112",
                          "issue_code": "SOURCE_TRAILING_UNAVAILABLE"}]})
    job_id = TestClient(server.app).post("/api/jobs/update").json()["job_id"]
    detail = TestClient(server.app).get(f"/api/jobs/{job_id}/details").json()
    job = get_job(tmp_path, job_id)
    assert (job["state"], job["stage"], job["fetch_status"], job["validation_status"],
            job["publication_status"]) == (
                "PARTIAL", "UNCHANGED_WITH_PARTIAL_FAILURE", "PARTIAL", "VERIFIED", "UNCHANGED")
    assert "H00300" in str(detail)


def test_publish_failure_job_is_failed_while_old_snapshot_remains(tmp_path, monkeypatch):
    database = tmp_path / "etf_market.db"
    init_reliability_schema(database)
    publish_snapshot(tmp_path, "old", {"snapshot_id": "old", "records": [], "latestTradeDate": "20261111"},
                     {"snapshot_id": "old", "records": [], "latestTradeDate": "20261111"})
    monkeypatch.setattr(server, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(server, "DATABASE_PATH", database)

    def fail_publish(progress, **kwargs):
        for stage in ("FETCHING", "VALIDATING", "VALIDATED", "STAGING"):
            progress(stage)
        raise OSError("secret publication path")

    monkeypatch.setattr(server, "update_dataset", fail_publish)
    client = TestClient(server.app)
    job_id = client.post("/api/jobs/update").json()["job_id"]
    report = client.get("/api/data-center").json()
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "FAILED"
    assert report["current_snapshot_id"] == "old"
    assert "已保留旧版快照" in report["recent_jobs"][0]["error"]
    assert "secret publication path" not in report["recent_jobs"][0]["error"]
    assert report["recent_jobs"][0]["fetch_status"] == "FETCH_OK"
    assert report["recent_jobs"][0]["validation_status"] == "VERIFIED"
    assert report["recent_jobs"][0]["publication_status"] == "FAILED"
    assert "secret" not in str(report)


def test_fetch_ok_but_validation_failure_keeps_stages_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA_ROOT", tmp_path)

    def fail_validation(progress, **kwargs):
        progress("FETCHING")
        progress("VALIDATING")
        raise ValueError("candidate differs")

    monkeypatch.setattr(server, "update_dataset", fail_validation)
    job_id = TestClient(server.app).post("/api/jobs/update").json()["job_id"]
    job = get_job(tmp_path, job_id)
    assert (job["fetch_status"], job["validation_status"], job["publication_status"]) == (
        "FETCH_OK", "VALIDATION_FAILED", "NOT_ATTEMPTED")


def test_remote_peer_cannot_call_mutating_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA_ROOT", tmp_path)
    remote = TestClient(server.app, client=("203.0.113.9", 50000))
    assert remote.post("/api/jobs/update").status_code == 403
    assert remote.post("/api/update").status_code == 403
    assert remote.post("/api/dividend/sync-watchlist").status_code == 403
    assert not (tmp_path / "jobs.db").exists()
