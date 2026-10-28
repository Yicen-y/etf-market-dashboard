from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "etf_prices.json"
DATABASE_PATH = ROOT / "data" / "etf_market.db"

PRODUCTS = {
    "512530": {"name": "沪深300红利ETF建信", "role": "dividend"},
    "562310": {"name": "沪深300成长ETF银华", "role": "growth"},
    "510330": {"name": "沪深300ETF华夏", "role": "benchmark"},
}

# AkShare returns data from the ETF's inception when the requested start date
# predates it. This keeps the database ready for arbitrary benchmark dates.
START_DATE = "20000101"

# Avoid querying periods before an ETF existed; Eastmoney may close those requests.
PRODUCT_START_DATES = {
    "512530": "20180101",
    "562310": "20210101",
    "510330": "20130101",
}


