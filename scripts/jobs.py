"""Durable local update jobs. The claim is atomic across server workers."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _expiry() -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat(timespec="seconds")


def _connect(data_root: Path) -> sqlite3.Connection:
    data_root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(data_root / "jobs.db", timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("""CREATE TABLE IF NOT EXISTS update_jobs (
        job_id TEXT PRIMARY KEY, dataset TEXT NOT NULL, update_window TEXT NOT NULL,
        trigger TEXT NOT NULL, state TEXT NOT NULL, stage TEXT NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT, snapshot_id TEXT, error TEXT,
        heartbeat_at TEXT NOT NULL DEFAULT '',
        fetch_status TEXT NOT NULL DEFAULT 'UNKNOWN',
        validation_status TEXT NOT NULL DEFAULT 'UNKNOWN',
        publication_status TEXT NOT NULL DEFAULT 'UNKNOWN')""")
    connection.execute("""CREATE TABLE IF NOT EXISTS job_dataset_results (
        job_id TEXT NOT NULL, dataset_id TEXT NOT NULL, label TEXT NOT NULL,
        state TEXT NOT NULL, provider TEXT, reason_code TEXT, error_type TEXT,
        records_added INTEGER, records_revised INTEGER, latest_date TEXT,
        recorded_at TEXT NOT NULL,
        PRIMARY KEY (job_id,dataset_id),
        FOREIGN KEY (job_id) REFERENCES update_jobs(job_id))""")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(update_jobs)")}
    for column in ("heartbeat_at", "fetch_status", "validation_status", "publication_status"):
        if column not in columns:
            default = "" if column == "heartbeat_at" else "UNKNOWN"
            connection.execute(f"ALTER TABLE update_jobs ADD COLUMN {column} TEXT NOT NULL DEFAULT '{default}'")
    connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS one_active_job
        ON update_jobs(dataset, update_window) WHERE state IN ('QUEUED','RUNNING')""")
    return connection


def claim_job(data_root: Path, dataset: str, update_window: str, trigger: str,
              *, reuse_success: bool = True) -> tuple[dict, bool]:
    """Return an active job, optionally reusing a successful window result."""
    with _connect(data_root) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""UPDATE update_jobs SET state='FAILED', stage='ORPHANED',
            error='WorkerInterrupted', finished_at=? WHERE state IN ('QUEUED','RUNNING')
            AND heartbeat_at<?""", (_now(), _expiry()))
        reusable_states = "('QUEUED','RUNNING','SUCCEEDED')" if reuse_success else "('QUEUED','RUNNING')"
        row = connection.execute(f"""SELECT * FROM update_jobs WHERE dataset=? AND update_window=?
            AND state IN {reusable_states}
            ORDER BY CASE state WHEN 'RUNNING' THEN 0 WHEN 'QUEUED' THEN 1 ELSE 2 END,
            started_at DESC LIMIT 1""", (dataset, update_window)).fetchone()
        if row:
            return dict(row), False
        job_id = uuid.uuid4().hex
        connection.execute("""INSERT INTO update_jobs
            (job_id,dataset,update_window,trigger,state,stage,started_at,heartbeat_at)
            VALUES (?,?,?,?,'QUEUED','WAITING',?,?)""", (job_id, dataset, update_window, trigger, _now(), _now()))
        row = connection.execute("SELECT * FROM update_jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row), True


def set_job(data_root: Path, job_id: str, *, state: str, stage: str,
            snapshot_id: str | None = None, error: str | None = None,
            fetch_status: str | None = None, validation_status: str | None = None,
            publication_status: str | None = None) -> None:
    if state not in {"RUNNING", "SUCCEEDED", "FAILED", "PARTIAL"}:
        raise ValueError("invalid job state")
    with _connect(data_root) as connection:
        connection.execute("""UPDATE update_jobs SET state=?, stage=?, snapshot_id=?, error=?, heartbeat_at=?,
            fetch_status=COALESCE(?,fetch_status), validation_status=COALESCE(?,validation_status),
            publication_status=COALESCE(?,publication_status),
            finished_at=CASE WHEN ? IN ('SUCCEEDED','FAILED','PARTIAL') THEN ? ELSE NULL END
            WHERE job_id=?""", (state, stage, snapshot_id, error, _now(),
                                fetch_status, validation_status, publication_status, state, _now(), job_id))


def heartbeat_job(data_root: Path, job_id: str) -> None:
    with _connect(data_root) as connection:
        connection.execute("UPDATE update_jobs SET heartbeat_at=? WHERE job_id=? AND state='RUNNING'",
                           (_now(), job_id))


def _public_job(row: sqlite3.Row) -> dict:
    job = dict(row)
    if job["state"] in {"QUEUED", "RUNNING"} and job["heartbeat_at"] < _expiry():
        job.update(state="FAILED", stage="ORPHANED", error="WorkerInterrupted")
    return job


def get_job(data_root: Path, job_id: str) -> dict | None:
    path = data_root / "jobs.db"
    if not path.exists():
        return None
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM update_jobs WHERE job_id=?", (job_id,)).fetchone()
        return _public_job(row) if row else None


def recent_jobs(data_root: Path, limit: int = 20) -> list[dict]:
    path = data_root / "jobs.db"
    if not path.exists():
        return []
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        return [_public_job(row) for row in connection.execute(
            "SELECT * FROM update_jobs ORDER BY started_at DESC LIMIT ?", (limit,))]


def record_dataset_result(data_root: Path, job_id: str, dataset_id: str, label: str,
                          state: str, provider: str | None = None,
                          reason_code: str | None = None, error_type: str | None = None,
                          records_added: int | None = None, records_revised: int | None = None,
                          latest_date: str | None = None) -> None:
    """Persist a safe per-dataset outcome; retries update the same job row."""
    if state not in {"PUBLISHED", "UPDATED", "NO_NEW_ROWS", "PARTIAL", "FAILED", "SKIPPED", "UNKNOWN"}:
        raise ValueError("invalid dataset state")
    if reason_code and not reason_code.replace("_", "").isalnum():
        raise ValueError("reason_code must be a diagnostic code")
    if error_type and not error_type.replace("_", "").isalnum():
        raise ValueError("error_type must be a class name")
    with _connect(data_root) as connection:
        connection.execute("""INSERT INTO job_dataset_results VALUES (?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(job_id,dataset_id) DO UPDATE SET
          label=excluded.label,state=excluded.state,provider=excluded.provider,
          reason_code=excluded.reason_code,error_type=excluded.error_type,
          records_added=excluded.records_added,records_revised=excluded.records_revised,
          latest_date=excluded.latest_date,recorded_at=excluded.recorded_at""",
          (job_id,dataset_id,label,state,provider,reason_code,error_type,
           records_added,records_revised,latest_date,_now()))


def get_job_detail(data_root: Path, job_id: str) -> dict | None:
    """Read current outcomes; label pre-migration job inference explicitly."""
    job = get_job(data_root, job_id)
    if job is None:
        return None
    path = data_root / "jobs.db"
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='job_dataset_results'").fetchone()
        datasets = ([dict(row) for row in connection.execute(
            "SELECT dataset_id,label,state,provider,reason_code,error_type,records_added,records_revised,latest_date,recorded_at FROM job_dataset_results WHERE job_id=? ORDER BY dataset_id",
            (job_id,))] if exists else [])
    legacy = not datasets
    if legacy and job["state"] == "PARTIAL" and job["stage"] == "PUBLISHED_WITH_PARTIAL_FAILURE":
        datasets = [
            {"dataset_id":"etf_prices","label":"ETF 行情","state":"PUBLISHED","provider":None,
             "reason_code":None,"error_type":None,"records_added":None,"records_revised":None,
             "latest_date":None,"recorded_at":None},
            {"dataset_id":"index_prices","label":"指数行情","state":"PUBLISHED","provider":None,
             "reason_code":None,"error_type":None,"records_added":None,"records_revised":None,
             "latest_date":None,"recorded_at":None},
            {"dataset_id":"nikkei225_anchor","label":"日经225临时基准（五年之锚）",
             "state":"UNKNOWN","provider":"Wind MCP","reason_code":"LEGACY_DETAIL_NOT_RECORDED",
             "error_type":None,"records_added":None,"records_revised":None,
             "latest_date":None,"recorded_at":None},
        ]
    elif (legacy and job["state"] == "SUCCEEDED" and job["stage"] == "PUBLISHED"
          and job["snapshot_id"] and job["publication_status"] == "PUBLISHED"):
        datasets = [{"dataset_id":"all_prices","label":"ETF 与指数行情（旧任务汇总）",
                     "state":"PUBLISHED","provider":None,"reason_code":"LEGACY_SUMMARY_ONLY",
                     "error_type":None,"records_added":None,"records_revised":None,
                     "latest_date":None,"recorded_at":None}]
    elif legacy and job["state"] == "FAILED":
        datasets = [{"dataset_id":"all_prices","label":"ETF 或指数行情（旧任务未定位具体标的）",
                     "state":"UNKNOWN","provider":None,"reason_code":"LEGACY_DETAIL_NOT_RECORDED",
                     "error_type":job.get("error") if str(job.get("error") or "").isidentifier() else None,
                     "records_added":None,"records_revised":None,"latest_date":None,
                     "recorded_at":None}]
    return {**job,"datasets":datasets,"historical_detail_incomplete":legacy}
