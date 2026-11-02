"""The fund flow universe uses the existing dashboard database."""

from scripts.config import DATABASE_PATH

ETF_UNIVERSE = {
    "510300.SH": {"name": "华泰柏瑞沪深300ETF", "group": "core"},
    "510310.SH": {"name": "易方达沪深300ETF", "group": "core"},
    "510330.SH": {"name": "华夏沪深300ETF", "group": "core"},
    "159919.SZ": {"name": "嘉实沪深300ETF", "group": "core"},
    "510320.SH": {"name": "中金沪深300ETF", "group": "extended"},
    "510350.SH": {"name": "工银瑞信沪深300ETF", "group": "extended"},
}

PRESET_GROUPS = {
    "original_shanghai_five": ("510300.SH", "510310.SH", "510320.SH", "510330.SH", "510350.SH"),
    "core_four": ("510300.SH", "510310.SH", "510330.SH", "159919.SZ"),
    "all_six": tuple(ETF_UNIVERSE),
}
