from us_stock_signal.features.technical import technical_snapshot_features


def test_technical_snapshot_features_include_price_action_context():
    closes = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 40]
    highs = [value + 1 for value in closes[:-1]] + [50]
    lows = [value - 1 for value in closes[:-1]] + [35]
    opens = [value - 0.5 for value in closes[:-1]] + [32]
    volumes = [1000] * 24 + [3000]

    features = technical_snapshot_features(closes, highs, volumes, current_price=40, opens=opens, lows=lows)

    assert round(features["gap_pct"], 2) == -3.03
    assert round(features["intraday_pct"], 2) == 25.0
    assert round(features["close_position_pct"], 2) == 33.33
    assert round(features["upper_wick_pct"], 2) == 25.0
    assert round(features["lower_wick_pct"], 2) == 14.29
    assert round(features["day_range_pct"], 2) == 37.5
