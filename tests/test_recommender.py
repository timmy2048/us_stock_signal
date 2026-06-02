from us_stock_signal.models import MarketSnapshot, NewsBundle
from us_stock_signal.recommender import RecommendationEngine


def _pricing_config(take_profit_2_atr_multiple: float = 3.0) -> dict:
    return {
        "stop_atr_multiple": 1.2,
        "take_profit_1_atr_multiple": 1.8,
        "take_profit_2_atr_multiple": take_profit_2_atr_multiple,
        "min_stop_pct": 0.03,
        "max_stop_pct": 0.08,
        "entry_buffer_pct": 0.002,
        "max_chase_pct": 0.005,
        "pending_signal_expiry_trading_days": 2,
    }


def test_hard_filter_blocks_low_liquidity_even_with_high_ai_and_ml_scores():
    engine = RecommendationEngine(
        config={
            "universe": {"min_price": 2.0, "min_avg_dollar_volume_20d": 10000000},
            "scoring": {"rule_weight": 0.6, "ml_weight": 0.25, "ai_weight": 0.15, "min_score": 60, "top_n": 10},
            "pricing": _pricing_config(),
        }
    )
    snapshots = [
        MarketSnapshot(
            symbol="BAD",
            current_price=8.0,
            recent_high_15m=8.1,
            atr14=0.4,
            avg_dollar_volume_20d=100000,
            rule_score=95,
            ml_score=95,
            ai_score=95,
            reasons=["strong looking"],
            risk_flags=[],
            data_quality="test",
        )
    ]

    assert engine.recommend(snapshots, {"BAD": NewsBundle(symbol="BAD", headlines=[])}, "regular") == []


def test_recommendation_engine_ranks_top10_and_keeps_price_levels():
    engine = RecommendationEngine.default_for_tests()
    snapshots = [
        MarketSnapshot(
            symbol=f"S{i}",
            current_price=10.0 + i,
            recent_high_15m=10.2 + i,
            atr14=0.5,
            avg_dollar_volume_20d=20000000,
            rule_score=60 + i,
            ml_score=55 + i,
            ai_score=50 + i,
            reasons=["trend up"],
            risk_flags=[],
            data_quality="test",
        )
        for i in range(12)
    ]

    recs = engine.recommend(snapshots, {}, "regular")

    assert len(recs) == 10
    assert recs[0].symbol == "S11"
    assert recs[0].rank == 1
    assert recs[0].stop_loss < recs[0].entry_price_low
    assert recs[0].take_profit_1 > recs[0].entry_price_high


def test_recommendation_engine_limit_can_return_candidate_pool_beyond_top_n():
    engine = RecommendationEngine.default_for_tests()
    snapshots = [
        MarketSnapshot(
            symbol=f"S{i}",
            current_price=10.0 + i,
            recent_high_15m=10.2 + i,
            atr14=0.5,
            avg_dollar_volume_20d=20000000,
            rule_score=60 + i,
            ml_score=55 + i,
            ai_score=50 + i,
            reasons=["trend up"],
            risk_flags=[],
            data_quality="test",
        )
        for i in range(12)
    ]

    recs = engine.recommend(snapshots, {}, "regular", limit=12)

    assert len(recs) == 12
    assert recs[0].rank == 1
    assert recs[-1].rank == 12


def test_recommendation_engine_marks_afterhours_as_watchlist_and_regular_as_actionable():
    engine = RecommendationEngine.default_for_tests()
    snapshot = MarketSnapshot(
        symbol="XYZ",
        current_price=20.0,
        recent_high_15m=20.3,
        atr14=0.8,
        avg_dollar_volume_20d=30000000,
        rule_score=85,
        ml_score=80,
        ai_score=70,
        reasons=["trend up"],
        risk_flags=[],
        data_quality="test",
    )

    watchlist = engine.recommend([snapshot], {}, "afterhours")
    actionable = engine.recommend([snapshot], {}, "regular")

    assert watchlist[0].signal_status == "WATCHLIST"
    assert actionable[0].signal_status == "ACTIONABLE"


def test_recommendation_engine_persists_primary_take_profit_for_execution_alignment():
    engine = RecommendationEngine(
        config={
            "universe": {"min_price": 2.0, "min_avg_dollar_volume_20d": 10000000},
            "scoring": {
                "rule_weight": 0.6,
                "ml_weight": 0.25,
                "ai_weight": 0.15,
                "trigger_mode": "high_yield_breakout",
                "high_yield": {
                    "min_score": 70,
                    "candidate_pool_limit": 5,
                    "top_n": 1,
                    "min_atr_pct": 5,
                    "max_atr_pct": 999,
                    "min_distance_to_20d_high_pct": -999,
                    "primary_take_profit": "tp2",
                },
            },
            "pricing": _pricing_config(take_profit_2_atr_multiple=7.0),
        }
    )
    snapshot = MarketSnapshot(
        symbol="XYZ",
        current_price=20.0,
        recent_high_15m=20.0,
        atr14=1.2,
        avg_dollar_volume_20d=30000000,
        rule_score=95,
        ml_score=90,
        ai_score=50,
        reasons=["trend up"],
        risk_flags=[],
        data_quality="test",
        extra={"atr_pct": 6, "distance_to_20d_high_pct": -20},
    )

    recs = engine.recommend([snapshot], {}, "regular")

    assert recs[0].primary_take_profit == "tp2"


def test_recommendation_engine_uses_secondary_sort_when_scores_tie():
    engine = RecommendationEngine.default_for_tests()
    snapshots = [
        MarketSnapshot(
            symbol="LOWVOL",
            current_price=20.0,
            recent_high_15m=20.3,
            atr14=0.8,
            avg_dollar_volume_20d=20000000,
            rule_score=90,
            ml_score=90,
            ai_score=50,
            reasons=["same score"],
            risk_flags=[],
            data_quality="test",
        ),
        MarketSnapshot(
            symbol="HIGHVOL",
            current_price=20.0,
            recent_high_15m=20.3,
            atr14=0.8,
            avg_dollar_volume_20d=90000000,
            rule_score=90,
            ml_score=90,
            ai_score=50,
            reasons=["same score"],
            risk_flags=[],
            data_quality="test",
        ),
    ]

    recs = engine.recommend(snapshots, {}, "afterhours")

    assert [rec.symbol for rec in recs] == ["HIGHVOL", "LOWVOL"]


def test_high_yield_breakout_mode_filters_after_candidate_pool_ranking():
    engine = RecommendationEngine(
        config={
            "universe": {"min_price": 2.0, "min_avg_dollar_volume_20d": 10000000},
            "scoring": {
                "rule_weight": 0.6,
                "ml_weight": 0.25,
                "ai_weight": 0.15,
                "trigger_mode": "high_yield_breakout",
                "high_yield": {
                    "min_score": 70,
                    "candidate_pool_limit": 3,
                    "top_n": 2,
                    "min_atr_pct": 3,
                    "max_atr_pct": 10,
                    "min_distance_to_20d_high_pct": -1,
                },
            },
            "pricing": _pricing_config(),
        }
    )
    snapshots = [
        MarketSnapshot(
            symbol="OVEREXT",
            current_price=20,
            recent_high_15m=20,
            atr14=1,
            avg_dollar_volume_20d=30000000,
            rule_score=95,
            ml_score=90,
            ai_score=50,
            data_quality="test",
            extra={"atr_pct": 12, "distance_to_20d_high_pct": -0.2},
        ),
        MarketSnapshot(
            symbol="BREAKOUT",
            current_price=20,
            recent_high_15m=20,
            atr14=1,
            avg_dollar_volume_20d=30000000,
            rule_score=90,
            ml_score=88,
            ai_score=50,
            data_quality="test",
            extra={"atr_pct": 5, "distance_to_20d_high_pct": -0.3},
        ),
        MarketSnapshot(
            symbol="PULLBACK",
            current_price=20,
            recent_high_15m=20,
            atr14=1,
            avg_dollar_volume_20d=30000000,
            rule_score=89,
            ml_score=88,
            ai_score=50,
            data_quality="test",
            extra={"atr_pct": 5, "distance_to_20d_high_pct": -3},
        ),
    ]

    recs = engine.recommend(snapshots, {}, "regular")

    assert [rec.symbol for rec in recs] == ["BREAKOUT"]
    assert any("high yield" in reason.lower() for reason in recs[0].reasons)


def test_high_yield_breakout_mode_can_require_momentum_and_volume():
    engine = RecommendationEngine(
        config={
            "universe": {"min_price": 2.0, "min_avg_dollar_volume_20d": 10000000},
            "scoring": {
                "rule_weight": 0.6,
                "ml_weight": 0.25,
                "ai_weight": 0.15,
                "trigger_mode": "high_yield_breakout",
                "high_yield": {
                    "min_score": 70,
                    "candidate_pool_limit": 5,
                    "top_n": 5,
                    "min_atr_pct": 5,
                    "max_atr_pct": 999,
                    "min_distance_to_20d_high_pct": -999,
                    "min_momentum_20_pct": 60,
                    "min_volume_ratio": 2,
                },
            },
            "pricing": _pricing_config(take_profit_2_atr_multiple=6.0),
        }
    )
    snapshots = [
        MarketSnapshot(
            symbol="LOWMOM",
            current_price=20,
            recent_high_15m=20,
            atr14=1.2,
            avg_dollar_volume_20d=30000000,
            rule_score=95,
            ml_score=90,
            ai_score=50,
            data_quality="test",
            extra={"atr_pct": 6, "distance_to_20d_high_pct": -20, "momentum_20_pct": 25, "volume_ratio": 3},
        ),
        MarketSnapshot(
            symbol="LOWVOL",
            current_price=20,
            recent_high_15m=20,
            atr14=1.2,
            avg_dollar_volume_20d=30000000,
            rule_score=94,
            ml_score=90,
            ai_score=50,
            data_quality="test",
            extra={"atr_pct": 6, "distance_to_20d_high_pct": -20, "momentum_20_pct": 80, "volume_ratio": 1.3},
        ),
        MarketSnapshot(
            symbol="STRONG",
            current_price=20,
            recent_high_15m=20,
            atr14=1.2,
            avg_dollar_volume_20d=30000000,
            rule_score=93,
            ml_score=90,
            ai_score=50,
            data_quality="test",
            extra={"atr_pct": 6, "distance_to_20d_high_pct": -20, "momentum_20_pct": 80, "volume_ratio": 3},
        ),
    ]

    recs = engine.recommend(snapshots, {}, "regular")

    assert [rec.symbol for rec in recs] == ["STRONG"]


def test_high_yield_breakout_mode_can_require_short_term_momentum():
    engine = RecommendationEngine(
        config={
            "universe": {"min_price": 2.0, "min_avg_dollar_volume_20d": 10000000},
            "scoring": {
                "rule_weight": 0.6,
                "ml_weight": 0.25,
                "ai_weight": 0.15,
                "trigger_mode": "high_yield_breakout",
                "high_yield": {
                    "min_score": 70,
                    "candidate_pool_limit": 5,
                    "top_n": 5,
                    "min_atr_pct": 5,
                    "max_atr_pct": 999,
                    "min_distance_to_20d_high_pct": -999,
                    "min_momentum_20_pct": 150,
                    "min_momentum_5_pct": 20,
                    "min_volume_ratio": 2,
                },
            },
            "pricing": _pricing_config(take_profit_2_atr_multiple=7.0),
        }
    )
    snapshots = [
        MarketSnapshot(
            symbol="SLOW5",
            current_price=20,
            recent_high_15m=20,
            atr14=1.2,
            avg_dollar_volume_20d=30000000,
            rule_score=95,
            ml_score=90,
            ai_score=50,
            data_quality="test",
            extra={
                "atr_pct": 6,
                "distance_to_20d_high_pct": -20,
                "momentum_20_pct": 180,
                "momentum_5_pct": 12,
                "volume_ratio": 3,
            },
        ),
        MarketSnapshot(
            symbol="FAST5",
            current_price=20,
            recent_high_15m=20,
            atr14=1.2,
            avg_dollar_volume_20d=30000000,
            rule_score=94,
            ml_score=90,
            ai_score=50,
            data_quality="test",
            extra={
                "atr_pct": 6,
                "distance_to_20d_high_pct": -20,
                "momentum_20_pct": 180,
                "momentum_5_pct": 25,
                "volume_ratio": 3,
            },
        ),
    ]

    recs = engine.recommend(snapshots, {}, "regular")

    assert [rec.symbol for rec in recs] == ["FAST5"]
    assert "5d momentum >= 20%" in recs[0].reasons[0]


def test_high_yield_breakout_mode_can_require_sixty_day_high_proximity():
    engine = RecommendationEngine(
        config={
            "universe": {"min_price": 2.0, "min_avg_dollar_volume_20d": 10000000},
            "scoring": {
                "rule_weight": 0.6,
                "ml_weight": 0.25,
                "ai_weight": 0.15,
                "trigger_mode": "high_yield_breakout",
                "high_yield": {
                    "min_score": 70,
                    "candidate_pool_limit": 5,
                    "top_n": 5,
                    "min_atr_pct": 5,
                    "max_atr_pct": 999,
                    "min_distance_to_20d_high_pct": -999,
                    "min_distance_to_60d_high_pct": -5,
                    "min_momentum_20_pct": 150,
                    "min_momentum_5_pct": 60,
                    "min_volume_ratio": 2,
                },
            },
            "pricing": _pricing_config(take_profit_2_atr_multiple=7.0),
        }
    )
    snapshots = [
        MarketSnapshot(
            symbol="FAR60",
            current_price=20,
            recent_high_15m=20,
            atr14=1.2,
            avg_dollar_volume_20d=30000000,
            rule_score=95,
            ml_score=90,
            ai_score=50,
            data_quality="test",
            extra={
                "atr_pct": 6,
                "distance_to_20d_high_pct": -2,
                "distance_to_60d_high_pct": -20,
                "momentum_20_pct": 180,
                "momentum_5_pct": 80,
                "volume_ratio": 3,
            },
        ),
        MarketSnapshot(
            symbol="NEAR60",
            current_price=20,
            recent_high_15m=20,
            atr14=1.2,
            avg_dollar_volume_20d=30000000,
            rule_score=94,
            ml_score=90,
            ai_score=50,
            data_quality="test",
            extra={
                "atr_pct": 6,
                "distance_to_20d_high_pct": -2,
                "distance_to_60d_high_pct": -3,
                "momentum_20_pct": 180,
                "momentum_5_pct": 80,
                "volume_ratio": 3,
            },
        ),
    ]

    recs = engine.recommend(snapshots, {}, "regular")

    assert [rec.symbol for rec in recs] == ["NEAR60"]
    assert "60d high distance >= -5%" in recs[0].reasons[0]


def test_high_yield_breakout_mode_can_filter_extreme_gap_and_price():
    engine = RecommendationEngine(
        config={
            "universe": {"min_price": 2.0, "min_avg_dollar_volume_20d": 10000000},
            "scoring": {
                "rule_weight": 0.6,
                "ml_weight": 0.25,
                "ai_weight": 0.15,
                "trigger_mode": "high_yield_breakout",
                "high_yield": {
                    "min_score": 70,
                    "candidate_pool_limit": 5,
                    "top_n": 5,
                    "min_atr_pct": 5,
                    "max_atr_pct": 999,
                    "min_distance_to_20d_high_pct": -999,
                    "min_momentum_20_pct": 150,
                    "min_momentum_5_pct": 60,
                    "min_volume_ratio": 2,
                    "max_gap_pct": 80,
                    "max_price": 100,
                },
            },
            "pricing": _pricing_config(take_profit_2_atr_multiple=7.0),
        }
    )
    common_extra = {
        "atr_pct": 6,
        "distance_to_20d_high_pct": -20,
        "momentum_20_pct": 180,
        "momentum_5_pct": 80,
        "volume_ratio": 3,
    }
    snapshots = [
        MarketSnapshot(
            symbol="GAP",
            current_price=20,
            recent_high_15m=20,
            atr14=1.2,
            avg_dollar_volume_20d=30000000,
            rule_score=95,
            ml_score=90,
            ai_score=50,
            data_quality="test",
            extra={**common_extra, "gap_pct": 120},
        ),
        MarketSnapshot(
            symbol="PRICE",
            current_price=120,
            recent_high_15m=120,
            atr14=7.2,
            avg_dollar_volume_20d=30000000,
            rule_score=94,
            ml_score=90,
            ai_score=50,
            data_quality="test",
            extra={**common_extra, "gap_pct": 20},
        ),
        MarketSnapshot(
            symbol="OK",
            current_price=20,
            recent_high_15m=20,
            atr14=1.2,
            avg_dollar_volume_20d=30000000,
            rule_score=93,
            ml_score=90,
            ai_score=50,
            data_quality="test",
            extra={**common_extra, "gap_pct": 20},
        ),
    ]

    recs = engine.recommend(snapshots, {}, "regular")

    assert [rec.symbol for rec in recs] == ["OK"]
    assert "gap <= 80%" in recs[0].reasons[0]
    assert "price <= 100" in recs[0].reasons[0]
