from us_stock_signal.pricing import build_trade_plan


def test_trade_plan_has_explicit_entry_stop_targets_and_expiry():
    plan = build_trade_plan(
        current_price=10.0,
        recent_high_15m=10.2,
        atr14=0.5,
        config={
            "stop_atr_multiple": 1.2,
            "take_profit_1_atr_multiple": 1.8,
            "take_profit_2_atr_multiple": 3.0,
            "min_stop_pct": 0.03,
            "max_stop_pct": 0.08,
            "entry_buffer_pct": 0.002,
            "max_chase_pct": 0.005,
            "pending_signal_expiry_trading_days": 2,
        },
    )

    assert plan.entry_price_low == 10.0
    assert plan.entry_price_high == 10.22
    assert plan.max_chase_price == 10.27
    assert plan.stop_loss == 9.62
    assert plan.take_profit_1 == 11.12
    assert plan.take_profit_2 == 11.72
    assert "2 个交易日" in plan.expiry
    assert plan.invalidation_price == 9.9


def test_stop_loss_is_capped_to_max_stop_pct_for_very_large_atr():
    plan = build_trade_plan(
        current_price=20.0,
        recent_high_15m=20.2,
        atr14=5.0,
        config={
            "stop_atr_multiple": 1.2,
            "take_profit_1_atr_multiple": 1.8,
            "take_profit_2_atr_multiple": 3.0,
            "min_stop_pct": 0.03,
            "max_stop_pct": 0.08,
            "entry_buffer_pct": 0.002,
            "max_chase_pct": 0.005,
            "pending_signal_expiry_trading_days": 2,
        },
    )

    assert plan.stop_loss == 18.62


def test_stop_loss_risk_is_capped_from_planned_entry_price():
    plan = build_trade_plan(
        current_price=10.0,
        recent_high_15m=12.0,
        atr14=5.0,
        config={
            "stop_atr_multiple": 1.2,
            "take_profit_1_atr_multiple": 1.8,
            "take_profit_2_atr_multiple": 3.0,
            "min_stop_pct": 0.03,
            "max_stop_pct": 0.08,
            "entry_buffer_pct": 0.002,
            "max_chase_pct": 0.005,
            "pending_signal_expiry_trading_days": 2,
        },
    )

    risk_pct = (plan.entry_price_high - plan.stop_loss) / plan.entry_price_high

    assert plan.entry_price_high == 12.02
    assert plan.max_chase_price == 12.08
    assert round(risk_pct, 4) <= 0.0801
