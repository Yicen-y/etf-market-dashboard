from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "etf_prices.json"

PRODUCTS = {
    "512530": {"name": "沪深300红利ETF建信", "role": "dividend"},
    "562310": {"name": "沪深300成长ETF银华", "role": "growth"},
    "510330": {"name": "沪深300ETF华夏", "role": "benchmark"},
}

START_DATE = "20251231"


