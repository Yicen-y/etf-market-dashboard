from datetime import date

import pytest

from scripts.fund_flow.models import RawETFRecord
from scripts.fund_flow.services.sync import SyncReport, calculate_flow_yi, sync_recent


def record(code, day, shares, nav=4.0):
    return RawETFRecord(
        etf_code=code,
        record_date=day,
        effective_trade_date=day,
        published_at=None,
        total_share=shares,
        share_unit="万份",
        share_scope="on_exchange",
        share_date_basis="post_close",
        nav=nav,
        close=None,
        total_size=None,
        source_id="synthetic",
        source_version="v1",
        import_batch_id="batch-1",
    )


def test_flow_formula_uses_share_delta_times_current_nav():
    previous = record("510300.SH", date(2024, 1, 2), 100, 4.0)
    current = record("510300.SH", date(2024, 1, 3), 110, 4.0)

    assert calculate_flow_yi(current, previous) == pytest.approx(0.004)


def test_sync_report_has_structured_provider_status(tmp_path):
    class Provider:
        def fetch(self, codes, start, end):
            return [record("510300.SH", start, 100)]

    report = sync_recent(
        tmp_path / "flow.db",
        share_providers=[Provider()],
        nav_provider=None,
        codes=["510300.SH"],
        start=date(2024, 1, 2),
        end=date(2024, 1, 2),
    )

    assert isinstance(report, SyncReport)
    assert report.inserted >= 1
    assert report.provider_status[0]["status"] == "success"

