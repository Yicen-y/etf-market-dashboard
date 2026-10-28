from datetime import date
import akshare as ak


def fetch_product_history(product_code: str, start_date: str, end_date: str, api_key=None) -> list[dict]:
    frame = ak.fund_etf_hist_em(symbol=product_code, period="daily", start_date=start_date, end_date=end_date, adjust="")
    if frame is None or frame.empty:
        raise RuntimeError(f"AkShare returned no data for {product_code}")
    if not {"日期", "收盘"}.issubset(frame.columns):
        raise RuntimeError(f"AkShare response for {product_code} is missing required columns")
    return [{"tradeDate": str(row["日期"]).replace("-", ""), "productCode": product_code, "closePrice": float(row["收盘"])} for _, row in frame.iterrows()]


def current_end_date() -> str:
    return date.today().strftime("%Y%m%d")

