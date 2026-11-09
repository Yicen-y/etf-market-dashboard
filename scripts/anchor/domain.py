"""Pure indicator calculations on an explicit trading calendar."""

from collections import deque
from math import isfinite


def indicators(calendar, observations, window=1250, upper=0.15, lower=0.15, rsi_period=90):
    calendar = list(calendar)
    if window < 1 or rsi_period < 1 or not isfinite(upper) or not isfinite(lower) or not 0 <= upper or not 0 <= lower:
        raise ValueError("invalid indicator parameters")
    if list(calendar) != sorted(set(calendar)):
        raise ValueError("calendar must be sorted and unique")
    calendar_days = set(calendar)
    if any(day not in calendar_days for day in observations):
        raise ValueError("observation outside trading calendar")
    for value in observations.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
            raise ValueError("index values must be finite and positive")
    prices = deque(maxlen=window)
    changes = deque(maxlen=rsi_period)
    previous = avg_gain = avg_loss = None
    gap_seen = False
    result = []
    for day in calendar:
        price = observations.get(day)
        if price is None:
            prices.clear(); changes.clear()
            gap_seen = True
            previous = avg_gain = avg_loss = None
            result.append({'tradeDate': day, 'close': None, 'ma': None, 'upper': None, 'lower': None, 'deviation': None, 'rsi': None, 'quality': 'BLOCKED'})
            continue
        prices.append(price)
        rsi = None
        if previous is not None:
            delta = price - previous
            gain, loss = max(delta, 0), max(-delta, 0)
            if avg_gain is None:
                changes.append((gain, loss))
                if len(changes) == rsi_period:
                    avg_gain = sum(x[0] for x in changes) / rsi_period
                    avg_loss = sum(x[1] for x in changes) / rsi_period
            else:
                avg_gain = (avg_gain * (rsi_period - 1) + gain) / rsi_period
                avg_loss = (avg_loss * (rsi_period - 1) + loss) / rsi_period
            if avg_gain is not None:
                rsi = 50.0 if avg_gain == avg_loss == 0 else 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
        previous = price
        ma = sum(prices) / window if len(prices) == window else None
        result.append({'tradeDate': day, 'close': price, 'ma': ma, 'upper': ma * (1 + upper) if ma is not None else None, 'lower': ma * (1 - lower) if ma is not None else None, 'deviation': price / ma - 1 if ma is not None else None, 'rsi': rsi, 'quality': 'READY' if ma is not None else ('BLOCKED' if gap_seen else 'INSUFFICIENT_HISTORY')})
    return result


def compare_indexes(series, base_date):
    """Align by date and normalize using the latest common date at or before base_date."""
    codes = list(series)
    if len(codes) != 2:
        raise ValueError('exactly two indices are required')
    indexed = {code: {row['tradeDate']: row for row in rows} for code, rows in series.items()}
    common = sorted(set(indexed[codes[0]]) & set(indexed[codes[1]]))
    bases = [day for day in common if day <= base_date and all(indexed[c][day]['close'] is not None for c in codes)]
    if not bases:
        raise ValueError('所选基准日前没有两个指数的共同交易日')
    base = bases[-1]
    result = []
    for day in common:
        left, right = (indexed[c][day] for c in codes)
        result.append({'tradeDate': day, 'deviationSpread': None if left['deviation'] is None or right['deviation'] is None else right['deviation'] - left['deviation'], 'normalized': {c: None if indexed[c][day]['close'] is None else indexed[c][day]['close'] / indexed[c][base]['close'] * 100 for c in codes}})
    return {'baseDate': base, 'rows': result}
