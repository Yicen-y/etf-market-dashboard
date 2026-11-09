"""Read-only rotation summary from published snapshot metrics."""
import math

RULES = (
    ("ratio", "ratioMa242", "上穿比值均线", "下穿比值均线"),
    ("ratio", "ratioUpper242", "突破上轨", "跌回上轨内"),
    ("ratio", "ratioLower242", "回到下轨内", "跌破下轨"),
    ("return40Spread", 0, "收益差转正", "收益差转负"),
    ("return40Spread", "return40Ma242", "收益差上穿均线", "收益差下穿均线"),
    ("rsi14", 50, "RSI上穿50", "RSI下穿50"),
    ("rsi14", 30, "RSI离开30以下", "RSI进入30以下"),
    ("rsi14", 70, "RSI进入70以上", "RSI离开70以上"),
)


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def pair(row, field, threshold):
    if field == "return40Spread" and row.get("return40CoverageStatus", "PASS") != "PASS":
        return None
    value = number(row.get(field))
    limit = number(row.get(threshold)) if isinstance(threshold, str) else threshold
    return (value, limit) if value is not None and limit is not None else None


def side(values):
    value, limit = values
    return (value > limit) - (value < limit)


def summarize_strategy(strategy, rows, dates):
    by_day = {row["tradeDate"]: row for row in rows}
    events, states, previous = [], [], {}
    for position, day in enumerate(dates):
        row = by_day.get(day, {})
        states = []
        for field, threshold, up, down in RULES:
            key = (field, threshold)
            current = pair(row, field, threshold)
            old, duration = previous.get(key, (None, 0))
            if current is None:
                previous.pop(key, None)
                continue
            direction = side(current)
            old_direction = side(old) if old else None
            duration = duration + 1 if direction == old_direction else 1
            previous[key] = (current, duration)
            states.append(dict(field=field, threshold=threshold, direction=direction, days=duration))
            if position >= len(dates) - 5 and old and direction and direction != old_direction:
                events.append(dict(strategy=strategy["id"], date=day, label=up if direction > 0 else down,
                                   field=field, previous=old[0], previous_threshold=old[1],
                                   value=current[0], threshold=current[1]))
    latest = dates[-1]
    current = by_day.get(latest, {})
    valid_dates = [day for day in dates if number(by_day.get(day, {}).get("ratio")) is not None]
    data_date = valid_dates[-1] if valid_dates else None
    spread = pair(current, "return40Spread", 0)
    ratio = pair(current, "ratio", "ratioMa242")
    incomplete = len(states) != len(RULES)
    return {**strategy, "data_date": data_date, "spread": spread[0] if spread else None,
            "distance": ratio[0] / ratio[1] - 1 if ratio and ratio[1] else None,
            "rsi": number(current.get("rsi14")), "states": states,
            "quality": "数据落后或缺失" if data_date != latest else "部分指标缺失或窗口有缺口" if incomplete else "完整",
            "events": sorted(events, key=lambda event: event["date"], reverse=True)}


def summarize_etf(etf, observation):
    rows = [row for row in etf["records"] if row["tradeDate"] <= observation]
    base = next((row for row in reversed(rows) if row["tradeDate"] <= "20251231"), None)
    last = rows[-1] if rows else None
    returns = {}
    for code, product in etf["products"].items():
        a = number(base["prices"].get(code)) if base else None
        b = number(last["prices"].get(code)) if last else None
        returns[code] = dict(name=product["name"], value=b / a - 1 if a and b else None)
    a, b = (returns.get(code, {}).get("value") for code in ("512530", "562310"))
    return dict(base_date=base["tradeDate"] if base else None, data_date=last["tradeDate"] if last else None,
                returns=returns, spread=a-b if a is not None and b is not None else None,
                portfolio=(a+b)/2 if a is not None and b is not None else None)


def build_overview(snapshot_id, index, etf):
    dates = sorted(set(index["tradingCalendar"]["dates"]))
    if not dates:
        raise ValueError("快照缺少参考交易日历")
    configs = [{"id": "prism", "name": "成长100R / 价值100R", "a": "480080", "b": "480081"}, *index["strategies"]]
    groups = [summarize_strategy(item, index["records"] if item["id"] == "prism"
                                else index.get("strategyMetrics", {}).get(item["id"], []), dates)
              for item in configs]
    for group in groups:
        for side in ("a", "b"):
            group[side + "_name"] = index.get("indexes", {}).get(group.get(side), {}).get("name")
    return dict(snapshot_id=snapshot_id, observation_date=dates[-1], recent_dates=dates[-5:],
                formula_version=index.get("metricFormulaVersion"), rule_version="rotation-overview-v1",
                groups=groups, etf=summarize_etf(etf, dates[-1]))
