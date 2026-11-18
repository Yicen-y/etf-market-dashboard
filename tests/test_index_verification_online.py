"""Opt-in live-provider checks: RUN_INDEX_ONLINE=1 python -m pytest this_file -q."""
import os
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.config import DATABASE_PATH, DATA_ROOT
from scripts.index_verification import _fetch, reconcile


@pytest.mark.skipif(os.getenv("RUN_INDEX_ONLINE") != "1", reason="live provider test is opt-in")
@pytest.mark.parametrize("code", ["H00821", "H00918", "H00300"])
@pytest.mark.parametrize("start,end", [("20130603","20130701"),("20261008","20261111")])
def test_live_csi_reference_matches_saved_market_without_mutation(code,start,end):
    manifest=hashlib.sha256((DATA_ROOT/"current_manifest.json").read_bytes()).hexdigest()
    snapshot=hashlib.sha256((DATA_ROOT/"index_prices.json").read_bytes()).hexdigest()
    with sqlite3.connect(DATABASE_PATH) as db:
        before=hashlib.sha256(json.dumps(db.execute("SELECT trade_date,index_code,close_value,source,updated_at FROM index_prices ORDER BY trade_date,index_code").fetchall(),ensure_ascii=False).encode()).hexdigest()
        local=[{"tradeDate":day,"closeValue":price} for day,price in db.execute(
            "SELECT trade_date,close_value FROM index_prices WHERE index_code=? AND trade_date BETWEEN ? AND ? ORDER BY trade_date",(code,start,end))]
    result = _fetch(code, start, end)
    assert result.upstream == "CSI"
    assert result.raw_bytes
    assert result.rows
    assert all(row["indexCode"] == code for row in result.rows)
    assert all(row["closeValue"] > 0 for row in result.rows)
    matches=reconcile(local,result.rows,identity="MATCH")
    assert len(local)>=15
    assert all(item["status"]=="MATCH" for item in matches)
    with sqlite3.connect(DATABASE_PATH) as db:
        after=hashlib.sha256(json.dumps(db.execute("SELECT trade_date,index_code,close_value,source,updated_at FROM index_prices ORDER BY trade_date,index_code").fetchall(),ensure_ascii=False).encode()).hexdigest()
    assert after==before
    assert hashlib.sha256((DATA_ROOT/"current_manifest.json").read_bytes()).hexdigest()==manifest
    assert hashlib.sha256((DATA_ROOT/"index_prices.json").read_bytes()).hexdigest()==snapshot


@pytest.mark.skipif(os.getenv("RUN_INDEX_ONLINE") != "1", reason="live provider test is opt-in")
@pytest.mark.parametrize("code", ["480080", "480081"])
@pytest.mark.parametrize("start,end", [("20130603","20130701"),("20261008","20261111")])
def test_live_cni_reference_has_raw_http_and_same_point_values(code,start,end):
    manifest=hashlib.sha256((DATA_ROOT/"current_manifest.json").read_bytes()).hexdigest()
    snapshot=hashlib.sha256((DATA_ROOT/"index_prices.json").read_bytes()).hexdigest()
    with sqlite3.connect(DATABASE_PATH) as db:
        before=hashlib.sha256(json.dumps(db.execute("SELECT trade_date,index_code,close_value,source,updated_at FROM index_prices ORDER BY trade_date,index_code").fetchall(),ensure_ascii=False).encode()).hexdigest()
        local=[{"tradeDate":day,"closeValue":price} for day,price in db.execute(
            "SELECT trade_date,close_value FROM index_prices WHERE index_code=? AND trade_date BETWEEN ? AND ? ORDER BY trade_date",(code,start,end))]
    result=_fetch(code,start,end)
    assert result.upstream == "CNI"
    assert result.provider == "CNI official HTTPS"
    assert result.raw_bytes and len(local)>=15
    assert all(row["indexCode"]==code for row in result.rows)
    matches=reconcile(local,result.rows,identity="MATCH",decimals=4)
    assert all(item["status"]=="MATCH" for item in matches)
    with sqlite3.connect(DATABASE_PATH) as db:
        after=hashlib.sha256(json.dumps(db.execute("SELECT trade_date,index_code,close_value,source,updated_at FROM index_prices ORDER BY trade_date,index_code").fetchall(),ensure_ascii=False).encode()).hexdigest()
    assert after==before
    assert hashlib.sha256((DATA_ROOT/"current_manifest.json").read_bytes()).hexdigest()==manifest
    assert hashlib.sha256((DATA_ROOT/"index_prices.json").read_bytes()).hexdigest()==snapshot
