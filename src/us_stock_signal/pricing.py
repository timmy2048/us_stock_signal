from __future__ import annotations

from .models import TradePlan


def _round_price(value: float) -> float:
    if value >= 1:
        return round(value, 2)
    return round(value, 4)


def build_trade_plan(
    current_price: float,
    recent_high_15m: float,
    atr14: float,
    config: dict,
) -> TradePlan:
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    if recent_high_15m <= 0:
        raise ValueError("recent_high_15m must be positive")
    if atr14 <= 0:
        raise ValueError("atr14 must be positive")

    stop_multiple = float(config.get("stop_atr_multiple", 1.2))
    tp1_multiple = float(config.get("take_profit_1_atr_multiple", 1.8))
    tp2_multiple = float(config.get("take_profit_2_atr_multiple", 3.0))
    min_stop_pct = float(config.get("min_stop_pct", 0.03))
    max_stop_pct = float(config.get("max_stop_pct", 0.08))
    buffer_pct = float(config.get("entry_buffer_pct", 0.002))
    max_chase_pct = max(0.0, float(config.get("max_chase_pct", 0.0)))
    expiry_days = int(config.get("pending_signal_expiry_trading_days", 2))

    entry_low = current_price
    entry_high = max(current_price, recent_high_15m * (1 + buffer_pct))
    max_chase_price = max(entry_high, entry_high * (1 + max_chase_pct))
    planned_entry = entry_high
    raw_stop_distance = atr14 * stop_multiple
    min_stop_distance = planned_entry * min_stop_pct
    max_stop_distance = planned_entry * max_stop_pct
    stop_distance = min(max(raw_stop_distance, min_stop_distance), max_stop_distance)

    return TradePlan(
        entry_price_low=_round_price(entry_low),
        entry_price_high=_round_price(entry_high),
        max_chase_price=_round_price(max_chase_price),
        stop_loss=_round_price(planned_entry - stop_distance),
        take_profit_1=_round_price(planned_entry + atr14 * tp1_multiple),
        take_profit_2=_round_price(planned_entry + atr14 * tp2_multiple),
        invalidation_price=_round_price(current_price * 0.99),
        expiry=f"{expiry_days} 个交易日内未触发入场则失效",
    )
