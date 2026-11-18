"""Conservative gate for an explicitly reviewed ETF backup price feed."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path


def load_backup_policy(data_root: Path, symbol: str) -> dict | None:
    path = data_root / "source_policy.json"
    if not path.exists():
        return None
    raw = path.read_bytes()
    try:
        policy = json.loads(raw).get("etf", {}).get(symbol)
    except (ValueError, AttributeError, TypeError):
        return None
    if not isinstance(policy, dict) or policy.get("backup_upstream") != "Sina" or policy.get("price_basis") != "UNADJUSTED_CLOSE" or not policy.get("evidence_id"):
        return None
    return {**policy, "policy_sha256": hashlib.sha256(raw).hexdigest()}


def trusted_primary_overlaps(database: Path, data_root: Path, symbol: str, dates: set[str]) -> dict[str, float]:
    if not dates:
        return {}
    try:
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            rows = connection.execute("""SELECT c.trade_date,c.normalized_value,r.value_raw,r.source_version,r.raw_sha256,r.fetch_batch_id
            FROM canonical_observations c JOIN raw_observations r ON r.raw_record_id=c.selected_raw_id
            WHERE c.kind='etf' AND c.symbol=? AND r.upstream_publisher='Eastmoney'""", (symbol,)).fetchall()
    except sqlite3.Error:
        return {}
    verified = {}
    for day, value, raw_value, basis, digest, batch in rows:
        if (day not in dates or basis != "UNADJUSTED_CLOSE/v1" or not value
                or not math.isfinite(value) or not isinstance(digest, str)
                or len(digest) != 64 or not all(char in "0123456789abcdef" for char in digest)
                or not isinstance(batch, str) or not batch.isascii()
                or not batch.replace("-", "").replace("_", "").isalnum()):
            continue
        try:
            if float(raw_value) != value:
                continue
        except (TypeError, ValueError):
            continue
        folder = data_root / "raw" / "market" / batch
        for file in folder.glob(f"*-{digest[:16]}.bin"):
            try:
                if not file.is_symlink() and hashlib.sha256(file.read_bytes()).hexdigest() == digest:
                    verified[day] = value
                    break
            except OSError:
                continue
    return verified


def compare_backup(rows: list[dict], primary: dict[str, float], policy: dict) -> list[str]:
    """Compare price levels and interval returns only after basis review."""
    if not policy or policy.get("price_basis") != "UNADJUSTED_CLOSE" or not policy.get("evidence_id"):
        return ["BASIS_UNVERIFIED"]
    try:
        overlap = sorted((row["tradeDate"], float(row["closePrice"]), primary[row["tradeDate"]])
                         for row in rows if row["tradeDate"] in primary)
    except (ValueError, TypeError, KeyError):
        return ["INVALID_CANDIDATE_PRICE"]
    try:
        minimum = max(2, int(policy.get("min_overlap", 5)))
        price_limit = float(policy.get("max_price_relative_difference", 0.005))
        return_limit = float(policy.get("max_return_difference", 0.005))
    except (TypeError, ValueError):
        return ["INVALID_SOURCE_POLICY"]
    if len(overlap) < minimum:
        return ["INSUFFICIENT_PRIMARY_OVERLAP"]
    if not math.isfinite(price_limit) or not math.isfinite(return_limit) or not 0 <= price_limit <= 0.05 or not 0 <= return_limit <= 0.05:
        return ["INVALID_SOURCE_POLICY"]
    issues = []
    for day, candidate, reference in overlap:
        if not math.isfinite(candidate) or candidate <= 0 or abs(candidate / reference - 1) > price_limit:
            issues.append(f"PRICE_BASIS_OR_CORPORATE_ACTION_REVIEW:{day}")
    for previous, current in zip(overlap, overlap[1:]):
        day, candidate, reference = current
        _, old_candidate, old_reference = previous
        if candidate <= 0 or old_candidate <= 0 or not math.isfinite(candidate) or not math.isfinite(old_candidate) or abs(candidate / old_candidate - reference / old_reference) > return_limit:
            issues.append(f"RETURN_DIFFERENCE:{day}")
    return issues
