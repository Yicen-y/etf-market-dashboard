"""Pure, point-in-time-safe research calculations for the dividend dashboards."""

from __future__ import annotations

from datetime import date
from math import exp, isfinite, log, sqrt
from statistics import mean, median


def condition_forward_returns(signal_rows, index_rows, *, horizons=(20, 60, 120, 252)):
    """Descriptive forward returns for PIT signals; execution starts at T+1 close."""
    prices = _clean_series(index_rows)
    dates = [day for day, _ in prices]
    values = [value for _, value in prices]
    if any(row.get("mode") != "expanding_point_in_time" for row in signal_rows):
        raise ValueError("condition returns require point-in-time signals")
    signal_by_day = {row["tradeDate"]: row.get("z") for row in signal_rows}
    buckets = (("z_below_minus_1_5", lambda z: z < -1.5), ("z_minus_1_5_to_0", lambda z: -1.5 <= z < 0),
               ("z_0_to_plus_1_5", lambda z: 0 <= z <= 1.5), ("z_above_plus_1_5", lambda z: z > 1.5))
    output = []
    position = {day: i for i, day in enumerate(dates)}
    for horizon in horizons:
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
            raise ValueError("horizons must be positive trading-day integers")
        all_samples = []
        for day, z in signal_by_day.items():
            if z is None or day not in position:
                continue
            i = position[day]
            start_i, end_i = i + 1, i + horizon + 1
            if end_i >= len(values):
                continue
            returns = values[end_i] / values[start_i] - 1
            path = [1.0] + [values[j] / values[start_i] for j in range(start_i + 1, end_i + 1)]
            peak = 0.0
            max_drawdown = 0.0
            for level in path:
                peak = max(peak, level)
                if peak:
                    max_drawdown = min(max_drawdown, level / peak - 1)
            all_samples.append((i, returns, max_drawdown))
        baseline_values = [value for _, value, _ in all_samples]
        baseline_mean = mean(baseline_values) if baseline_values else None
        sample_by_position = {item[0]: item for item in all_samples}
        for name, predicate in (("all_signals", lambda z: True), *buckets):
            samples = all_samples if name == "all_signals" else []
            if name != "all_signals":
                samples = []
            for day, z in signal_by_day.items():
                if name == "all_signals" or z is None or day not in position or not predicate(z):
                    continue
                i = position[day]
                match = sample_by_position.get(i)
                if match is not None:
                    samples.append(match)
            samples.sort(key=lambda item: item[0])
            returns = [value for _, value, _ in samples]
            nonoverlap, last = [], -1
            for i, value, _ in samples:
                if i > last:
                    nonoverlap.append(value)
                    last = i + horizon
            bucket_mean = mean(returns) if returns else None
            excess = bucket_mean - baseline_mean if bucket_mean is not None and baseline_mean is not None else None
            hac_se = None
            if excess is not None:
                bucket_positions = {i for i, _, _ in samples}
                n_bucket = len(samples)
                n_all = len(all_samples)
                centered = [0.0] * len(dates)
                for i, value, _ in all_samples:
                    contribution = 0.0
                    if i in bucket_positions:
                        contribution += (value - bucket_mean) / n_bucket
                    contribution -= (value - baseline_mean) / n_all
                    centered[i] = contribution
                variance_of_sum = sum(value * value for value in centered)
                for lag in range(1, min(max(0, horizon - 1), len(centered) - 1) + 1):
                    weight = 1 - lag / (horizon + 1)
                    covariance_sum = sum(centered[i] * centered[i - lag] for i in range(lag, len(centered)))
                    variance_of_sum += 2 * weight * covariance_sum
                hac_se = sqrt(max(0.0, variance_of_sum))
            ci_low = excess - 1.96 * hac_se if excess is not None and hac_se is not None else None
            ci_high = excess + 1.96 * hac_se if excess is not None and hac_se is not None else None
            output.append({"bucket": name, "horizon": horizon, "sampleCount": len(returns),
                           "nonOverlappingCount": len(nonoverlap), "meanReturn": mean(returns) if returns else None,
                           "medianReturn": median(returns) if returns else None,
                           "q25": sorted(returns)[int((len(returns)-1)*.25)] if returns else None,
                           "q75": sorted(returns)[int((len(returns)-1)*.75)] if returns else None,
                           "positiveRate": sum(value > 0 for value in returns) / len(returns) if returns else None,
                           "meanMaxDrawdown": mean([mdd for _, _, mdd in samples]) if samples else None,
                           "unconditionalMeanReturn": baseline_mean,
                           "meanExcessVsUnconditional": excess,
                           "excessCi95Low": ci_low, "excessCi95High": ci_high,
                           "uncertaintyMethod": "Newey-West HAC normal approximation with lag=horizon; overlapping forward windows remain descriptive",
                           "interpretation": "描述性条件收益；信号收盘后、下一交易日收盘起算；区间重叠，非交易策略绩效"})
    return output


def _clean_series(rows):
    ordered = sorted(rows, key=lambda row: row["tradeDate"])
    dates = [row["tradeDate"] for row in ordered]
    if len(dates) != len(set(dates)):
        raise ValueError("duplicate tradeDate")
    out = []
    for row in ordered:
        value = row.get("closeValue")
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
            raise ValueError(f"invalid positive index close on {row['tradeDate']}")
        out.append((row["tradeDate"], float(value)))
    return out


def _fit(rows):
    """OLS of ln(index) on actual elapsed tropical years; sample residual SD."""
    series = _clean_series(rows)
    if len(series) < 3:
        raise ValueError("at least three observations required for residual standard deviation")
    origin = date.fromisoformat(f"{series[0][0][:4]}-{series[0][0][4:6]}-{series[0][0][6:8]}")
    xs = [(date.fromisoformat(f"{d[:4]}-{d[4:6]}-{d[6:8]}") - origin).days / 365.2425 for d, _ in series]
    ys = [log(v) for _, v in series]
    xbar, ybar = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - xbar) ** 2 for x in xs)
    if sxx == 0:
        raise ValueError("regression dates must span time")
    beta = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / sxx
    alpha = ybar - beta * xbar
    residuals = [y - (alpha + beta * x) for x, y in zip(xs, ys)]
    residual_sd = sqrt(sum(e * e for e in residuals) / (len(rows) - 2))
    return series, xs, alpha, beta, residuals, residual_sd


def dividend_regression(rows, *, mode="fixed_asof", sigma=1.5, expanding_warmup=756):
    """Return as-of full-sample fit or expanding point-in-time fits.

    Fixed-as-of values are retrospective and must never be treated as historic signals.
    Expanding values at t use only observations through t.
    """
    if mode not in {"fixed_asof", "expanding_point_in_time"} or not isfinite(sigma) or sigma <= 0:
        raise ValueError("invalid regression parameters")
    series = _clean_series(rows)
    if mode == "fixed_asof":
        fit, xs, alpha, beta, residuals, sd = _fit(rows)
        if sd == 0:
            raise ValueError("regression residual standard deviation is zero")
        result = []
        for (day, close), x, residual in zip(fit, xs, residuals):
            trend = exp(alpha + beta * x)
            result.append({"tradeDate": day, "close": close, "trend": trend,
                           "upper": trend * exp(sigma * sd), "lower": trend * exp(-sigma * sd),
                           "z": residual / sd, "mode": mode})
        return {"mode": mode, "fitStartDate": fit[0][0], "fitEndDate": fit[-1][0],
                "sampleCount": len(fit), "alpha": alpha, "beta": beta,
                "residualStd": sd, "annualizedGrowth": exp(beta) - 1,
                "sigma": sigma, "rows": result}
    result = []
    for end in range(len(series)):
        prefix = [{"tradeDate": d, "closeValue": v} for d, v in series[:end + 1]]
        if end + 1 < expanding_warmup:
            result.append({"tradeDate": series[end][0], "close": series[end][1], "trend": None,
                           "upper": None, "lower": None, "z": None, "mode": mode})
            continue
        fit, xs, alpha, beta, residuals, sd = _fit(prefix)
        if sd == 0:
            vals = (None, None, None, None)
        else:
            trend = exp(alpha + beta * xs[-1])
            vals = (trend, trend * exp(sigma * sd), trend * exp(-sigma * sd), residuals[-1] / sd)
        result.append({"tradeDate": series[end][0], "close": series[end][1], "trend": vals[0],
                       "upper": vals[1], "lower": vals[2], "z": vals[3], "mode": mode})
    return {"mode": mode, "warmup": expanding_warmup, "rows": result}


def ah_common_40(a_rows, h_rows, *, expected_common_dates=None):
    """A/H 40-interval return spread on common valid dates; no carry-forward."""
    a = dict(_clean_series(a_rows))
    h = dict(_clean_series(h_rows))
    if expected_common_dates is not None:
        calendar = list(expected_common_dates)
        if calendar != sorted(calendar) or len(calendar) != len(set(calendar)):
            raise ValueError("expected_common_dates must be sorted and unique")
        dates = calendar
    else:
        dates = sorted(set(a) & set(h))
    result = []
    for i, day in enumerate(dates):
        has_pair = day in a and day in h
        if not has_pair:
            result.append({"tradeDate": day, "aReturn40": None, "hReturn40": None, "spread40": None,
                           "ratio": a[day] / h[day] if day in a and day in h else None,
                           "quality": "MISSING_COMMON_OBSERVATION"})
            continue
        expected_slice = dates[i-40:i+1] if i >= 40 else []
        valid = i >= 40 and len(expected_slice) == 41
        if valid and expected_common_dates is not None:
            valid = all(x in a and x in h for x in expected_slice)
        if not valid:
            result.append({"tradeDate": day, "aReturn40": None, "hReturn40": None, "spread40": None,
                           "ratio": a[day] / h[day], "aClose": a[day], "hClose": h[day],
                           "quality": "INSUFFICIENT_OR_GAPPED"})
            continue
        old = dates[i-40]
        ar, hr = a[day] / a[old] - 1, h[day] / h[old] - 1
        result.append({"tradeDate": day, "aReturn40": ar, "hReturn40": hr,
                       "spread40": ar - hr, "ratio": a[day] / h[day], "aClose": a[day], "hClose": h[day],
                       "quality": "READY"})
    return result


def dividend_spread_and_percentile(dividend_yield_pct, gov10y_pct, history, *, min_samples=30):
    """Official yield minus official 10Y yield in percentage points; empirical CDF."""
    if dividend_yield_pct is None or gov10y_pct is None:
        return {"spreadPp": None, "percentile": None, "quality": "MISSING_OFFICIAL"}
    values = [v for v in history if isinstance(v, (int, float)) and not isinstance(v, bool) and isfinite(v)]
    if len(values) < min_samples:
        return {"spreadPp": dividend_yield_pct - gov10y_pct, "percentile": None,
                "sampleCount": len(values), "quality": "INSUFFICIENT_HISTORY"}
    return {"spreadPp": dividend_yield_pct - gov10y_pct,
            "percentile": 100 * sum(v <= dividend_yield_pct for v in values) / len(values),
            "sampleCount": len(values), "quality": "READY"}
