import json
from pathlib import Path


GUIDE_PATH = Path(__file__).parents[1] / "web" / "strategy-guides.json"


def test_strategy_guides_cover_current_dashboards_and_formulas():
    guides = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))

    assert {"etf", "prism"}.issubset(guides)
    assert guides["etf"]["sections"]
    assert guides["prism"]["sections"]

    prism_formulas = [
        item
        for section in guides["prism"]["sections"]
        for item in section.get("items", []) + section.get("formulas", [])
        if isinstance(item, dict) and "formula" in item
    ]
    assert len(prism_formulas) >= 8
    assert all("\\[" in item["formula"] and "\\]" in item["formula"] for item in prism_formulas)


def test_prism_guide_documents_five_usage_methods():
    prism = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))["prism"]
    uses_section = next(section for section in prism["sections"] if section["type"] == "uses")

    assert len(uses_section["items"]) == 5
    assert [item["number"] for item in uses_section["items"]] == [
        "用法一",
        "用法二",
        "用法三",
        "用法四",
        "用法五",
    ]
