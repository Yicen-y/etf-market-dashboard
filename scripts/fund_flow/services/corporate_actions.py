"""Auditable ETF corporate-action handling.

An event is only applied after its accounting basis is verified.  A large
share jump by itself is a candidate, never an automatic adjustment.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
from pathlib import Path
from typing import Iterable, Sequence

from ..models import CorporateAction, CleanETFRecord, QualityIssue, RawETFRecord


_STATUS_ORDER = {
    "discovered": 0,
    "source_verified": 1,
    "basis_verified": 2,
    "applied": 3,
    "rejected": -1,
}


def _as_date(value):
    return value if isinstance(value, date) else date.fromisoformat(value)


def validate_corporate_action(action: CorporateAction) -> list[QualityIssue]:
    """Return blocking issues for events which cannot safely be applied."""

    event_date = _as_date(action.ex_date)
    issues: list[QualityIssue] = []
    if action.status == "rejected":
        issues.append(QualityIssue(action.etf_code, event_date, "corporate_action_rejected", "公司行为已被拒绝", "BLOCKED"))
        return issues
    if action.ratio is None or action.ratio <= 0:
        issues.append(QualityIssue(action.etf_code, event_date, "corporate_action_ratio_missing", "公司行为缺少有效折算比例", "BLOCKED"))
    if action.status not in {"basis_verified", "applied"} or action.first_post_record_date is None:
        issues.append(QualityIssue(action.etf_code, event_date, "corporate_action_unverified", "公司行为尚未核验首个调整后记录日，暂不复权", "BLOCKED"))
    if action.first_post_record_date is not None and _as_date(action.first_post_record_date) <= event_date:
        issues.append(QualityIssue(action.etf_code, event_date, "corporate_action_date_order", "首个调整后记录日必须晚于事件日", "BLOCKED"))
    return issues


def _applicable_actions(actions: Iterable[CorporateAction]) -> list[CorporateAction]:
    result = []
    for action in actions:
        if not validate_corporate_action(action):
            result.append(action)
    return sorted(result, key=lambda item: _as_date(item.first_post_record_date))


def apply_share_unit_adjustment(
    rows: Sequence[RawETFRecord], actions: Sequence[CorporateAction]
) -> list[CleanETFRecord]:
    """Normalize historical share/NAV units across verified share events."""

    valid_actions = _applicable_actions(actions)
    output: list[CleanETFRecord] = []
    for row in sorted(rows, key=lambda item: (_as_date(item.effective_trade_date), item.etf_code)):
        shares = row.total_share
        nav = row.nav
        errors: list[str] = []
        status = "PASS"
        for action in actions:
            if action.etf_code != row.etf_code:
                continue
            issues = validate_corporate_action(action)
            # An unresolved event blocks calculations at and after the event;
            # observations before it remain usable for historical context.
            if issues and _as_date(row.effective_trade_date) >= _as_date(action.ex_date):
                status = "BLOCKED"
                errors.extend(issue.code for issue in issues)
        for action in valid_actions:
            if action.etf_code != row.etf_code or shares is None or nav is None:
                continue
            if _as_date(row.effective_trade_date) < _as_date(action.first_post_record_date):
                shares *= action.ratio
                nav /= action.ratio
        size_yi = None if shares is None or nav is None else shares * nav / 10000
        output.append(CleanETFRecord(
            etf_code=row.etf_code,
            trade_date=row.effective_trade_date,
            shares_wan=shares,
            nav=nav,
            size_yi=size_yi if size_yi is None or size_yi >= 0 else None,
            share_scope=row.share_scope,
            validation_status=status,
            error_codes=tuple(sorted(set(errors))),
            source_id=row.source_id,
        ))
    return output


def detect_candidate_actions(
    rows: Sequence[RawETFRecord], share_jump_threshold: float = 0.10
) -> list[CorporateAction]:
    """Create review-only candidates from abrupt share changes."""

    candidates: list[CorporateAction] = []
    grouped: dict[str, list[RawETFRecord]] = {}
    for row in rows:
        grouped.setdefault(row.etf_code, []).append(row)
    for code, code_rows in grouped.items():
        code_rows.sort(key=lambda item: _as_date(item.effective_trade_date))
        for previous, current in zip(code_rows, code_rows[1:]):
            if not previous.total_share or current.total_share is None:
                continue
            jump = current.total_share / previous.total_share - 1
            if abs(jump) >= share_jump_threshold:
                candidates.append(CorporateAction(
                    etf_code=code,
                    ex_date=current.effective_trade_date,
                    event_date=current.effective_trade_date,
                    action_type="candidate_share_jump",
                    ratio=current.total_share / previous.total_share,
                    status="discovered",
                ))
    return candidates


def load_seed_action(name: str, root: Path | None = None) -> CorporateAction:
    root = root or Path(__file__).resolve().parents[3]
    path = root / "data" / "source_events" / f"{name}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CorporateAction(
        etf_code=payload["etf_code"],
        ex_date=payload["ex_date"],
        event_date=payload.get("event_date"),
        action_type=payload["action_type"],
        ratio=payload.get("ratio"),
        first_post_record_date=payload.get("first_post_record_date"),
        status=payload.get("status", "source_verified"),
        value=payload.get("value"),
    )
