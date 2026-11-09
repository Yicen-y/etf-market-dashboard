from pathlib import Path


WEB = Path("web")


def test_research_page_exposes_all_three_live_research_views_and_controls():
    html = (WEB / "dividend-research.html").read_text(encoding="utf-8")
    for element_id in ("yield-chart", "ah-chart", "reg-chart", "yield-table", "ah-table", "yield-range", "yield-refresh", "yield-export"):
        assert f'id="{element_id}"' in html
    for element_id in ("ah-backtest", "ah-cost-bps", "ah-backtest-table"):
        assert f'id="{element_id}"' in html
    assert "A股 / 港股红利动量" in html
    assert "中证红利官方股息率2" in html


def test_research_script_has_real_api_and_no_static_missing_placeholders():
    script = (WEB / "dividend-research.js").read_text(encoding="utf-8")
    assert "/api/research/dividend-yield" in script
    assert "/api/research/dividend-ah" in script
    assert "/api/research/refresh" in script
    assert "download" in script
    assert "MISSING_OFFICIAL" in script
    assert "MISSING_SERIES" in script
    assert "/api/research/dividend-ah-backtest" in script


def test_yield_chart_binds_legend_colors_to_series_colors():
    script = (WEB / "dividend-research.js").read_text(encoding="utf-8")
    assert 'name:"中证红利股息率2",type:"line",color:"#c9362b"' in script
    assert 'name:"中债国债收益率曲线10Y",type:"line",color:"#2c6bed"' in script
    assert 'name:"股息率利差（pp）",type:"line",color:"#16834a"' in script
