from __future__ import annotations

from datetime import datetime

from .execution_policy import (
    recommendation_primary_take_profit_price,
    recommendation_primary_take_profit_target,
    take_profit_event_type,
    take_profit_label,
)
from .models import Recommendation, SignalEvent

_TERMINAL_SIGNAL_STATUSES = {"STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2", "INVALIDATED", "EXPIRED"}


def evaluate_tracked_signal(
    recommendation: Recommendation,
    price: float,
    now: datetime,
    created_at: datetime,
    max_tracking_days: int = 10,
    lifecycle_status: str = "PENDING_ENTRY",
) -> SignalEvent | None:
    age_days = (now - created_at).days
    primary_target = recommendation_primary_take_profit_target(recommendation)
    primary_take_profit = recommendation_primary_take_profit_price(recommendation)
    primary_take_profit_event = take_profit_event_type(primary_target)
    primary_take_profit_label = take_profit_label(primary_target)
    max_chase_price = _max_chase_price(recommendation)

    if lifecycle_status in _TERMINAL_SIGNAL_STATUSES:
        return None
    if age_days >= max_tracking_days:
        return SignalEvent(
            recommendation_id=recommendation.id,
            symbol=recommendation.symbol,
            event_type="EXPIRED",
            price=price,
            timestamp=now,
            message=f"{recommendation.symbol} 跟踪超过 {max_tracking_days} 天，信号超期。",
        )
    if lifecycle_status == "ENTRY_TRIGGERED":
        if price <= recommendation.stop_loss:
            return SignalEvent(
                recommendation_id=recommendation.id,
                symbol=recommendation.symbol,
                event_type="STOP_LOSS",
                price=price,
                timestamp=now,
                message=f"{recommendation.symbol} 触及止损价 {recommendation.stop_loss:.2f}。",
            )
        if price >= primary_take_profit:
            return SignalEvent(
                recommendation_id=recommendation.id,
                symbol=recommendation.symbol,
                event_type=primary_take_profit_event,
                price=price,
                timestamp=now,
                message=f"{recommendation.symbol} 触及回测主止盈 {primary_take_profit_label} {primary_take_profit:.2f}。",
            )
    if recommendation.entry_price_high <= price <= max_chase_price:
        return SignalEvent(
            recommendation_id=recommendation.id,
            symbol=recommendation.symbol,
            event_type="ENTRY_TRIGGERED",
            price=price,
            timestamp=now,
            message=(
                f"{recommendation.symbol} 突破触发价并进入允许追价区间，"
                f"触发价 {recommendation.entry_price_high:.2f}，追价上限 {max_chase_price:.2f}。"
            ),
        )
    if price <= recommendation.invalidation_price:
        return SignalEvent(
            recommendation_id=recommendation.id,
            symbol=recommendation.symbol,
            event_type="INVALIDATED",
            price=price,
            timestamp=now,
            message=f"{recommendation.symbol} 跌破失效价 {recommendation.invalidation_price:.2f}。",
        )
    return SignalEvent(
        recommendation_id=recommendation.id,
        symbol=recommendation.symbol,
        event_type="HOLD",
        price=price,
        timestamp=now,
        message=f"{recommendation.symbol} 信号继续跟踪。",
    )


def _max_chase_price(recommendation: Recommendation) -> float:
    if recommendation.max_chase_price and recommendation.max_chase_price >= recommendation.entry_price_high:
        return recommendation.max_chase_price
    return recommendation.entry_price_high
