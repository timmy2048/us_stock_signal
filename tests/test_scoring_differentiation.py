from us_stock_signal.features.technical import score_technical_snapshot
from us_stock_signal.models_ml.simple_model import heuristic_ml_score


def test_technical_score_keeps_strong_setups_differentiated():
    momentum_surge_closes = [50.0] * 40 + [
        52.0,
        53.0,
        54.0,
        55.0,
        56.0,
        57.0,
        58.0,
        59.0,
        60.0,
        62.0,
        64.0,
        66.0,
        68.0,
        70.0,
        72.0,
        74.0,
        76.0,
        78.0,
        80.0,
        82.0,
    ]
    volume_breakout_closes = [50.0 + idx * 0.15 for idx in range(50)] + [
        58.0,
        60.0,
        62.0,
        64.0,
        66.0,
        68.0,
        70.0,
        72.0,
        74.0,
        76.0,
    ]

    momentum_score, _, _ = score_technical_snapshot(
        momentum_surge_closes,
        [1_000_000] * 59 + [1_100_000],
        momentum_surge_closes[-1],
    )
    volume_score, _, _ = score_technical_snapshot(
        volume_breakout_closes,
        [1_000_000] * 59 + [2_200_000],
        volume_breakout_closes[-1],
    )

    assert momentum_score < 100
    assert volume_score < 100
    assert momentum_score != volume_score


def test_heuristic_ml_score_does_not_flatten_high_rule_scores_to_100():
    normal_volume_score = heuristic_ml_score(rule_score=100, atr_pct=0.04, volume_ratio=1.2)
    surge_volume_score = heuristic_ml_score(rule_score=100, atr_pct=0.04, volume_ratio=2.5)

    assert normal_volume_score < 100
    assert surge_volume_score < 100
    assert normal_volume_score != surge_volume_score
