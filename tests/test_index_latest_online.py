"""Opt-in live issuer availability for a caller supplied complete trade date.

RUN_INDEX_ONLINE=1 INDEX_ONLINE_TARGET=YYYYMMDD pytest this_file -q
"""
import hashlib
import os

import pytest

from scripts.config import INDEXES
from scripts.index_verification import _fetch


@pytest.mark.skipif(os.getenv("RUN_INDEX_ONLINE") != "1" or not os.getenv("INDEX_ONLINE_TARGET"),
                    reason="live target date must be explicitly supplied")
@pytest.mark.parametrize("code", list(INDEXES))
def test_issuer_returns_target_close_with_raw_response(code):
    target = os.environ["INDEX_ONLINE_TARGET"]
    result = _fetch(code,target,target)
    assert result.provider in ("CSI official HTTP", "CNI official HTTPS")
    assert result.upstream == ("CNI" if code in ("480080","480081") else "CSI")
    assert result.raw_sha256 == hashlib.sha256(result.raw_bytes).hexdigest()
    assert any(row["tradeDate"] == target and row["indexCode"] == code and row["closeValue"] > 0
               for row in result.rows)
