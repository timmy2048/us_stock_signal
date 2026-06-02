from datetime import datetime, timedelta, timezone

from us_stock_signal.models import Recommendation
from us_stock_signal.tracker import evaluate_tracked_signal


def _rec() -> Recommendation:
    return Recommendation(
        id="r1",
        symbol="XYZ",
        rank=1,
        score=88,
        session="regular",
        current_price=10,
        entry_price_low=10,
        entry_price_high=10.2,
        max_chase_price=10.25,
        stop_loss=9.5,
        take_profit_1=10.9,
        take_profit_2=11.5,
        expiry="2 个交易日",
        invalidation_price=9.9,
        reasons=[],
        risk_flags=[],
        data_quality="test",
        ai_status="available",
    )


def test_tracker_reports_entry_stop_take_profit_and_expiry():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rec = _rec()

    assert evaluate_tracked_signal(rec, price=10.1, now=now, created_at=now).event_type == "HOLD"
    assert evaluate_tracked_signal(rec, price=10.22, now=now, created_at=now).event_type == "ENTRY_TRIGGERED"
    assert evaluate_tracked_signal(rec, price=9.4, now=now, created_at=now).event_type == "INVALIDATED"
    assert evaluate_tracked_signal(rec, price=11.0, now=now, created_at=now).event_type == "HOLD"
    assert (
        evaluate_tracked_signal(rec, price=10.0, now=now + timedelta(days=12), created_at=now).event_type
        == "EXPIRED"
    )


def test_tracker_waits_for_primary_take_profit_when_backtest_target_is_tp2():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rec = _rec()
    rec.primary_take_profit = "tp2"

    assert evaluate_tracked_signal(rec, price=11.0, now=now, created_at=now, lifecycle_status="ENTRY_TRIGGERED").event_type == "HOLD"
    assert (
        evaluate_tracked_signal(rec, price=11.5, now=now, created_at=now, lifecycle_status="ENTRY_TRIGGERED").event_type
        == "TAKE_PROFIT_2"
    )


def test_tracker_exits_at_tp1_even_if_price_runs_past_tp2_when_tp1_is_primary():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rec = _rec()
    rec.primary_take_profit = "tp1"

    assert (
        evaluate_tracked_signal(rec, price=11.6, now=now, created_at=now, lifecycle_status="ENTRY_TRIGGERED").event_type
        == "TAKE_PROFIT_1"
    )


def test_tracker_does_not_stop_or_take_profit_before_entry_trigger():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rec = _rec()

    assert evaluate_tracked_signal(rec, price=11.6, now=now, created_at=now).event_type == "HOLD"
    assert evaluate_tracked_signal(rec, price=9.4, now=now, created_at=now).event_type == "INVALIDATED"
