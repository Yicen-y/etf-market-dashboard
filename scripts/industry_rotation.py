"""Read-only Prism view of CSI industry total-return indexes versus Wind All A."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DATABASE_PATH
from .prism_metrics import calculate_prism_metrics

WIND_CODE = "881001.WI"
DIVIDEND_CODE = "H00922"


def catalog(database: Path = DATABASE_PATH) -> list[dict]:
    with sqlite3.connect(database) as db:
        industries = [dict(code=code, name=name, category=category)
                      for code, name, category in db.execute(
                          "SELECT index_code,name,rotation_category FROM industry_total_return_indices ORDER BY rowid")]
        if db.execute("SELECT 1 FROM index_prices WHERE index_code=? LIMIT 1", (DIVIDEND_CODE,)).fetchone():
            industries.append(dict(code=DIVIDEND_CODE, name="中证红利全收益", category="红利"))
        return industries


def prism(code: str, database: Path = DATABASE_PATH) -> dict:
    with sqlite3.connect(database) as db:
        item = ("中证红利全收益", "红利") if code == DIVIDEND_CODE and db.execute(
            "SELECT 1 FROM index_prices WHERE index_code=? LIMIT 1", (code,)).fetchone() else None
        if item is None:
            item = db.execute("""SELECT name,rotation_category FROM industry_total_return_indices
                                 WHERE index_code=? AND return_type='total_return'""", (code,)).fetchone()
        if item is None:
            raise ValueError("unknown industry total-return index")
        price_table = "index_prices" if code == DIVIDEND_CODE else "industry_total_return_prices"
        data = db.execute(f"""SELECT w.trade_date,w.close_value,p.close_value
            FROM wind_index_daily_prices w
            LEFT JOIN {price_table} p
              ON p.trade_date=REPLACE(w.trade_date,'-','') AND p.index_code=?
            WHERE w.wind_code=? AND w.verification_status='PASS'
            ORDER BY w.trade_date""", (code, WIND_CODE)).fetchall()
    records = [{"tradeDate": day.replace("-", ""),
                "values": {code: float(industry) if industry is not None else None,
                           WIND_CODE: float(wind)}} for day, wind, industry in data]
    if not records or not any(row["values"][code] is not None for row in records):
        raise ValueError("industry and Wind All A history unavailable")
    first = next(i for i, row in enumerate(records) if row["values"][code] is not None)
    last = len(records) - 1 - next(i for i, row in enumerate(reversed(records)) if row["values"][code] is not None)
    records = records[first:last + 1]
    rows = calculate_prism_metrics(records, code, WIND_CODE)
    return {"code": code, "name": item[0], "category": item[1],
            "benchmarkCode": WIND_CODE, "benchmarkName": "万得全A",
            "basisNote": ("中证红利使用全收益指数；万得全A使用本地指数点位。两者收益口径不同，信号仅供相对强弱观察。"
                          if code == DIVIDEND_CODE else
                          "行业为中证全收益指数；万得全A使用本地指数点位。两者收益口径不同，信号仅供相对强弱观察。"),
            "firstTradeDate": rows[0]["tradeDate"], "latestTradeDate": rows[-1]["tradeDate"],
            "rows": rows}
