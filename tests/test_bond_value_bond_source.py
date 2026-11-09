import sys
from types import SimpleNamespace

import pandas as pd

from scripts.bond_value.service import _fetch_bond_yields


def test_akshare_adapter_selects_china_government_bond_curve(monkeypatch):
    frame = pd.DataFrame([
        {"曲线名称": "中债国债收益率曲线", "日期": "2026-11-06", "10年": 1.63},
        {"曲线名称": "中债商业银行普通债收益率曲线(AAA)", "日期": "2026-11-06", "10年": 1.85},
    ])
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        bond_china_yield=lambda start, end: frame,
    ))

    assert _fetch_bond_yields("2026-11-06", "2026-11-06") == [
        {"tradeDate": "20261106", "yieldPct": 1.63},
    ]
