from scripts.config import PRODUCTS


def test_required_products_are_configured():
    assert set(PRODUCTS) == {"512530", "562310", "510330"}
    assert PRODUCTS["512530"]["role"] == "dividend"
    assert PRODUCTS["562310"]["role"] == "growth"
    assert PRODUCTS["510330"]["role"] == "benchmark"

