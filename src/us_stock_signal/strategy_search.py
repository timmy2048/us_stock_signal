from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from math import isinf
from typing import Any, Iterable

import pandas as pd

from .scoring_validation import _future_buffer_days, prepare_validation_data, validate_prepared_signal_days


@dataclass(frozen=True, slots=True)
class HighYieldStrategyVariant:
    name: str
    candidate_pool_limit: int
    top_n: int
    min_score: float
    min_atr_pct: float
    max_atr_pct: float
    min_distance_to_20d_high_pct: float
    take_profit_2_atr_multiple: float
    min_distance_to_60d_high_pct: float | None = None
    min_momentum_20_pct: float | None = None
    min_momentum_5_pct: float | None = None
    min_volume_ratio: float | None = None
    max_gap_pct: float | None = None
    max_price: float | None = None
    stop_atr_multiple: float | None = None
    min_stop_pct: float | None = None
    max_stop_pct: float | None = None
    entry_buffer_pct: float | None = None
    pending_entry_days: int | None = None
    max_holding_days: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_high_yield_variants() -> list[HighYieldStrategyVariant]:
    variants: list[HighYieldStrategyVariant] = []

    def add(
        profile: str,
        candidate_pool_limit: int,
        top_n: int,
        min_score: float,
        min_atr_pct: float,
        max_atr_pct: float,
        min_distance_to_20d_high_pct: float,
        take_profit_2_atr_multiple: float,
        min_distance_to_60d_high_pct: float | None = None,
        min_momentum_20_pct: float | None = None,
        min_momentum_5_pct: float | None = None,
        min_volume_ratio: float | None = None,
        max_gap_pct: float | None = None,
        max_price: float | None = None,
        stop_atr_multiple: float | None = None,
        min_stop_pct: float | None = None,
        max_stop_pct: float | None = None,
        entry_buffer_pct: float | None = None,
        pending_entry_days: int | None = None,
        max_holding_days: int | None = None,
    ) -> None:
        parts = [
            profile,
            f"pool{candidate_pool_limit}",
            f"top{top_n}",
            f"score{min_score:g}",
            f"atr{min_atr_pct:g}-{max_atr_pct:g}",
            f"tp{take_profit_2_atr_multiple:g}",
        ]
        if min_momentum_20_pct is not None:
            parts.append(f"mom{min_momentum_20_pct:g}")
        if min_distance_to_60d_high_pct is not None:
            parts.append(f"dist60_{min_distance_to_60d_high_pct:g}")
        if min_momentum_5_pct is not None:
            parts.append(f"mom5_{min_momentum_5_pct:g}")
        if min_volume_ratio is not None:
            parts.append(f"vol{min_volume_ratio:g}")
        if max_gap_pct is not None:
            parts.append(f"gapmax{max_gap_pct:g}")
        if max_price is not None:
            parts.append(f"pricemax{max_price:g}")
        if stop_atr_multiple is not None:
            parts.append(f"stop{stop_atr_multiple:g}")
        if min_stop_pct is not None:
            parts.append(f"minstop{min_stop_pct:g}")
        if max_stop_pct is not None:
            parts.append(f"maxstop{max_stop_pct:g}")
        if entry_buffer_pct is not None:
            parts.append(f"entrybuf{entry_buffer_pct * 100:g}pct")
        if pending_entry_days is not None:
            parts.append(f"pending{pending_entry_days}")
        if max_holding_days is not None:
            parts.append(f"hold{max_holding_days}")
        variants.append(
            HighYieldStrategyVariant(
                name="_".join(parts),
                candidate_pool_limit=candidate_pool_limit,
                top_n=top_n,
                min_score=min_score,
                min_atr_pct=min_atr_pct,
                max_atr_pct=max_atr_pct,
                min_distance_to_20d_high_pct=min_distance_to_20d_high_pct,
                take_profit_2_atr_multiple=take_profit_2_atr_multiple,
                min_distance_to_60d_high_pct=min_distance_to_60d_high_pct,
                min_momentum_20_pct=min_momentum_20_pct,
                min_momentum_5_pct=min_momentum_5_pct,
                min_volume_ratio=min_volume_ratio,
                max_gap_pct=max_gap_pct,
                max_price=max_price,
                stop_atr_multiple=stop_atr_multiple,
                min_stop_pct=min_stop_pct,
                max_stop_pct=max_stop_pct,
                entry_buffer_pct=entry_buffer_pct,
                pending_entry_days=pending_entry_days,
                max_holding_days=max_holding_days,
            )
        )

    for top_n in [2, 5, 10]:
        for tp2 in [3, 4, 6]:
            add("near_high_breakout", 20, top_n, 80, 3, 10, -1, tp2)

    for top_n in [1, 2, 5]:
        for tp2 in [4, 6, 8]:
            add("volatile_near_high", 50, top_n, 80, 8, 20, -1, tp2)

    for top_n in [1, 2, 5, 10]:
        for tp2 in [4, 6, 8]:
            add("ultra_momentum", 100, top_n, 80, 5, 999, -999, tp2, min_momentum_20_pct=60, min_volume_ratio=2)

    for top_n in [1, 2, 5]:
        for volume_ratio in [2, 3]:
            for tp2 in [6, 8]:
                add(
                    "extreme_momentum",
                    100,
                    top_n,
                    80,
                    5,
                    999,
                    -999,
                    tp2,
                    min_momentum_20_pct=80,
                    min_volume_ratio=volume_ratio,
                )

    for top_n in [2, 5]:
        for tp2 in [4, 6, 8]:
            add("momentum_volume", 80, top_n, 80, 3, 999, -999, tp2, min_momentum_20_pct=50, min_volume_ratio=3)

    for min_score in [70, 75]:
        for top_n in [2, 5, 10]:
            for momentum in [60, 80, 100]:
                for volume_ratio in [1.5, 2, 3]:
                    add(
                        "relaxed_extreme",
                        150,
                        top_n,
                        min_score,
                        5,
                        999,
                        -999,
                        6,
                        min_momentum_20_pct=momentum,
                        min_volume_ratio=volume_ratio,
                    )

    for holding_days in [3, 5, 7, 10]:
        for top_n in [2, 5, 10]:
            add(
                "holding_extreme",
                100,
                top_n,
                80,
                5,
                999,
                -999,
                6,
                min_momentum_20_pct=80,
                min_volume_ratio=2,
                max_holding_days=holding_days,
            )

    for holding_days in [2, 3]:
        for top_n in [2, 5, 10]:
            for entry_buffer_pct in [0.0, 0.001, 0.002, 0.005, 0.01]:
                add(
                    "entry_tuned_extreme",
                    100,
                    top_n,
                    80,
                    5,
                    999,
                    -999,
                    6,
                    min_momentum_20_pct=80,
                    min_volume_ratio=2,
                    entry_buffer_pct=entry_buffer_pct,
                    max_holding_days=holding_days,
                )

    for holding_days in [2, 3, 5]:
        for top_n in [2, 5, 10]:
            for pending_days in range(1, min(holding_days, 3) + 1):
                add(
                    "expiry_tuned_extreme",
                    100,
                    top_n,
                    80,
                    5,
                    999,
                    -999,
                    6,
                    min_momentum_20_pct=80,
                    min_volume_ratio=2,
                    entry_buffer_pct=0.0,
                    pending_entry_days=pending_days,
                    max_holding_days=holding_days,
                )

    for top_n in [3, 5]:
        for tp2 in [6, 7, 8]:
            add(
                "tp_tuned_extreme",
                100,
                top_n,
                80,
                5,
                999,
                -999,
                tp2,
                min_momentum_20_pct=80,
                min_volume_ratio=2,
                stop_atr_multiple=1.2,
                max_stop_pct=0.08,
                entry_buffer_pct=0.0,
                pending_entry_days=1,
                max_holding_days=3,
            )

    for top_n in [2, 5]:
        for momentum in [120, 130, 150, 180]:
            for momentum_5 in [None, 15, 25, 40, 60, 80]:
                for min_stop_pct in [0.01, 0.02, 0.03]:
                    for max_stop_pct in [0.02, 0.04, 0.06, 0.08]:
                        if min_stop_pct > max_stop_pct:
                            continue
                        add(
                            "quality_tuned_extreme",
                            100,
                            top_n,
                            80,
                            5,
                            999,
                            -999,
                            7,
                            min_momentum_20_pct=momentum,
                            min_momentum_5_pct=momentum_5,
                            min_volume_ratio=2,
                            max_gap_pct=80,
                            max_price=100,
                            stop_atr_multiple=1.2,
                            min_stop_pct=min_stop_pct,
                            max_stop_pct=max_stop_pct,
                            entry_buffer_pct=0.0,
                            pending_entry_days=1,
                            max_holding_days=3,
                        )

    for top_n in [2, 5, 10]:
        for tp2 in [6, 8, 10]:
            for stop_multiple in [1.2, 1.8, 2.4]:
                for max_stop_pct in [0.08, 0.12]:
                    add(
                        "risk_expanded_extreme",
                        100,
                        top_n,
                        80,
                        5,
                        999,
                        -999,
                        tp2,
                        min_momentum_20_pct=80,
                        min_volume_ratio=2,
                        stop_atr_multiple=stop_multiple,
                        max_stop_pct=max_stop_pct,
                    )

    return variants


def build_high_yield_variant_config(base_config: dict[str, Any], variant: HighYieldStrategyVariant) -> dict[str, Any]:
    config = deepcopy(base_config)
    config.setdefault("scoring", {})
    config.setdefault("pricing", {})
    scoring = config["scoring"]
    scoring["trigger_mode"] = "high_yield_breakout"
    scoring["top_n"] = variant.top_n
    scoring["min_score"] = variant.min_score
    scoring["watchlist_min_score"] = variant.min_score
    high_yield = scoring.setdefault("high_yield", {})
    high_yield.update(
        {
            "min_score": variant.min_score,
            "watchlist_min_score": variant.min_score,
            "top_n": variant.top_n,
            "candidate_pool_limit": variant.candidate_pool_limit,
            "min_atr_pct": variant.min_atr_pct,
            "max_atr_pct": variant.max_atr_pct,
            "min_distance_to_20d_high_pct": variant.min_distance_to_20d_high_pct,
            "primary_take_profit": "tp2",
        }
    )
    _set_optional_threshold(high_yield, "min_momentum_20_pct", variant.min_momentum_20_pct)
    _set_optional_threshold(high_yield, "min_distance_to_60d_high_pct", variant.min_distance_to_60d_high_pct)
    _set_optional_threshold(high_yield, "min_momentum_5_pct", variant.min_momentum_5_pct)
    _set_optional_threshold(high_yield, "min_volume_ratio", variant.min_volume_ratio)
    _set_optional_threshold(high_yield, "max_gap_pct", variant.max_gap_pct)
    _set_optional_threshold(high_yield, "max_price", variant.max_price)
    config["pricing"]["take_profit_2_atr_multiple"] = variant.take_profit_2_atr_multiple
    _set_optional_threshold(config["pricing"], "stop_atr_multiple", variant.stop_atr_multiple)
    _set_optional_threshold(config["pricing"], "min_stop_pct", variant.min_stop_pct)
    _set_optional_threshold(config["pricing"], "max_stop_pct", variant.max_stop_pct)
    if variant.entry_buffer_pct is not None:
        config["pricing"]["entry_buffer_pct"] = variant.entry_buffer_pct
    if variant.pending_entry_days is not None:
        config["pricing"]["pending_signal_expiry_trading_days"] = variant.pending_entry_days
    if variant.max_holding_days is not None:
        config["pricing"]["max_tracking_trading_days"] = variant.max_holding_days
    return config


def rank_strategy_search_results(
    results: list[dict[str, Any]],
    objective: str = "avg_all",
    min_signal_count: int = 30,
    limit: int = 10,
) -> list[dict[str, Any]]:
    filtered = [
        result
        for result in results
        if int(result.get("summary", {}).get("signal_count", 0)) >= int(min_signal_count)
    ]
    filtered.sort(key=lambda item: _result_sort_key(item, objective), reverse=True)
    return filtered[:limit]


def search_high_yield_strategies_from_daily_bars(
    daily_bars: pd.DataFrame,
    base_config: dict[str, Any],
    lookback_days: int = 365,
    sample_days: int = 40,
    max_holding_days: int = 10,
    objective: str = "avg_all",
    min_signal_count: int = 30,
    top_results: int = 10,
    variants: Iterable[HighYieldStrategyVariant] | None = None,
) -> dict[str, Any]:
    strategy_variants = list(variants) if variants is not None else default_high_yield_variants()
    max_variant_holding_days = max([max_holding_days, *[_variant_holding_days(variant, max_holding_days) for variant in strategy_variants]])
    prepared_max_holding_days = _future_buffer_days(base_config, max_variant_holding_days)
    prepared = prepare_validation_data(
        daily_bars,
        lookback_days=lookback_days,
        sample_days=sample_days,
        max_holding_days=prepared_max_holding_days,
    )
    raw_results = []
    for variant in strategy_variants:
        config = build_high_yield_variant_config(base_config, variant)
        variant_holding_days = _variant_holding_days(variant, max_holding_days)
        report = validate_prepared_signal_days(
            prepared,
            config,
            top_n=variant.top_n,
            max_holding_days=variant_holding_days,
        )
        raw_results.append(
            {
                "variant": variant.to_dict(),
                "summary": report.get("summary", {}),
                "rank_metrics": report.get("rank_metrics", []),
                "avg_candidates_per_day": report.get("avg_candidates_per_day", 0),
            }
        )

    ranked = rank_strategy_search_results(
        raw_results,
        objective=objective,
        min_signal_count=min_signal_count,
        limit=top_results,
    )
    return {
        "lookback_days": lookback_days,
        "sample_days_requested": sample_days,
        "sample_days_evaluated": len(prepared.eval_dates),
        "objective": objective,
        "min_signal_count": min_signal_count,
        "evaluated_variants": len(raw_results),
        "results": ranked,
        "reason": prepared.reason,
    }


def _set_optional_threshold(target: dict[str, Any], key: str, value: float | None) -> None:
    if value is None:
        target.pop(key, None)
    else:
        target[key] = value


def _variant_holding_days(variant: HighYieldStrategyVariant, default: int) -> int:
    return int(variant.max_holding_days) if variant.max_holding_days is not None else int(default)


def _result_sort_key(result: dict[str, Any], objective: str) -> tuple[float, float, float, int]:
    summary = result.get("summary", {})
    if objective == "compound":
        primary = _float_metric(summary.get("single_position_total_return_pct", 0))
    elif objective == "avg_entered":
        primary = _float_metric(summary.get("avg_return_pct", 0))
    elif objective == "profit_factor":
        primary = _float_metric(summary.get("profit_factor", 0))
    else:
        primary = _float_metric(summary.get("avg_return_pct_all_signals", 0))
    return (
        primary,
        _float_metric(summary.get("profit_factor", 0)),
        _float_metric(summary.get("avg_return_pct", 0)),
        int(summary.get("signal_count", 0)),
    )


def _float_metric(value: Any) -> float:
    if value == "inf":
        return float("inf")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if isinf(number):
        return float("inf")
    return number
