from __future__ import annotations

from typing import Any

from .models import Recommendation

_TP2_ALIASES = {"tp2", "take_profit_2"}


def normalize_take_profit_target(target: str | None) -> str:
    normalized = str(target or "tp1").strip().lower()
    return "tp2" if normalized in _TP2_ALIASES else "tp1"


def config_primary_take_profit(config: dict[str, Any]) -> str:
    scoring = config.get("scoring", {})
    high_yield = scoring.get("high_yield", {})
    configured = high_yield.get("primary_take_profit", scoring.get("primary_take_profit", "tp1"))
    return normalize_take_profit_target(configured)


def recommendation_primary_take_profit_target(
    recommendation: Recommendation,
    fallback: str | None = None,
) -> str:
    configured = recommendation.primary_take_profit or fallback
    return normalize_take_profit_target(configured)


def take_profit_label(target: str | None) -> str:
    return "TP2" if normalize_take_profit_target(target) == "tp2" else "TP1"


def take_profit_event_type(target: str | None) -> str:
    return "TAKE_PROFIT_2" if normalize_take_profit_target(target) == "tp2" else "TAKE_PROFIT_1"


def recommendation_primary_take_profit_price(
    recommendation: Recommendation,
    fallback: str | None = None,
) -> float:
    target = recommendation_primary_take_profit_target(recommendation, fallback)
    return recommendation.take_profit_2 if target == "tp2" else recommendation.take_profit_1


def recommendation_primary_take_profit_label(
    recommendation: Recommendation,
    fallback: str | None = None,
) -> str:
    return take_profit_label(recommendation_primary_take_profit_target(recommendation, fallback))


def recommendation_secondary_take_profit_price(
    recommendation: Recommendation,
    fallback: str | None = None,
) -> float:
    target = recommendation_primary_take_profit_target(recommendation, fallback)
    return recommendation.take_profit_1 if target == "tp2" else recommendation.take_profit_2
