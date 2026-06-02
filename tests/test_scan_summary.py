from us_stock_signal import cli
from us_stock_signal.notifiers.dingtalk import format_markdown_message


def test_score_gate_for_session_uses_watchlist_threshold():
    settings = type(
        "Settings",
        (),
        {"scoring": {"min_score": 90, "watchlist_min_score": 88, "top_n": 10}},
    )()

    assert cli._score_gate_for_session(settings, "afterhours") == 88
    assert cli._score_gate_for_session(settings, "premarket") == 88
    assert cli._score_gate_for_session(settings, "regular") == 90


def test_score_gate_for_session_uses_high_yield_threshold():
    settings = type(
        "Settings",
        (),
        {
            "scoring": {
                "trigger_mode": "high_yield_breakout",
                "min_score": 90,
                "watchlist_min_score": 90,
                "high_yield": {"min_score": 80, "watchlist_min_score": 81},
            }
        },
    )()

    assert cli._score_gate_for_session(settings, "afterhours") == 81
    assert cli._score_gate_for_session(settings, "regular") == 80


def test_validation_top_n_defaults_to_high_yield_config():
    settings = type(
        "Settings",
        (),
        {"scoring": {"trigger_mode": "high_yield_breakout", "top_n": 5, "high_yield": {"top_n": 1}}},
    )()

    assert cli._validation_top_n(settings, None) == 1
    assert cli._validation_top_n(settings, 3) == 3


def test_configured_max_holding_days_defaults_to_pricing_config():
    settings = type("Settings", (), {"pricing": {"max_tracking_trading_days": 3}})()

    assert cli._configured_max_holding_days(settings, None) == 3
    assert cli._configured_max_holding_days(settings, 7) == 7


def test_markdown_summary_shows_gate_and_top_limit():
    message = format_markdown_message(
        [],
        session="afterhours",
        scan_summary={"scanned_count": 30, "candidate_count": 0, "min_score": 90, "top_n": 10},
    )

    assert "入选门槛：综合分 >= 90" in message.text
    assert "最多推送 Top10" in message.text


def test_markdown_summary_labels_high_yield_breakout_mode():
    message = format_markdown_message(
        [],
        session="afterhours",
        scan_summary={
            "scanned_count": 30,
            "candidate_count": 0,
            "min_score": 80,
            "top_n": 2,
            "trigger_mode": "high_yield_breakout",
            "primary_take_profit": "tp2",
        },
    )

    assert message.title == "美股短线高收益突破预备观察"
    assert "触发模式：高收益突破；验证主目标：TP2" in message.text
    assert "最多推送 Top2" in message.text
