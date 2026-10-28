from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "etf_prices.json"
INDEX_DATA_PATH = ROOT / "data" / "index_prices.json"
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

INDEXES = {
    "480080": {"name": "成长100R", "role": "growth_return", "sourceCode": "480080"},
    "480081": {"name": "价值100R", "role": "value_return", "sourceCode": "480081"},
    "H00821": {"name": "沪深300红利", "role": "dividend_total_return", "sourceCode": "H00821"},
    "H00300": {"name": "沪深300", "role": "hs300_total_return", "sourceCode": "H00300"},
    "H00918": {"name": "沪深300成长", "role": "growth_total_return", "sourceCode": "H00918"},
    "H00919": {"name": "沪深300价值", "role": "value_total_return", "sourceCode": "H00919"},
    "932000CNY010": {"name": "中证2000", "role": "csi2000_total_return", "sourceCode": "932000CNY010"},
    "H00811": {"name": "中证细分有色", "role": "nonferrous_total_return", "sourceCode": "H00811"},
    "H00813": {"name": "中证细分化工", "role": "chemical_total_return", "sourceCode": "H00813"},
    "H20180": {"name": "中证银行", "role": "banks_total_return", "sourceCode": "H20180"},
    "H20035": {"name": "沪深300非银金融", "role": "exbank_financial_total_return", "sourceCode": "H20035"},
    "H00922": {"name": "中证红利", "role": "dividend_total_return_2", "sourceCode": "H00922"},
    "H20903": {"name": "中证A股", "role": "a_share_total_return", "sourceCode": "H20903"},
}
INDEX_START_DATE = "20121231"

STRATEGIES = [
    {"id": "dividend-hs300", "name": "沪深300红利与沪深300轮动", "a": "H00821", "b": "H00300"},
    {"id": "growth-value-300", "name": "沪深300成长与沪深300价值轮动", "a": "H00918", "b": "H00919"},
    {"id": "csi2000-hs300", "name": "中证2000与沪深300轮动", "a": "932000CNY010", "b": "H00300"},
    {"id": "nonferrous-chemical", "name": "中证细分有色与中证细分化工轮动", "a": "H00811", "b": "H00813"},
    {"id": "banks-exbank-financial", "name": "中证银行与沪深300非银金融轮动", "a": "H20180", "b": "H20035"},
    {"id": "dividend-growth-300", "name": "沪深300红利与沪深300成长轮动", "a": "H00821", "b": "H00918"},
    {"id": "dividend-a-share", "name": "中证红利与中证A股轮动", "a": "H00922", "b": "H20903"},
]


