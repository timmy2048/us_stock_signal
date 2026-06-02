from __future__ import annotations

import math


def average_true_range(highs, lows, closes, period: int = 14) -> float:
    if len(closes) < 2:
        return 0.0
    true_ranges: list[float] = []
    for idx in range(1, len(closes)):
        high = float(highs[idx])
        low = float(lows[idx])
        prev_close = float(closes[idx - 1])
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    window = true_ranges[-period:] if len(true_ranges) >= period else true_ranges
    return sum(window) / len(window) if window else 0.0


def technical_snapshot_features(closes, highs, volumes, current_price: float, opens=None, lows=None) -> dict[str, float]:
    close_values = [float(v) for v in closes if not math.isnan(float(v))]
    high_values = [float(v) for v in highs if not math.isnan(float(v))]
    volume_values = [float(v) for v in volumes if not math.isnan(float(v))]
    if len(close_values) < 25 or len(volume_values) < 20:
        return {}
    last = float(current_price)
    close_5 = close_values[-6]
    close_20 = close_values[-21]
    vol20 = sum(volume_values[-20:]) / 20
    high20 = max(high_values[-20:]) if len(high_values) >= 20 else max(close_values[-20:])
    high60_window = high_values[-60:] if len(high_values) >= 60 else high_values
    high60 = max(high60_window) if high60_window else high20
    features = {
        "momentum_5_pct": (last / close_5 - 1) * 100 if close_5 else 0.0,
        "momentum_20_pct": (last / close_20 - 1) * 100 if close_20 else 0.0,
        "volume_ratio": volume_values[-1] / vol20 if vol20 else 1.0,
        "distance_to_20d_high_pct": (last / high20 - 1) * 100 if high20 else 0.0,
        "distance_to_60d_high_pct": (last / high60 - 1) * 100 if high60 else 0.0,
    }
    features.update(_price_action_features(opens, highs, lows, closes))
    return features


def _price_action_features(opens, highs, lows, closes) -> dict[str, float]:
    if opens is None or lows is None:
        return {}
    if len(opens) < 1 or len(highs) < 1 or len(lows) < 1 or len(closes) < 2:
        return {}
    last_open = _float_or_none(opens[-1])
    last_high = _float_or_none(highs[-1])
    last_low = _float_or_none(lows[-1])
    last_close = _float_or_none(closes[-1])
    prev_close = _float_or_none(closes[-2])
    if None in {last_open, last_high, last_low, last_close, prev_close}:
        return {}
    if last_open <= 0 or last_low <= 0 or last_close <= 0 or prev_close <= 0:
        return {}
    day_range = max(last_high - last_low, 0.0)
    close_position = ((last_close - last_low) / day_range * 100) if day_range > 0 else 50.0
    return {
        "gap_pct": (last_open / prev_close - 1) * 100,
        "intraday_pct": (last_close / last_open - 1) * 100,
        "close_position_pct": close_position,
        "upper_wick_pct": max((last_high / last_close - 1) * 100, 0.0),
        "lower_wick_pct": max((last_close / last_low - 1) * 100, 0.0),
        "day_range_pct": day_range / last_close * 100,
    }


def _float_or_none(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def score_technical_snapshot(closes, volumes, current_price: float) -> tuple[float, list[str], list[str]]:
    reasons: list[str] = []
    risks: list[str] = []
    if len(closes) < 25:
        return 50.0, ["历史数据不足，按中性处理"], ["样本不足"]

    close_values = [float(v) for v in closes if not math.isnan(float(v))]
    volume_values = [float(v) for v in volumes if not math.isnan(float(v))]
    if len(close_values) < 25 or len(volume_values) < 20:
        return 50.0, ["历史数据不足，按中性处理"], ["样本不足"]

    last = current_price
    close_5 = close_values[-6]
    close_20 = close_values[-21]
    ma20 = sum(close_values[-20:]) / 20
    ma50 = sum(close_values[-50:]) / min(50, len(close_values))
    vol20 = sum(volume_values[-20:]) / 20
    vol_last = volume_values[-1]

    score = 50.0
    momentum_5 = (last / close_5 - 1) * 100
    momentum_20 = (last / close_20 - 1) * 100
    score += max(-12, min(15, momentum_5 * 1.0))
    score += max(-12, min(16, momentum_20 * 0.55))
    if last > ma20:
        score += 5
        reasons.append("价格站上 20 日均线")
    else:
        score -= 7
        risks.append("价格低于 20 日均线")
    if last > ma50:
        score += 4
        reasons.append("中期趋势向上")
    else:
        score -= 5
    volume_ratio = vol_last / vol20 if vol20 > 0 else 1.0
    score += max(-4, min(8, (volume_ratio - 1.0) * 4.5))
    if volume_ratio >= 1.5:
        reasons.append("成交量明显放大")
    if momentum_5 > 18:
        score -= min(8, (momentum_5 - 18) * 0.35)
    if momentum_5 > 3:
        reasons.append("5 日动量强")
    if momentum_20 > 8:
        reasons.append("20 日相对强势")
    if abs(momentum_5) > 12:
        risks.append("短线波动过大")
    return round(max(0, min(100, score)), 2), reasons[:5], risks[:5]
