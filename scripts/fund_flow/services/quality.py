"""Quality rules for daily ETF share/NAV observations."""

from __future__ import annotations

from datetime import date
import math
from typing import Sequence

from ..models import CleanETFRecord, QualityIssue


def validate_daily_records(rows: Sequence[CleanETFRecord]) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for row in rows:
        day = row.trade_date if isinstance(row.trade_date, date) else date.fromisoformat(row.trade_date)
        if row.shares_wan is None or not math.isfinite(float(row.shares_wan)) or row.shares_wan < 0:
            issues.append(QualityIssue(row.etf_code, day, "Q1_missing_shares", "份额缺失，不能计算净申赎", "BLOCKED"))
        if row.nav is None or not math.isfinite(float(row.nav)) or row.nav <= 0:
            issues.append(QualityIssue(row.etf_code, day, "Q2_missing_nav", "单位净值缺失或非正数", "BLOCKED"))
        if row.size_yi is not None and (not math.isfinite(float(row.size_yi)) or row.size_yi < 0):
            issues.append(QualityIssue(row.etf_code, day, "Q3_negative_size", "资产规模不能为负", "BLOCKED"))
        if row.share_scope not in {"on_exchange", "total_fund"}:
            issues.append(QualityIssue(row.etf_code, day, "Q4_unknown_scope", "份额口径未识别", "BLOCKED"))
        if row.validation_status == "BLOCKED":
            issues.append(QualityIssue(row.etf_code, day, "Q5_source_blocked", ";".join(row.error_codes) or "来源记录已阻断", "BLOCKED"))
        elif row.validation_status == "WARNING":
            issues.append(QualityIssue(row.etf_code, day, "Q6_source_warning", ";".join(row.error_codes) or "来源记录有警告", "WARNING"))
    return issues
