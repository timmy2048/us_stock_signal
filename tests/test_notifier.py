from us_stock_signal.notifiers.dingtalk import build_signed_url, format_markdown_message
from us_stock_signal.models import Recommendation


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

    assert "美股短线 Top10" in message.title
    assert "Top1 重点信号" in message.text
    assert "XYZ" in message.text
    assert "止损价" in message.text


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

    assert "美股短线 Top10 预备观察名单" in message.title
    assert "非交易时段" in message.text
    assert "等待开盘确认" in message.text


def test_empty_afterhours_message_is_watchlist_not_actionable_recommendation():
    message = format_markdown_message([], session="afterhours", scan_summary={"scanned_count": 30})

    assert message.title == "美股短线 Top10 预备观察名单"
    assert "非交易时段" in message.text
    assert "本次入选候选：0 个" in message.text
    assert "本次扫描范围：30 个" in message.text
