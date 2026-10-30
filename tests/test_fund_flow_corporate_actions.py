from datetime import date

from scripts.fund_flow.models import CorporateAction, RawETFRecord
from scripts.fund_flow.services.corporate_actions import (
    apply_share_unit_adjustment,
    detect_candidate_actions,
    load_seed_action,
    validate_corporate_action,
)


def raw(day, shares, nav):
    return RawETFRecord(
        etf_code="510310.SH", record_date=day, effective_trade_date=day,
        published_at="2024-01-01T18:00:00", total_share=shares, share_unit="万份",
        share_scope="on_exchange", share_date_basis="post_close", nav=nav,
        close=None, total_size=None, source_id="test", source_version="v1", import_batch_id="b1",
    )


def test_two_for_one_consolidation_preserves_economic_value():
    action = CorporateAction(
        etf_code="510310.SH", action_type="consolidation", event_date="2024-01-02",
        ex_date="2024-01-02", ratio=0.5, first_post_record_date="2024-01-03",
        status="basis_verified",
    )
    cleaned = apply_share_unit_adjustment([raw("2024-01-02", 100, 2), raw("2024-01-03", 50, 4)], [action])
    assert cleaned[0].shares_wan == 50
    assert cleaned[0].nav == 4
    assert cleaned[1].shares_wan == 50
    assert cleaned[1].nav == 4


def test_510310_seed_without_first_post_record_is_blocked():
    action = load_seed_action("510310_consolidation")
    assert action.ratio == 0.49977589
    assert action.status == "source_verified"
    assert "corporate_action_unverified" in validate_corporate_action(action)[0].code


def test_large_jump_is_review_candidate_only():
    candidates = detect_candidate_actions([raw("2024-01-01", 100, 2), raw("2024-01-02", 50, 4)])
    assert len(candidates) == 1
    assert candidates[0].status == "discovered"


def test_cash_dividend_is_not_a_share_unit_adjustment():
    action = CorporateAction(
        etf_code="510310.SH", action_type="cash_dividend", event_date="2024-01-02",
        ex_date="2024-01-02", ratio=0.5, first_post_record_date="2024-01-03",
        status="basis_verified",
    )
    assert validate_corporate_action(action)[0].code == "corporate_action_type_unsupported"

