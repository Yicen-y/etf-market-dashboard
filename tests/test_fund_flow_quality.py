from scripts.fund_flow.models import CleanETFRecord
from scripts.fund_flow.services.quality import validate_daily_records


def test_missing_nav_is_blocking_quality_issue():
    row = CleanETFRecord("510300.SH", "2024-01-02", 100, None, None, "on_exchange", "PASS", (), "test")
    issues = validate_daily_records([row])
    assert any(issue.code == "Q2_missing_nav" and issue.status == "BLOCKED" for issue in issues)


def test_unresolved_scope_is_blocking_quality_issue():
    row = CleanETFRecord("510300.SH", "2024-01-02", 100, 4, 0.04, "unknown", "PASS", (), "test")
    issues = validate_daily_records([row])
    assert any(issue.code == "Q4_unknown_scope" and issue.status == "BLOCKED" for issue in issues)
