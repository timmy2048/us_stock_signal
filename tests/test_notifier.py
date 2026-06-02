from us_stock_signal.models import Recommendation
from us_stock_signal.notifiers.dingtalk import build_signed_url, format_markdown_message


def test_dingtalk_signed_url_uses_timestamp_and_secret():
    url = build_signed_url(
        webhook="https://oapi.dingtalk.com/robot/send?access_token=abc",
        secret="secret",
        timestamp_ms=1700000000000,
    )

    assert "timestamp=1700000000000" in url
    assert "sign=" in url
    assert "secret" not in url


def test_markdown_message_highlights_top1_and_lists_top10():
    rec = Recommendation(
        id="scan-1-XYZ",
        symbol="XYZ",
        rank=1,
        score=88.5,
        session="regular",
        current_price=10.0,
        entry_price_low=10.0,
        entry_price_high=10.2,
        max_chase_price=10.25,
        stop_loss=9.5,
        take_profit_1=10.9,
        take_profit_2=11.5,
        expiry="2 个交易日",
        invalidation_price=9.9,
        reasons=["放量突破", "相对强势"],
        risk_flags=["高波动"],
        data_quality="free_delayed",
        ai_status="available",
    )

    message = format_markdown_message([rec])

    assert "Top10" in message.title
    assert "Top1" in message.text
    assert "XYZ" in message.text
    assert "9.50" in message.text


def test_markdown_message_uses_backtest_primary_take_profit_in_push_text():
    rec = Recommendation(
        id="scan-1-XYZ",
        symbol="XYZ",
        rank=1,
        score=88.5,
        session="regular",
        current_price=10.0,
        entry_price_low=10.0,
        entry_price_high=10.2,
        max_chase_price=10.25,
        stop_loss=9.5,
        take_profit_1=10.9,
        take_profit_2=11.5,
        expiry="2 个交易日",
        invalidation_price=9.9,
        reasons=["放量突破"],
        risk_flags=[],
        data_quality="free_delayed",
        ai_status="available",
    )

    message = format_markdown_message(
        [rec],
        scan_summary={"trigger_mode": "high_yield_breakout", "primary_take_profit": "tp2"},
    )

    assert "10.20" in message.text
    assert "10.25" in message.text
    assert "TP2 11.50" in message.text
    assert "TP1 10.90" in message.text


def test_markdown_message_labels_watchlist_as_non_trading_preparation():
    rec = Recommendation(
        id="scan-1-XYZ",
        symbol="XYZ",
        rank=1,
        score=88.5,
        session="afterhours",
        current_price=10.0,
        entry_price_low=10.0,
        entry_price_high=10.2,
        max_chase_price=10.25,
        stop_loss=9.5,
        take_profit_1=10.9,
        take_profit_2=11.5,
        expiry="2 个交易日",
        invalidation_price=9.9,
        reasons=["日线强势"],
        risk_flags=[],
        data_quality="free_yfinance",
        ai_status="available",
        signal_status="WATCHLIST",
    )

    message = format_markdown_message([rec])

    assert "Top10" in message.title
    assert "等待开盘确认" in message.text


def test_empty_afterhours_message_is_watchlist_not_actionable_recommendation():
    message = format_markdown_message([], session="afterhours", scan_summary={"scanned_count": 30})

    assert "Top10" in message.title
    assert "0" in message.text
    assert "30" in message.text
