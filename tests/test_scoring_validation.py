from datetime import date, timedelta

import pandas as pd
import us_stock_signal.scoring_validation as scoring_validation

from us_stock_signal.models import BacktestTradeResult
from us_stock_signal.scoring_validation import (
    PreparedSignalDay,
    PreparedValidationData,
    ValidatedSignal,
    _single_position_metrics,
    _future_buffer_days,
    _validation_take_profit,
    _validation_take_profit_label,
    build_snapshot_from_daily_history,
    validate_prepared_signal_days,
    validate_scoring_from_daily_bars,
)
from us_stock_signal.models import Recommendation


def test_build_snapshot_from_daily_history_uses_only_as_of_rows():
    rows = []
    start = date(2026, 1, 1)
    for idx in range(70):
        rows.append(
            {
                "symbol": "AAA",
                "bar_date": start + timedelta(days=idx),
                "open": 10 + idx,
                "high": 10.5 + idx,
                "low": 9.5 + idx,
                "close": 10 + idx,
                "volume": 1_000_000,
            }
        )
    frame = pd.DataFrame(rows)
    as_of_history = frame[frame["bar_date"] <= start + timedelta(days=59)]

    snapshot = build_snapshot_from_daily_history("AAA", as_of_history, min_history_days=50)

    assert snapshot is not None
    assert snapshot.current_price == 69
    assert snapshot.current_price != 79


def test_validate_scoring_from_daily_bars_reports_future_path_outcomes():
    rows = []
    start = date(2026, 1, 1)
    for idx in range(75):
        signal_ready_close = 10 + idx * 0.2
        rows.append(
            {
                "symbol": "WIN",
                "bar_date": start + timedelta(days=idx),
                "open": signal_ready_close,
                "high": signal_ready_close + 0.3,
                "low": signal_ready_close - 0.2,
                "close": signal_ready_close,
                "volume": 2_000_000 if idx < 60 else 3_000_000,
            }
        )
        weaker_close = 10 + idx * 0.02
        rows.append(
            {
                "symbol": "FLAT",
                "bar_date": start + timedelta(days=idx),
                "open": weaker_close,
                "high": weaker_close + 0.1,
                "low": weaker_close - 0.1,
                "close": weaker_close,
                "volume": 2_000_000,
            }
        )
    frame = pd.DataFrame(rows)
    report = validate_scoring_from_daily_bars(
        frame,
        {
            "universe": {"min_price": 2.0, "min_avg_dollar_volume_20d": 1_000_000},
            "scoring": {"rule_weight": 0.6, "ml_weight": 0.25, "ai_weight": 0.15, "min_score": 0, "top_n": 1},
            "pricing": {
                "stop_atr_multiple": 1.2,
                "take_profit_1_atr_multiple": 1.8,
                "take_profit_2_atr_multiple": 3.0,
                "min_stop_pct": 0.03,
                "max_stop_pct": 0.08,
                "entry_buffer_pct": 0.002,
                "pending_signal_expiry_trading_days": 2,
            },
            "backtest": {"slippage_bps": 0, "ibkr_min_commission": 0, "ibkr_commission_per_share": 0},
        },
        lookback_days=120,
        top_n=1,
        sample_days=1,
        max_holding_days=10,
        min_history_days=50,
    )

    assert report["sample_days_evaluated"] == 1
    assert report["summary"]["signal_count"] == 1
    assert report["summary"]["entered_count"] == 1
    assert report["rank_metrics"][0]["rank"] == 1
    assert report["sample_signals"][0]["symbol"] == "WIN"


def test_validation_can_use_take_profit_2_as_primary_target():
    rec = Recommendation(
        id="r1",
        symbol="AAA",
        rank=1,
        score=90,
        session="regular",
        current_price=10,
        entry_price_low=10,
        entry_price_high=10.1,
        stop_loss=9.5,
        take_profit_1=11,
        take_profit_2=12,
        expiry="2 个交易日",
        invalidation_price=9.9,
        reasons=[],
        risk_flags=[],
        data_quality="test",
        ai_status="neutral_or_missing",
    )

    assert _validation_take_profit(rec, {"scoring": {"high_yield": {"primary_take_profit": "tp2"}}}) == 12
    assert _validation_take_profit(rec, {"scoring": {}}) == 11
    assert _validation_take_profit_label({"scoring": {"high_yield": {"primary_take_profit": "tp2"}}}) == "TAKE_PROFIT_2"
    assert _validation_take_profit_label({"scoring": {}}) == "TAKE_PROFIT_1"


def test_single_position_metrics_compound_and_skip_overlapping_signals():
    signals = [
        ValidatedSignal(
            signal_date=date(2026, 1, 1),
            symbol="A",
            rank=1,
            score=90,
            exit_reason="TAKE_PROFIT_2",
            return_pct=10,
            bars_held=4,
            exit_date=date(2026, 1, 5),
        ),
        ValidatedSignal(
            signal_date=date(2026, 1, 2),
            symbol="B",
            rank=1,
            score=95,
            exit_reason="TAKE_PROFIT_2",
            return_pct=100,
            bars_held=1,
            exit_date=date(2026, 1, 3),
        ),
        ValidatedSignal(
            signal_date=date(2026, 1, 6),
            symbol="C",
            rank=1,
            score=80,
            exit_reason="STOP_LOSS",
            return_pct=-10,
            bars_held=1,
            exit_date=date(2026, 1, 7),
        ),
    ]

    metrics = _single_position_metrics(signals)

    assert metrics["single_position_trade_count"] == 2
    assert metrics["single_position_skipped_signals"] == 1
    assert metrics["single_position_final_equity"] == 0.99
    assert metrics["single_position_total_return_pct"] == -1
    assert metrics["single_position_max_drawdown_pct"] == 10


def test_future_buffer_days_keeps_sampling_horizon_at_least_configured_value():
    assert _future_buffer_days({"backtest": {"validation_future_days": 10}}, max_holding_days=3) == 10
    assert _future_buffer_days({"backtest": {"validation_future_days": 5}}, max_holding_days=7) == 7


def test_validate_prepared_signal_days_passes_configured_entry_expiry_to_backtest(monkeypatch):
    captured = {}

    class FakeRecommendationEngine:
        def __init__(self, config):
            self.config = config

        def recommend(self, snapshots, news_by_symbol, session):
            return [
                Recommendation(
                    id="r1",
                    symbol="AAA",
                    rank=1,
                    score=90,
                    session=session,
                    current_price=10,
                    entry_price_low=10,
                    entry_price_high=10.5,
                    stop_loss=9.5,
                    take_profit_1=11,
                    take_profit_2=12,
                    expiry="2 trading days",
                    invalidation_price=9.9,
                    reasons=[],
                    risk_flags=[],
                    data_quality="test",
                    ai_status="neutral_or_missing",
                )
            ]

    def fake_run_path_backtest(*args, entry_expiry_bars=None, **kwargs):
        captured["entry_expiry_bars"] = entry_expiry_bars
        return BacktestTradeResult(
            entry_price=0,
            exit_price=10,
            exit_reason="NO_ENTRY",
            bars_held=0,
            return_pct=0,
            entry_bar_index=0,
            exit_bar_index=entry_expiry_bars or 0,
        )

    monkeypatch.setattr(scoring_validation, "RecommendationEngine", FakeRecommendationEngine)
    monkeypatch.setattr(scoring_validation, "run_path_backtest", fake_run_path_backtest)
    start = date(2026, 1, 1)
    future_path = pd.DataFrame(
        {
            "bar_date": [start + timedelta(days=idx) for idx in range(6)],
            "high": [10, 10, 10, 11, 11, 11],
            "low": [9, 9, 9, 9, 9, 9],
            "close": [10, 10, 10, 10, 10, 10],
        }
    )
    prepared = PreparedValidationData(
        lookback_days=365,
        sample_days_requested=1,
        eval_dates=[start],
        days=[
            PreparedSignalDay(
                signal_date=start,
                snapshots=[object()],
                futures_by_symbol={"AAA": future_path},
            )
        ],
    )

    validate_prepared_signal_days(
        prepared,
        {
            "universe": {},
            "scoring": {},
            "pricing": {"pending_signal_expiry_trading_days": 2},
            "backtest": {"slippage_bps": 0, "ibkr_min_commission": 0, "ibkr_commission_per_share": 0},
        },
        top_n=1,
        max_holding_days=5,
    )

    assert captured["entry_expiry_bars"] == 2
