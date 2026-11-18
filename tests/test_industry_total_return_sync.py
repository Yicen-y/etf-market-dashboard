import hashlib
import sqlite3

import pytest

from scripts.fetch_data import FetchResult
from scripts.industry_total_return_sync import INDICES, sync, validate
from scripts import industry_total_return_sync as industry_sync
from scripts import daily_verified


def result(code, *, name="Test Total Return Index", dates=("20190101", "20190102", "20190103")):
    raw = code.encode()
    return FetchResult(
        [{"tradeDate": day, "indexCode": code, "closeValue": 1000 + i,
          "indexNameEnAll": name} for i, day in enumerate(dates)],
        "CSI official HTTP", "CSI", {}, raw_bytes=raw,
        source_url="https://www.csindex.com.cn/csindex-home/perf/index-perf")


def test_validation_removes_only_boundary_holiday_and_rejects_wrong_basis():
    code = "H20596"
    calendar = {"20190102", "20190103"}
    assert validate(result(code), code, calendar, "20190101", "20190103") == [
        ("20190102", 1001.0), ("20190103", 1002.0)]
    with pytest.raises(ValueError, match="total-return"):
        validate(result(code, name="Price Index"), code, calendar, "20190101", "20190103")
    with pytest.raises(ValueError, match="non-trading"):
        validate(result(code, dates=("20190102", "20190104")), code, calendar,
                 "20190101", "20190104")


def test_sync_stores_all_series_and_verifiable_raw_payloads(tmp_path):
    database = tmp_path / "market.db"
    rows = sync(database, start="20190101", end="20190103",
                fetcher=lambda code, _start, _end: result(code),
                calendar_fetcher=lambda _start, _end: ["20190102", "20190103"])
    assert len(rows) == len(INDICES) == 17
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM industry_total_return_prices").fetchone()[0] == 34
        assert db.execute("SELECT COUNT(*) FROM industry_total_return_indices").fetchone()[0] == 17
        assert all(hashlib.sha256(raw).hexdigest() == digest for raw, digest in
                   db.execute("SELECT raw_payload,raw_sha256 FROM industry_total_return_batches"))


def test_incremental_sync_fetches_only_tail_and_updates_revisions(tmp_path, monkeypatch):
    monkeypatch.setattr(industry_sync, "INDICES", (("H20596", "煤炭", "周期"),))
    database = tmp_path / "market.db"
    calls = []
    values = {"20261110": 100.0, "20261111": 101.0, "20261112": 102.0}

    def fetcher(code, start, end):
        calls.append((code, start, end))
        return FetchResult(
            [{"tradeDate": day, "indexCode": code, "closeValue": value,
              "indexNameEnAll": "Coal Total Return Index"}
             for day, value in values.items() if start <= day <= end],
            "CSI official HTTP", "CSI", {}, raw_bytes=str(values).encode(),
            source_url="https://www.csindex.com.cn/csindex-home/perf/index-perf")

    calendar = lambda _start, _end: list(values)
    first = sync(database, start="20261101", end="20261112", fetcher=fetcher,
                 calendar_fetcher=calendar)
    assert first[0]["added"] == 3
    with sqlite3.connect(database) as db:
        original_batch = db.execute("SELECT batch_id FROM industry_total_return_prices WHERE trade_date='20261110'").fetchone()[0]

    values["20261111"] = 101.5
    values["20261113"] = 103.0
    second = sync(database, start="20261101", end="20261113", fetcher=fetcher,
                  calendar_fetcher=calendar)
    assert calls[-1] == ("H20596", "20261105", "20261113")
    assert second[0]["added"] == 1 and second[0]["revised"] == 1
    third = sync(database, start="20261101", end="20261113", fetcher=fetcher,
                 calendar_fetcher=calendar)
    assert third[0]["added"] == third[0]["revised"] == 0
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM industry_total_return_prices").fetchone()[0] == 4
        assert db.execute("SELECT close_value FROM industry_total_return_prices WHERE trade_date='20261111'").fetchone()[0] == 101.5
        assert db.execute("SELECT batch_id FROM industry_total_return_prices WHERE trade_date='20261110'").fetchone()[0] == original_batch


def test_daily_command_runs_incremental_industry_sync_and_verify_only_skips_it(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(daily_verified, "run_daily", lambda **kwargs: {
        "through": "20261117", "indexes": {}, "publication": {"status": "PUBLISHED"}})
    monkeypatch.setattr(daily_verified, "sync_industry_total_return", lambda **kwargs: (
        calls.append(kwargs) or [{"added": 1, "revised": 2}] * 17))
    daily_verified.main(["--through", "20261117", "--industry-overlap-days", "5"])
    assert calls == [{"end": "20261117", "overlap_days": 5}]
    assert '"added": 17' in capsys.readouterr().out
    daily_verified.main(["--verify-only", "--through", "20261117"])
    assert len(calls) == 1
    assert "SKIPPED_VERIFY_ONLY" in capsys.readouterr().out
