from datetime import datetime
from zoneinfo import ZoneInfo

from us_stock_signal.sync_guard import daily_sync_window_decision


NY = ZoneInfo("America/New_York")


def test_daily_sync_guard_blocks_before_market_close():
    decision = daily_sync_window_decision({}, now=datetime(2026, 6, 1, 15, 0, tzinfo=NY))

    assert decision.allowed is False
    assert decision.window == "blocked"
    assert "20:30" in decision.message


def test_daily_sync_guard_blocks_immediately_after_close_before_data_settles():
    decision = daily_sync_window_decision({}, now=datetime(2026, 6, 1, 17, 0, tzinfo=NY))

    assert decision.allowed is False
    assert "current market time is 2026-06-01 17:00" in decision.message


def test_daily_sync_guard_allows_after_close_settlement_window():
    decision = daily_sync_window_decision({}, now=datetime(2026, 6, 1, 20, 30, tzinfo=NY))

    assert decision.allowed is True
    assert decision.window == "after_close"


def test_daily_sync_guard_allows_premarket_retry_window():
    decision = daily_sync_window_decision({}, now=datetime(2026, 6, 2, 8, 0, tzinfo=NY))

    assert decision.allowed is True
    assert decision.window == "premarket_retry"


def test_daily_sync_guard_blocks_late_premarket_to_avoid_incomplete_current_day():
    decision = daily_sync_window_decision({}, now=datetime(2026, 6, 2, 9, 25, tzinfo=NY))

    assert decision.allowed is False


def test_daily_sync_guard_can_be_forced_for_manual_repair():
    decision = daily_sync_window_decision({}, now=datetime(2026, 6, 2, 9, 25, tzinfo=NY), force=True)

    assert decision.allowed is True
    assert decision.window == "forced"
