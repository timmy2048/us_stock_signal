import us_stock_signal.strategy_search as strategy_search
from us_stock_signal.strategy_search import (
    HighYieldStrategyVariant,
    build_high_yield_variant_config,
    default_high_yield_variants,
    rank_strategy_search_results,
)


def test_build_high_yield_variant_config_overrides_strategy_without_mutating_base():
    base_config = {
        "universe": {"min_price": 2},
        "scoring": {
            "rule_weight": 0.6,
            "ml_weight": 0.25,
            "ai_weight": 0.15,
            "high_yield": {"min_score": 80, "top_n": 2},
        },
        "pricing": {"take_profit_2_atr_multiple": 3.0},
        "backtest": {},
    }
    variant = HighYieldStrategyVariant(
        name="ultra",
        candidate_pool_limit=100,
        top_n=5,
        min_score=70,
        min_atr_pct=5,
        max_atr_pct=999,
        min_distance_to_20d_high_pct=-999,
        min_distance_to_60d_high_pct=-5,
        min_momentum_20_pct=60,
        min_momentum_5_pct=15,
        min_volume_ratio=2,
        max_gap_pct=80,
        max_price=100,
        take_profit_2_atr_multiple=6,
        stop_atr_multiple=1.8,
        min_stop_pct=0.015,
        max_stop_pct=0.12,
        entry_buffer_pct=0.001,
        pending_entry_days=4,
        max_holding_days=5,
    )

    config = build_high_yield_variant_config(base_config, variant)

    assert config["scoring"]["trigger_mode"] == "high_yield_breakout"
    assert config["scoring"]["top_n"] == 5
    assert config["scoring"]["min_score"] == 70
    assert config["scoring"]["watchlist_min_score"] == 70
    assert config["scoring"]["high_yield"]["min_score"] == 70
    assert config["scoring"]["high_yield"]["watchlist_min_score"] == 70
    assert config["scoring"]["high_yield"]["candidate_pool_limit"] == 100
    assert config["scoring"]["high_yield"]["min_distance_to_60d_high_pct"] == -5
    assert config["scoring"]["high_yield"]["min_momentum_20_pct"] == 60
    assert config["scoring"]["high_yield"]["min_momentum_5_pct"] == 15
    assert config["scoring"]["high_yield"]["min_volume_ratio"] == 2
    assert config["scoring"]["high_yield"]["max_gap_pct"] == 80
    assert config["scoring"]["high_yield"]["max_price"] == 100
    assert config["pricing"]["take_profit_2_atr_multiple"] == 6
    assert config["pricing"]["stop_atr_multiple"] == 1.8
    assert config["pricing"]["min_stop_pct"] == 0.015
    assert config["pricing"]["max_stop_pct"] == 0.12
    assert config["pricing"]["entry_buffer_pct"] == 0.001
    assert config["pricing"]["pending_signal_expiry_trading_days"] == 4
    assert config["pricing"]["max_tracking_trading_days"] == 5
    assert base_config["scoring"]["high_yield"]["top_n"] == 2
    assert base_config["pricing"]["take_profit_2_atr_multiple"] == 3.0
    assert "entry_buffer_pct" not in base_config["pricing"]


def test_rank_strategy_search_results_filters_low_sample_and_sorts_by_objective():
    results = [
        {
            "variant": {"name": "thin"},
            "summary": {"signal_count": 4, "avg_return_pct_all_signals": 20, "avg_return_pct": 22, "profit_factor": 3},
        },
        {
            "variant": {"name": "steady"},
            "summary": {"signal_count": 35, "avg_return_pct_all_signals": 4, "avg_return_pct": 5, "profit_factor": 2.5},
        },
        {
            "variant": {"name": "faster"},
            "summary": {"signal_count": 50, "avg_return_pct_all_signals": 6, "avg_return_pct": 4, "profit_factor": 1.8},
        },
    ]

    ranked = rank_strategy_search_results(results, objective="avg_all", min_signal_count=30, limit=2)

    assert [item["variant"]["name"] for item in ranked] == ["faster", "steady"]


def test_rank_strategy_search_results_can_sort_by_single_position_compound_return():
    results = [
        {
            "variant": {"name": "high_average"},
            "summary": {
                "signal_count": 40,
                "avg_return_pct_all_signals": 8,
                "single_position_total_return_pct": 12,
                "profit_factor": 2,
            },
        },
        {
            "variant": {"name": "better_compound"},
            "summary": {
                "signal_count": 40,
                "avg_return_pct_all_signals": 5,
                "single_position_total_return_pct": 35,
                "profit_factor": 1.8,
            },
        },
    ]

    ranked = rank_strategy_search_results(results, objective="compound", min_signal_count=30, limit=2)

    assert [item["variant"]["name"] for item in ranked] == ["better_compound", "high_average"]


def test_strategy_search_uses_variant_holding_periods(monkeypatch):
    variants = [
        HighYieldStrategyVariant("hold3", 100, 1, 80, 5, 999, -999, 6, max_holding_days=3),
        HighYieldStrategyVariant("hold7", 100, 1, 80, 5, 999, -999, 6, max_holding_days=7),
    ]
    observed = {"prepared_max": None, "validated_max": []}

    def fake_prepare(daily_bars, lookback_days, sample_days, max_holding_days):
        observed["prepared_max"] = max_holding_days
        return type("Prepared", (), {"eval_dates": [1], "reason": ""})()

    def fake_validate(prepared, config, top_n, max_holding_days):
        observed["validated_max"].append(max_holding_days)
        return {"summary": {"signal_count": 30, "single_position_total_return_pct": max_holding_days}, "rank_metrics": []}

    monkeypatch.setattr(strategy_search, "prepare_validation_data", fake_prepare)
    monkeypatch.setattr(strategy_search, "validate_prepared_signal_days", fake_validate)

    report = strategy_search.search_high_yield_strategies_from_daily_bars(
        daily_bars=object(),
        base_config={"scoring": {}, "pricing": {}, "backtest": {"validation_future_days": 10}},
        lookback_days=365,
        sample_days=40,
        max_holding_days=3,
        variants=variants,
        objective="compound",
    )

    assert observed["prepared_max"] == 10
    assert observed["validated_max"] == [3, 7]
    assert report["results"][0]["variant"]["name"] == "hold7"


def test_default_high_yield_variants_include_current_tuned_extreme_profile():
    variants = default_high_yield_variants()

    assert any(
        variant.top_n == 2
        and variant.take_profit_2_atr_multiple == 7
        and variant.min_momentum_20_pct == 120
        and variant.min_momentum_5_pct == 80
        and variant.max_gap_pct == 80
        and variant.max_price == 100
        and variant.min_stop_pct == 0.02
        and variant.max_stop_pct == 0.02
        and variant.entry_buffer_pct == 0
        and variant.pending_entry_days == 1
        and variant.max_holding_days == 3
        for variant in variants
    )
