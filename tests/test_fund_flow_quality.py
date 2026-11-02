from scripts.fund_flow.models import CleanETFRecord
from scripts.fund_flow.services.quality import validate_daily_records
import math
from types import SimpleNamespace


def test_missing_nav_is_blocking_quality_issue():
    row = CleanETFRecord("510300.SH", "2024-01-02", 100, None, None, "on_exchange", "PASS", (), "test")
    issues = validate_daily_records([row])
    assert any(issue.code == "Q2_missing_nav" and issue.status == "BLOCKED" for issue in issues)


def test_unresolved_scope_is_blocking_quality_issue():
    row = CleanETFRecord("510300.SH", "2024-01-02", 100, 4, 0.04, "unknown", "PASS", (), "test")
    issues = validate_daily_records([row])
    assert any(issue.code == "Q4_unknown_scope" and issue.status == "BLOCKED" for issue in issues)


def test_non_finite_share_and_nav_are_blocked():
    row = SimpleNamespace(etf_code="510300.SH", trade_date="2024-01-02", shares_wan=math.inf, nav=math.nan, size_yi=None, share_scope="on_exchange", validation_status="PASS", error_codes=())
    issues = validate_daily_records([row])
    assert any(issue.code == "Q1_missing_shares" for issue in issues)
    assert any(issue.code == "Q2_missing_nav" for issue in issues)
