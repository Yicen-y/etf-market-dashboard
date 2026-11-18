"""Explicit local reviewer decisions bound to an archived candidate payload."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def approved(data_root: Path, symbol: str, digest: str) -> str | None:
    try:
        decisions = json.loads((data_root / "source_approvals.json").read_text(encoding="utf-8"))
        value = decisions.get(symbol, {}).get(digest)
        return value if isinstance(value, str) and value.strip() else None
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def record_approval(data_root: Path, symbol: str, digest: str, evidence_id: str) -> None:
    if not re.fullmatch(r"\d{6}", symbol) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid candidate identity")
    if not 3 <= len(evidence_id.strip()) <= 200:
        raise ValueError("review evidence is required")
    path = data_root / "source_approvals.json"
    try:
        decisions = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        decisions = {}
    if not isinstance(decisions, dict):
        raise ValueError("invalid approval store")
    decisions.setdefault(symbol, {})[digest] = evidence_id.strip()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
