"""Synthetic records only; no market observations or network access."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import date
from typing import get_args
import sqlite3

import pytest

from scripts.fund_flow.config import ETF_UNIVERSE, PRESET_GROUPS
from scripts.fund_flow.db import init_fund_flow_schema, open_fund_flow_connection, seed_default_fund_master
from scripts.fund_flow import models
from scripts.fund_flow.models import CleanETFRecord, DailyMetric, RawETFRecord


def test_schema_can_be_initialized_twice(tmp_path):
    db_path = tmp_path / "etf_market.db"

    init_fund_flow_schema(db_path)
    init_fund_flow_schema(db_path)

    with sqlite3.connect(db_path) as conn:
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}

    assert "fund_master" in names
    assert "fund_flow_etf_daily_raw" in names
    assert "fund_flow_etf_daily_metrics" in names


def test_default_master_contains_six_etfs_and_presets(tmp_path):
    db_path = tmp_path / "etf_market.db"
    seed_default_fund_master(db_path)

    with open_fund_flow_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT etf_code, name, fund_group FROM fund_master ORDER BY etf_code"
        ).fetchall()

    assert {row[0] for row in rows} == set(ETF_UNIVERSE)
    assert set(PRESET_GROUPS) == {"original_shanghai_five", "core_four", "all_six"}
    assert set(PRESET_GROUPS["original_shanghai_five"]) == {
        "510300.SH", "510310.SH", "510320.SH", "510330.SH", "510350.SH"
    }


def test_record_models_preserve_units_and_statuses():
    raw = RawETFRecord(
        etf_code="510300.SH",
        record_date=date(2024, 1, 2),
        effective_trade_date=date(2024, 1, 2),
        published_at=None,
        total_share=100000.0,
        share_unit="万份",
        share_scope="on_exchange",
        share_date_basis="post_close",
        nav=4.0,
        close=None,
        total_size=None,
        source_id="test",
        source_version="1",
        import_batch_id="batch-1",
    )
    clean = CleanETFRecord(
        etf_code=raw.etf_code,
        trade_date=raw.effective_trade_date,
        shares_wan=raw.total_share,
        nav=raw.nav,
        size_yi=None,
        share_scope=raw.share_scope,
        validation_status="PASS",
        error_codes=(),
        source_id=raw.source_id,
    )
    metric = DailyMetric(
        etf_code=clean.etf_code,
        trade_date=clean.trade_date,
        shares_adj_wan=clean.shares_wan,
        nav_adj=clean.nav,
        delta_shares_wan=0.0,
        net_flow_yi=0.0,
        cum_flow_yi=0.0,
        intensity_pct=0.0,
        calc_version="v1",
        status="PASS",
    )

    assert raw.share_unit == "万份"
    assert clean.validation_status == "PASS"
    assert metric.status == "PASS"


def test_invalid_status_is_rejected():
    with pytest.raises(ValueError):
        CleanETFRecord(
            etf_code="510300.SH",
            trade_date=date(2024, 1, 2),
            shares_wan=1.0,
            nav=1.0,
            size_yi=None,
            share_scope="on_exchange",
            validation_status="bad",  # type: ignore[arg-type]
            error_codes=(),
            source_id="test",
        )


def raw_record(**changes):
    values = dict(
        etf_code="510300.SH", record_date="2024-01-02",
        effective_trade_date="2024-01-02", published_at=None,
        total_share=100, share_unit="万份", share_scope="total",
        share_date_basis="trade_date", nav=2, close=None, total_size=None,
        source_id="synthetic", source_version="v1", import_batch_id="batch-1",
    )
    values.update(changes)
    return models.RawETFRecord(**values)


def clean_record(**changes):
    values = dict(etf_code="510300.SH", trade_date="2024-01-02",
                  shares_wan=100, nav=2, size_yi=None, share_scope="total",
                  validation_status="PASS", error_codes=(), source_id="synthetic")
    values.update(changes)
    return models.CleanETFRecord(**values)


def metric_record(**changes):
    values = dict(etf_code="510300.SH", trade_date="2024-01-02",
                  shares_adj_wan=100, nav_adj=2, delta_shares_wan=-1,
                  net_flow_yi=-0.0002, cum_flow_yi=-0.0002, intensity_pct=-1,
                  calc_version="v1", status="PASS")
    values.update(changes)
    return models.DailyMetric(**values)


def test_records_preserve_missing_values_and_signed_flows():
    assert raw_record(total_share=None, nav=None).nav is None
    assert raw_record(total_share=-1).total_share == -1
    assert clean_record(nav=None, validation_status="BLOCKED").nav is None
    assert metric_record().net_flow_yi == -0.0002
    assert metric_record(net_flow_yi=None, status="INCOMPLETE").net_flow_yi is None
    with pytest.raises(FrozenInstanceError):
        raw_record().nav = 3


@pytest.mark.parametrize("factory,changes", [
    (raw_record, {"etf_code": "510300"}),
    (raw_record, {"record_date": "2024-02-30"}),
    (raw_record, {"effective_trade_date": "20240102"}),
    (raw_record, {"published_at": "not-a-timestamp"}),
    (raw_record, {"source_id": " "}),
    (raw_record, {"import_batch_id": ""}),
    (raw_record, {"nav": float("nan")}),
    (raw_record, {"share_unit": ""}),
    (clean_record, {"validation_status": "valid"}),
    (clean_record, {"shares_wan": -1}),
    (clean_record, {"error_codes": ["missing_nav"]}),
    (metric_record, {"status": "complete"}),
    (metric_record, {"calc_version": ""}),
    (metric_record, {"net_flow_yi": float("inf")}),
])
def test_invalid_model_inputs_are_rejected(factory, changes):
    with pytest.raises(ValueError):
        factory(**changes)


def test_dates_and_status_literals():
    assert raw_record(record_date=date(2024, 1, 2)).record_date == date(2024, 1, 2)
    assert raw_record(published_at="2024-01-02T16:00:00+08:00").published_at
    assert set(get_args(models.ValidationStatus)) == {"PASS", "WARNING", "BLOCKED"}
    assert set(get_args(models.MetricStatus)) == {"PASS", "WARNING", "BLOCKED", "INCOMPLETE"}
    assert set(get_args(models.ImportJobStatus)) == {"pending", "running", "completed", "failed"}


def test_auxiliary_records_validate_status_and_identity():
    action = models.CorporateAction(
        etf_code="510310.SH", ex_date="2024-01-03", action_type="consolidation",
        event_date="2024-01-02", ratio=0.5, status="source_verified",
    )
    assert action.first_post_record_date is None
    with pytest.raises(ValueError):
        replace(action, status="approved")
    with pytest.raises(ValueError):
        replace(action, ratio=0)
    issue = models.QualityIssue("510300.SH", "2024-01-02", "missing_nav", "Synthetic missing NAV", "BLOCKED")
    with pytest.raises(ValueError):
        replace(issue, status="valid")
    job = models.ImportJob("batch-1", "synthetic", "pending")
    with pytest.raises(ValueError):
        replace(job, status="unknown")
    with pytest.raises(ValueError):
        replace(job, import_batch_id="")


def test_core_record_fields_match_brief():
    assert [f.name for f in fields(models.RawETFRecord)] == [
        "etf_code", "record_date", "effective_trade_date", "published_at",
        "total_share", "share_unit", "share_scope", "share_date_basis", "nav",
        "close", "total_size", "source_id", "source_version", "import_batch_id",
    ]
    assert [f.name for f in fields(models.CleanETFRecord)] == [
        "etf_code", "trade_date", "shares_wan", "nav", "size_yi", "share_scope",
        "validation_status", "error_codes", "source_id",
    ]
    assert [f.name for f in fields(models.DailyMetric)] == [
        "etf_code", "trade_date", "shares_adj_wan", "nav_adj", "delta_shares_wan",
        "net_flow_yi", "cum_flow_yi", "intensity_pct", "calc_version", "status",
    ]


def test_universe_presets_and_database_path():
    from scripts.config import DATABASE_PATH as existing_path
    from scripts.fund_flow.config import DATABASE_PATH, ETF_UNIVERSE, PRESET_GROUPS

    assert DATABASE_PATH == existing_path
    assert ETF_UNIVERSE == {
        "510300.SH": {"name": "华泰柏瑞沪深300ETF", "group": "core"},
        "510310.SH": {"name": "易方达沪深300ETF", "group": "core"},
        "510330.SH": {"name": "华夏沪深300ETF", "group": "core"},
        "159919.SZ": {"name": "嘉实沪深300ETF", "group": "core"},
        "510320.SH": {"name": "中金沪深300ETF", "group": "extended"},
        "510350.SH": {"name": "工银瑞信沪深300ETF", "group": "extended"},
    }
    assert set(PRESET_GROUPS) == {"original_shanghai_five", "core_four", "all_six"}
    assert set(PRESET_GROUPS["original_shanghai_five"]) == {
        "510300.SH", "510310.SH", "510320.SH", "510330.SH", "510350.SH",
    }
    assert set(PRESET_GROUPS["core_four"]) == {code for code, fund in ETF_UNIVERSE.items() if fund["group"] == "core"}
    assert set(PRESET_GROUPS["all_six"]) == set(ETF_UNIVERSE)
    assert all(len(codes) == len(set(codes)) for codes in PRESET_GROUPS.values())


def test_schema_can_be_initialized_twice_without_changing_existing_data(tmp_path):
    import sqlite3
    from scripts.storage import upsert_index_records, upsert_records
    from scripts.fund_flow.db import init_fund_flow_schema

    path = tmp_path / "nested" / "etf_market.db"
    upsert_records(path, [{"tradeDate": "2024-01-02", "productCode": "510330", "closePrice": 2}], "synthetic")
    upsert_index_records(path, [{"tradeDate": "2024-01-02", "indexCode": "H00300", "closeValue": 100}], "synthetic")
    with sqlite3.connect(path) as conn:
        before = {name: conn.execute(f"SELECT * FROM {name}").fetchall() for name in ("etf_prices", "index_prices")}
        definitions = conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    init_fund_flow_schema(path)
    init_fund_flow_schema(path)
    with sqlite3.connect(path) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names == {"etf_prices", "index_prices", "fund_master", "fund_flow_etf_daily_raw",
                         "fund_flow_index_daily_raw", "fund_flow_corporate_actions", "fund_flow_etf_daily_clean",
                         "fund_flow_etf_daily_metrics", "fund_flow_data_sources", "fund_flow_import_jobs"}
        for name, rows in before.items():
            assert conn.execute(f"SELECT * FROM {name}").fetchall() == rows
        for name, sql in definitions:
            assert conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()[0] == sql
        for table, record in (("fund_flow_etf_daily_raw", models.RawETFRecord),
                              ("fund_flow_etf_daily_clean", models.CleanETFRecord),
                              ("fund_flow_etf_daily_metrics", models.DailyMetric)):
            columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            assert {f.name for f in fields(record)} <= columns


def test_connection_creates_parent_and_enforces_foreign_keys(tmp_path):
    import sqlite3
    from scripts.fund_flow.db import init_fund_flow_schema, open_fund_flow_connection

    path = tmp_path / "nested" / "flow.db"
    conn = open_fund_flow_connection(path)
    try:
        assert isinstance(conn, sqlite3.Connection)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()
    init_fund_flow_schema(path)
    conn = open_fund_flow_connection(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO fund_flow_import_jobs(import_batch_id,source_id,status) VALUES ('b','missing','pending')")
    finally:
        conn.close()


def test_seeding_is_idempotent_and_preserves_custom_master_data(tmp_path):
    import sqlite3
    from scripts.fund_flow.config import ETF_UNIVERSE
    from scripts.fund_flow.db import init_fund_flow_schema, seed_default_fund_master

    path = tmp_path / "fresh" / "flow.db"
    seed_default_fund_master(path)
    with sqlite3.connect(path) as conn:
        rows = conn.execute('SELECT etf_code,name,fund_group FROM fund_master').fetchall()
        assert {code: {"name": name, "group": group} for code, name, group in rows} == ETF_UNIVERSE
        conn.execute("UPDATE fund_master SET name='custom' WHERE etf_code='510300.SH'")
        conn.execute("INSERT INTO fund_master(etf_code,name,fund_group) VALUES ('999999.SH','synthetic','extended')")
    init_fund_flow_schema(path)
    seed_default_fund_master(path)
    seed_default_fund_master(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM fund_master").fetchone()[0] == 7
        assert conn.execute("SELECT name FROM fund_master WHERE etf_code='510300.SH'").fetchone()[0] == "custom"


@pytest.fixture
def flow_conn(tmp_path):
    from scripts.fund_flow.db import open_fund_flow_connection, seed_default_fund_master

    path = tmp_path / "flow.db"
    seed_default_fund_master(path)
    conn = open_fund_flow_connection(path)
    conn.execute("INSERT INTO fund_flow_data_sources(source_id) VALUES ('synthetic')")
    conn.executemany("INSERT INTO fund_flow_import_jobs(import_batch_id,source_id,status) VALUES (?,'synthetic','pending')", [("batch-1",), ("batch-2",)])
    try:
        yield conn
    finally:
        conn.close()


def insert_record(conn, table, record):
    from dataclasses import asdict
    import json

    values = asdict(record)
    if "error_codes" in values:
        values["error_codes"] = json.dumps(values["error_codes"])
    conn.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))


def test_raw_batches_preserve_versions_and_reject_duplicates(flow_conn):
    import sqlite3

    table = "fund_flow_etf_daily_raw"
    insert_record(flow_conn, table, raw_record())
    with pytest.raises(sqlite3.IntegrityError):
        insert_record(flow_conn, table, raw_record())
    insert_record(flow_conn, table, raw_record(import_batch_id="batch-2", total_share=101))
    insert_record(flow_conn, table, raw_record(source_version="v2", total_share=102))
    assert flow_conn.execute(f"SELECT total_share FROM {table} ORDER BY total_share").fetchall() == [(100,), (101,), (102,)]


def test_index_raw_batches_preserve_versions(flow_conn):
    import sqlite3

    sql = """INSERT INTO fund_flow_index_daily_raw
+        (index_code,record_date,effective_trade_date,close,source_id,source_version,import_batch_id)
+        VALUES ('000300.SH','2024-01-02','2024-01-02',100,'synthetic','v1',?)""".replace('+', '')
    flow_conn.execute(sql, ("batch-1",))
    with pytest.raises(sqlite3.IntegrityError):
        flow_conn.execute(sql, ("batch-1",))
    flow_conn.execute(sql, ("batch-2",))
    assert flow_conn.execute("SELECT count(*) FROM fund_flow_index_daily_raw").fetchone()[0] == 2


def test_clean_scope_and_metric_version_keys(flow_conn):
    import sqlite3

    for table, factory, changes in (
        ("fund_flow_etf_daily_clean", clean_record, {"share_scope": "listed"}),
        ("fund_flow_etf_daily_metrics", metric_record, {"calc_version": "v2"}),
    ):
        insert_record(flow_conn, table, factory())
        with pytest.raises(sqlite3.IntegrityError):
            insert_record(flow_conn, table, factory())
        insert_record(flow_conn, table, factory(**changes))
        assert flow_conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 2


def test_database_rejects_unknown_status_and_retains_nulls(flow_conn):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        flow_conn.execute("UPDATE fund_flow_import_jobs SET status='unknown'")
    insert_record(flow_conn, "fund_flow_etf_daily_clean", clean_record(nav=None, validation_status="BLOCKED", error_codes=("missing_nav",)))
    with pytest.raises(sqlite3.IntegrityError):
        flow_conn.execute("UPDATE fund_flow_etf_daily_clean SET validation_status='valid'")
    assert flow_conn.execute("SELECT nav,error_codes FROM fund_flow_etf_daily_clean").fetchone() == (None, '["missing_nav"]')
    insert_record(flow_conn, "fund_flow_etf_daily_metrics", metric_record(net_flow_yi=None, status="BLOCKED"))
    with pytest.raises(sqlite3.IntegrityError):
        flow_conn.execute("UPDATE fund_flow_etf_daily_metrics SET status='complete'")
    assert flow_conn.execute("SELECT net_flow_yi FROM fund_flow_etf_daily_metrics").fetchone()[0] is None
