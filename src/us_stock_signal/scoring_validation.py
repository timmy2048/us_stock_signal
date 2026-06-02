from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from statistics import mean
from typing import Any

import pandas as pd

from .backtest import run_path_backtest
from .features.technical import average_true_range, score_technical_snapshot, technical_snapshot_features
from .models import MarketSnapshot
from .models_ml.simple_model import heuristic_ml_score
from .recommender import RecommendationEngine


@dataclass(slots=True)
class ValidatedSignal:
    signal_date: date
    symbol: str
    rank: int
    score: float
    exit_reason: str
    return_pct: float
    bars_held: int
    exit_date: date


@dataclass(slots=True)
class SymbolBars:
    frame: pd.DataFrame
    dates: list[date]


@dataclass(slots=True)
class PreparedSignalDay:
    signal_date: date
    snapshots: list[MarketSnapshot]
    futures_by_symbol: dict[str, pd.DataFrame]


@dataclass(slots=True)
class PreparedValidationData:
    lookback_days: int
    sample_days_requested: int
    eval_dates: list[date]
    days: list[PreparedSignalDay]
    reason: str = ""


def build_snapshot_from_daily_history(
    symbol: str,
    history: pd.DataFrame,
    min_history_days: int = 50,
) -> MarketSnapshot | None:
    if len(history) < min_history_days:
        return None
    frame = history.sort_values("bar_date").tail(90)
    current_price = float(frame.iloc[-1]["close"])
    if current_price <= 0:
        return None
    highs = frame["high"].tolist()
    lows = frame["low"].tolist()
    opens = frame["open"].tolist()
    closes = frame["close"].tolist()
    volumes = frame["volume"].tolist()
    atr = average_true_range(highs, lows, closes, period=14)
    if atr <= 0:
        return None
    avg_volume = float(frame["volume"].tail(20).mean())
    volume_ratio = float(frame.iloc[-1]["volume"]) / avg_volume if avg_volume else 1.0
    rule_score, reasons, risks = score_technical_snapshot(closes, volumes, current_price)
    ml_score = heuristic_ml_score(rule_score, atr / current_price, volume_ratio)
    extra = technical_snapshot_features(closes, highs, volumes, current_price, opens=opens, lows=lows)
    extra["atr_pct"] = atr / current_price * 100
    return MarketSnapshot(
        symbol=symbol,
        current_price=current_price,
        recent_high_15m=current_price,
        atr14=float(atr),
        avg_dollar_volume_20d=avg_volume * current_price,
        rule_score=rule_score,
        ml_score=ml_score,
        ai_score=50,
        reasons=reasons + ["历史评分验证"],
        risk_flags=risks,
        data_quality="historical_daily",
        extra=extra,
    )


def prepare_validation_data(
    daily_bars: pd.DataFrame,
    lookback_days: int = 365,
    sample_days: int = 40,
    max_holding_days: int = 10,
    min_history_days: int = 50,
) -> PreparedValidationData:
    if daily_bars.empty:
        return PreparedValidationData(lookback_days, sample_days, [], [], "no_daily_bars")

    bars = daily_bars.copy()
    bars["bar_date"] = pd.to_datetime(bars["bar_date"]).dt.date
    bars = bars.sort_values(["symbol", "bar_date"]).reset_index(drop=True)
    all_dates = sorted(bars["bar_date"].unique())
    if not all_dates:
        return PreparedValidationData(lookback_days, sample_days, [], [], "no_trading_dates")

    latest_date = all_dates[-1]
    earliest_signal_date = latest_date - timedelta(days=lookback_days)
    eligible_dates = [
        item
        for idx, item in enumerate(all_dates)
        if item >= earliest_signal_date and idx >= min_history_days and idx + max_holding_days < len(all_dates)
    ]
    eval_dates = _evenly_spaced_dates(eligible_dates, sample_days)
    if not eval_dates:
        return PreparedValidationData(lookback_days, sample_days, [], [], "not_enough_history_or_future")

    grouped = {
        symbol: SymbolBars(
            frame=frame.sort_values("bar_date").reset_index(drop=True),
            dates=frame.sort_values("bar_date")["bar_date"].tolist(),
        )
        for symbol, frame in bars.groupby("symbol", sort=False)
    }

    days: list[PreparedSignalDay] = []
    for signal_date in eval_dates:
        snapshots: list[MarketSnapshot] = []
        futures_by_symbol: dict[str, pd.DataFrame] = {}
        for symbol, symbol_bars in grouped.items():
            idx = bisect_right(symbol_bars.dates, signal_date) - 1
            if idx < 0 or symbol_bars.dates[idx] != signal_date:
                continue
            history = symbol_bars.frame.iloc[max(0, idx - 89) : idx + 1]
            future_path = symbol_bars.frame.iloc[idx : idx + max_holding_days + 1]
            if len(future_path) < 2:
                continue
            snapshot = build_snapshot_from_daily_history(symbol, history, min_history_days=min_history_days)
            if snapshot is None:
                continue
            snapshots.append(snapshot)
            futures_by_symbol[symbol] = future_path
        days.append(PreparedSignalDay(signal_date=signal_date, snapshots=snapshots, futures_by_symbol=futures_by_symbol))

    return PreparedValidationData(lookback_days, sample_days, eval_dates, days)


def validate_scoring_from_daily_bars(
    daily_bars: pd.DataFrame,
    config: dict[str, Any],
    lookback_days: int = 365,
    top_n: int = 10,
    sample_days: int = 40,
    max_holding_days: int = 10,
    min_history_days: int = 50,
) -> dict[str, Any]:
    prepared = prepare_validation_data(
        daily_bars,
        lookback_days=lookback_days,
        sample_days=sample_days,
        max_holding_days=_future_buffer_days(config, max_holding_days),
        min_history_days=min_history_days,
    )
    return validate_prepared_signal_days(
        prepared,
        config,
        top_n=top_n,
        max_holding_days=max_holding_days,
    )


def validate_prepared_signal_days(
    prepared: PreparedValidationData,
    config: dict[str, Any],
    top_n: int = 10,
    max_holding_days: int = 10,
) -> dict[str, Any]:
    if prepared.reason:
        return _empty_report(prepared.lookback_days, top_n, prepared.sample_days_requested, prepared.reason)

    engine = RecommendationEngine(
        {
            "universe": config.get("universe", {}),
            "scoring": _scoring_with_top_n(config.get("scoring", {}), top_n),
            "pricing": config.get("pricing", {}),
        }
    )
    backtest_config = config.get("backtest", {})
    slippage_bps = float(backtest_config.get("slippage_bps", 10))
    notional = float(backtest_config.get("notional_per_trade", 10000))
    min_commission = float(backtest_config.get("ibkr_min_commission", 1.0))
    commission_per_share = float(backtest_config.get("ibkr_commission_per_share", 0.005))

    signals: list[ValidatedSignal] = []
    candidate_counts: list[int] = []
    for day in prepared.days:
        recommendations = engine.recommend(day.snapshots, {}, "regular")
        candidate_counts.append(len(recommendations))
        for rec in recommendations:
            path = day.futures_by_symbol.get(rec.symbol)
            if path is None or len(path) < 2:
                continue
            result = run_path_backtest(
                path[["high", "low", "close"]],
                entry_price_high=rec.entry_price_high,
                stop_loss=rec.stop_loss,
                take_profit_1=_validation_take_profit(rec, config),
                max_bars=max_holding_days,
                entry_expiry_bars=_entry_expiry_bars(config, max_holding_days),
                slippage_bps=slippage_bps,
                commission=_round_trip_commission_per_share(
                    rec.entry_price_high,
                    notional,
                    min_commission,
                    commission_per_share,
                ),
                take_profit_label=_validation_take_profit_label(config),
            )
            signals.append(
                ValidatedSignal(
                    signal_date=day.signal_date,
                    symbol=rec.symbol,
                    rank=rec.rank,
                    score=rec.score,
                    exit_reason=result.exit_reason,
                    return_pct=result.return_pct,
                    bars_held=result.bars_held,
                    exit_date=_path_exit_date(path, result.exit_bar_index),
                )
            )

    summary = _summarize_signals(signals, top_n=top_n)
    return {
        "lookback_days": prepared.lookback_days,
        "top_n": top_n,
        "sample_days_requested": prepared.sample_days_requested,
        "sample_days_evaluated": len(prepared.eval_dates),
        "first_signal_date": prepared.eval_dates[0].isoformat() if prepared.eval_dates else None,
        "last_signal_date": prepared.eval_dates[-1].isoformat() if prepared.eval_dates else None,
        "avg_candidates_per_day": round(mean(candidate_counts), 2) if candidate_counts else 0,
        "summary": summary,
        "rank_metrics": _rank_metrics(signals, top_n),
        "sample_signals": [asdict(item) for item in signals[:50]],
    }


def _scoring_with_top_n(scoring: dict[str, Any], top_n: int) -> dict[str, Any]:
    copied = {**scoring, "top_n": top_n}
    if isinstance(scoring.get("high_yield"), dict):
        copied["high_yield"] = {**scoring["high_yield"], "top_n": top_n}
    return copied


def _future_buffer_days(config: dict[str, Any], max_holding_days: int) -> int:
    configured = int(config.get("backtest", {}).get("validation_future_days", max_holding_days))
    return max(int(max_holding_days), configured)


def _entry_expiry_bars(config: dict[str, Any], max_holding_days: int) -> int:
    configured = int(config.get("pricing", {}).get("pending_signal_expiry_trading_days", max_holding_days))
    return min(max(1, configured), int(max_holding_days))


def _validation_take_profit(rec, config: dict[str, Any]) -> float:
    scoring = config.get("scoring", {})
    high_yield = scoring.get("high_yield", {})
    target = high_yield.get("primary_take_profit", scoring.get("primary_take_profit", "tp1"))
    return rec.take_profit_2 if target in {"tp2", "take_profit_2"} else rec.take_profit_1


def _validation_take_profit_label(config: dict[str, Any]) -> str:
    scoring = config.get("scoring", {})
    high_yield = scoring.get("high_yield", {})
    target = high_yield.get("primary_take_profit", scoring.get("primary_take_profit", "tp1"))
    return "TAKE_PROFIT_2" if target in {"tp2", "take_profit_2"} else "TAKE_PROFIT_1"


def _round_trip_commission_per_share(
    entry_price: float,
    notional: float,
    min_commission: float,
    commission_per_share: float,
) -> float:
    if entry_price <= 0 or notional <= 0:
        return 0.0
    shares = max(notional / entry_price, 1.0)
    one_way = max(min_commission, shares * commission_per_share)
    return (one_way * 2) / shares


def _summarize_signals(signals: list[ValidatedSignal], top_n: int) -> dict[str, Any]:
    entered = [item for item in signals if item.exit_reason != "NO_ENTRY"]
    wins = [item for item in entered if item.return_pct > 0]
    losses = [item for item in entered if item.return_pct < 0]
    gross_profit = sum(item.return_pct for item in wins)
    gross_loss = abs(sum(item.return_pct for item in losses))
    exit_counts: dict[str, int] = {}
    for item in signals:
        exit_counts[item.exit_reason] = exit_counts.get(item.exit_reason, 0) + 1
    single_position = _single_position_metrics(signals)
    return {
        "signal_count": len(signals),
        "entered_count": len(entered),
        "no_entry_count": exit_counts.get("NO_ENTRY", 0),
        "entry_rate": round(len(entered) / len(signals), 4) if signals else 0.0,
        "win_rate": round(len(wins) / len(entered), 4) if entered else 0.0,
        "avg_return_pct": round(mean([item.return_pct for item in entered]), 4) if entered else 0.0,
        "avg_return_pct_all_signals": round(mean([item.return_pct for item in signals]), 4) if signals else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else ("inf" if gross_profit > 0 else 0),
        "max_drawdown_pct": _max_drawdown_pct(entered),
        "avg_bars_held": round(mean([item.bars_held for item in entered]), 2) if entered else 0.0,
        "exit_reason_counts": exit_counts,
        "top_n": top_n,
        **single_position,
    }


def _single_position_metrics(signals: list[ValidatedSignal]) -> dict[str, Any]:
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    selected: list[ValidatedSignal] = []
    skipped = 0
    locked_until: date | None = None
    for item in sorted(signals, key=lambda value: (value.signal_date, value.rank)):
        if locked_until is not None and item.signal_date <= locked_until:
            skipped += 1
            continue
        if item.exit_reason == "NO_ENTRY":
            continue
        selected.append(item)
        equity *= 1 + item.return_pct / 100
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
        locked_until = item.exit_date

    wins = [item for item in selected if item.return_pct > 0]
    losses = [item for item in selected if item.return_pct < 0]
    gross_profit = sum(item.return_pct for item in wins)
    gross_loss = abs(sum(item.return_pct for item in losses))
    return {
        "single_position_trade_count": len(selected),
        "single_position_skipped_signals": skipped,
        "single_position_final_equity": round(equity, 6),
        "single_position_total_return_pct": round((equity - 1) * 100, 4),
        "single_position_win_rate": round(len(wins) / len(selected), 4) if selected else 0.0,
        "single_position_avg_return_pct": round(mean([item.return_pct for item in selected]), 4) if selected else 0.0,
        "single_position_profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else ("inf" if gross_profit > 0 else 0),
        "single_position_max_drawdown_pct": round(max_drawdown * 100, 4),
    }


def _rank_metrics(signals: list[ValidatedSignal], top_n: int) -> list[dict[str, Any]]:
    rows = []
    for rank in range(1, top_n + 1):
        rank_signals = [item for item in signals if item.rank == rank]
        if not rank_signals:
            continue
        rows.append({"rank": rank, **_summarize_signals(rank_signals, top_n=1)})
    return rows


def _path_exit_date(path: pd.DataFrame, exit_bar_index: int) -> date:
    rows = path.reset_index(drop=True)
    idx = min(max(int(exit_bar_index), 0), len(rows) - 1)
    value = rows.iloc[idx]["bar_date"]
    return pd.to_datetime(value).date()


def _max_drawdown_pct(signals: list[ValidatedSignal]) -> float:
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for item in sorted(signals, key=lambda value: (value.signal_date, value.rank)):
        equity *= 1 + item.return_pct / 100
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return round(max_drawdown * 100, 4)


def _evenly_spaced_dates(dates: list[date], sample_days: int) -> list[date]:
    if sample_days <= 0 or len(dates) <= sample_days:
        return dates
    if sample_days == 1:
        return [dates[-1]]
    indexes = [round(idx * (len(dates) - 1) / (sample_days - 1)) for idx in range(sample_days)]
    return [dates[idx] for idx in sorted(set(indexes))]


def _empty_report(lookback_days: int, top_n: int, sample_days: int, reason: str) -> dict[str, Any]:
    return {
        "lookback_days": lookback_days,
        "top_n": top_n,
        "sample_days_requested": sample_days,
        "sample_days_evaluated": 0,
        "reason": reason,
        "summary": _summarize_signals([], top_n=top_n),
        "rank_metrics": [],
        "sample_signals": [],
    }
