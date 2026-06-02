from __future__ import annotations

from datetime import datetime

from .models import Recommendation, SignalEvent


def evaluate_tracked_signal(
    recommendation: Recommendation,
    price: float,
    now: datetime,
    created_at: datetime,
    max_tracking_days: int = 10,
) -> SignalEvent:
    age_days = (now - created_at).days
    if age_days >= max_tracking_days:
        return SignalEvent(
            recommendation_id=recommendation.id,
            symbol=recommendation.symbol,
            event_type="EXPIRED",
            price=price,
            timestamp=now,
            message=f"{recommendation.symbol} 跟踪超过 {max_tracking_days} 天，信号超期。",
        )
    if price <= recommendation.stop_loss:
        return SignalEvent(
            recommendation_id=recommendation.id,
            symbol=recommendation.symbol,
            event_type="STOP_LOSS",
            price=price,
            timestamp=now,
            message=f"{recommendation.symbol} 触及止损价 {recommendation.stop_loss:.2f}。",
        )
    if price >= recommendation.take_profit_2:
        return SignalEvent(
            recommendation_id=recommendation.id,
            symbol=recommendation.symbol,
            event_type="TAKE_PROFIT_2",
            price=price,
            timestamp=now,
            message=f"{recommendation.symbol} 触及第二止盈价 {recommendation.take_profit_2:.2f}。",
        )
    if price >= recommendation.take_profit_1:
        return SignalEvent(
            recommendation_id=recommendation.id,
            symbol=recommendation.symbol,
            event_type="TAKE_PROFIT_1",
            price=price,
            timestamp=now,
            message=f"{recommendation.symbol} 触及第一止盈价 {recommendation.take_profit_1:.2f}。",
        )
    if recommendation.entry_price_low <= price <= recommendation.entry_price_high:
        return SignalEvent(
            recommendation_id=recommendation.id,
            symbol=recommendation.symbol,
            event_type="ENTRY_TRIGGERED",
            price=price,
            timestamp=now,
            message=f"{recommendation.symbol} 进入建议入场区间。",
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

