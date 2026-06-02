from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .execution_policy import config_primary_take_profit
from .models import MarketSnapshot, NewsBundle, Recommendation
from .pricing import build_trade_plan


def signal_status_for_session(session: str) -> str:
    if session == "regular":
        return "ACTIONABLE"
    if session == "premarket":
        return "CONFIRMING"
    return "WATCHLIST"


class RecommendationEngine:
    def __init__(self, config: dict) -> None:
        self.config = config

    @classmethod
    def default_for_tests(cls) -> "RecommendationEngine":
        return cls(
            {
                "universe": {"min_price": 2.0, "min_avg_dollar_volume_20d": 10000000},
                "scoring": {"rule_weight": 0.6, "ml_weight": 0.25, "ai_weight": 0.15, "min_score": 50, "top_n": 10},
                "pricing": {
                    "stop_atr_multiple": 1.2,
                    "take_profit_1_atr_multiple": 1.8,
                    "take_profit_2_atr_multiple": 3.0,
                    "min_stop_pct": 0.03,
                    "max_stop_pct": 0.08,
                    "entry_buffer_pct": 0.002,
                    "max_chase_pct": 0.005,
                    "pending_signal_expiry_trading_days": 2,
                },
            }
        )

    def recommend(
        self,
        snapshots: list[MarketSnapshot],
        news_by_symbol: dict[str, NewsBundle],
        session: str,
        limit: int | None = None,
    ) -> list[Recommendation]:
        candidates: list[tuple[tuple[float, ...], Recommendation, MarketSnapshot]] = []
        for snapshot in snapshots:
            if not self._passes_hard_filters(snapshot):
                continue
            try:
                plan = build_trade_plan(
                    snapshot.current_price,
                    snapshot.recent_high_15m,
                    snapshot.atr14,
                    self.config.get("pricing", {}),
                )
            except ValueError:
                continue

            score = self._combined_score(snapshot)
            signal_status = signal_status_for_session(session)
            if score < self._min_score(signal_status):
                continue

            news = news_by_symbol.get(snapshot.symbol)
            risk_flags = list(snapshot.risk_flags)
            reasons = list(snapshot.reasons)
            if news and news.summary:
                reasons.append(news.summary)
            if news:
                risk_flags.extend(news.risk_notes)

            recommendation = Recommendation(
                id=f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{snapshot.symbol}",
                symbol=snapshot.symbol,
                rank=0,
                score=score,
                session=session,
                current_price=round(snapshot.current_price, 2),
                entry_price_low=plan.entry_price_low,
                entry_price_high=plan.entry_price_high,
                max_chase_price=plan.max_chase_price,
                stop_loss=plan.stop_loss,
                take_profit_1=plan.take_profit_1,
                take_profit_2=plan.take_profit_2,
                expiry=plan.expiry,
                invalidation_price=plan.invalidation_price,
                reasons=reasons[:6],
                risk_flags=risk_flags[:6],
                data_quality=snapshot.data_quality,
                ai_status="available" if snapshot.ai_score != 50 else "neutral_or_missing",
                primary_take_profit=config_primary_take_profit(self.config),
                signal_status=signal_status,
            )
            candidates.append((self._sort_key(score, snapshot, plan), recommendation, snapshot))

        candidates.sort(key=lambda item: item[0], reverse=True)
        candidates = self._apply_trigger_mode(candidates)
        recommendations = [rec for _, rec, _ in candidates[: self._top_n(limit)]]
        for rank, rec in enumerate(recommendations, start=1):
            rec.rank = rank
        return recommendations

    def _passes_hard_filters(self, snapshot: MarketSnapshot) -> bool:
        universe = self.config.get("universe", {})
        return (
            snapshot.current_price >= float(universe.get("min_price", 2.0))
            and snapshot.avg_dollar_volume_20d >= float(universe.get("min_avg_dollar_volume_20d", 10000000))
            and snapshot.atr14 > 0
            and snapshot.recent_high_15m > 0
        )

    def _combined_score(self, snapshot: MarketSnapshot) -> float:
        scoring = self.config.get("scoring", {})
        score = (
            snapshot.rule_score * float(scoring.get("rule_weight", 0.6))
            + snapshot.ml_score * float(scoring.get("ml_weight", 0.25))
            + snapshot.ai_score * float(scoring.get("ai_weight", 0.15))
        )
        return round(max(0.0, min(100.0, score)), 2)

    def _sort_key(self, score: float, snapshot: MarketSnapshot, plan: Any) -> tuple[float, ...]:
        risk = max(plan.entry_price_high - plan.stop_loss, 0.000001)
        reward = max(plan.take_profit_1 - plan.entry_price_high, 0.0)
        reward_risk = reward / risk
        reward_pct = reward / plan.entry_price_high if plan.entry_price_high else 0.0
        risk_pct = risk / plan.entry_price_high if plan.entry_price_high else 1.0
        return (
            score,
            reward_risk,
            reward_pct,
            snapshot.avg_dollar_volume_20d,
            snapshot.rule_score,
            snapshot.ml_score,
            -risk_pct,
        )

    def _apply_trigger_mode(
        self,
        candidates: list[tuple[tuple[float, ...], Recommendation, MarketSnapshot]],
    ) -> list[tuple[tuple[float, ...], Recommendation, MarketSnapshot]]:
        scoring = self.config.get("scoring", {})
        if scoring.get("trigger_mode") != "high_yield_breakout":
            return candidates

        high_yield = scoring.get("high_yield", {})
        pool_limit = int(high_yield.get("candidate_pool_limit", 20))
        filtered = []
        for item in candidates[:pool_limit]:
            _, rec, snapshot = item
            if not self._passes_high_yield_breakout(snapshot):
                continue
            rec.reasons = [self._high_yield_reason(), *rec.reasons][:6]
            filtered.append(item)
        return filtered

    def _passes_high_yield_breakout(self, snapshot: MarketSnapshot) -> bool:
        high_yield = self.config.get("scoring", {}).get("high_yield", {})
        extra = snapshot.extra or {}
        atr_pct = float(extra.get("atr_pct", -1))
        distance_to_high = float(extra.get("distance_to_20d_high_pct", -999))
        distance_to_60d_high = float(extra.get("distance_to_60d_high_pct", -999))
        if atr_pct < float(high_yield.get("min_atr_pct", 3.0)):
            return False
        if atr_pct > float(high_yield.get("max_atr_pct", 10.0)):
            return False
        if distance_to_high < float(high_yield.get("min_distance_to_20d_high_pct", -1.0)):
            return False
        if "min_distance_to_60d_high_pct" in high_yield:
            if distance_to_60d_high < float(high_yield["min_distance_to_60d_high_pct"]):
                return False
        if "min_momentum_20_pct" in high_yield:
            momentum_20_pct = float(extra.get("momentum_20_pct", -999))
            if momentum_20_pct < float(high_yield["min_momentum_20_pct"]):
                return False
        if "min_momentum_5_pct" in high_yield:
            momentum_5_pct = float(extra.get("momentum_5_pct", -999))
            if momentum_5_pct < float(high_yield["min_momentum_5_pct"]):
                return False
        if "min_volume_ratio" in high_yield:
            volume_ratio = float(extra.get("volume_ratio", 0))
            if volume_ratio < float(high_yield["min_volume_ratio"]):
                return False
        if "max_gap_pct" in high_yield:
            gap_pct = float(extra.get("gap_pct", 999))
            if gap_pct > float(high_yield["max_gap_pct"]):
                return False
        if "max_price" in high_yield:
            if snapshot.current_price > float(high_yield["max_price"]):
                return False
        return True

    def _high_yield_reason(self) -> str:
        high_yield = self.config.get("scoring", {}).get("high_yield", {})
        min_atr_pct = float(high_yield.get("min_atr_pct", 3.0))
        max_atr_pct = float(high_yield.get("max_atr_pct", 10.0))
        if max_atr_pct >= 100:
            parts = [f"ATR >= {min_atr_pct:g}%"]
        else:
            parts = [f"ATR {min_atr_pct:g}%-{max_atr_pct:g}%"]
        if "min_distance_to_20d_high_pct" in high_yield:
            min_distance = float(high_yield["min_distance_to_20d_high_pct"])
            if min_distance > -100:
                parts.append(f"20d high distance >= {min_distance:g}%")
        if "min_distance_to_60d_high_pct" in high_yield:
            min_distance_60d = float(high_yield["min_distance_to_60d_high_pct"])
            if min_distance_60d > -100:
                parts.append(f"60d high distance >= {min_distance_60d:g}%")
        if "min_momentum_20_pct" in high_yield:
            parts.append(f"20d momentum >= {float(high_yield['min_momentum_20_pct']):g}%")
        if "min_momentum_5_pct" in high_yield:
            parts.append(f"5d momentum >= {float(high_yield['min_momentum_5_pct']):g}%")
        if "min_volume_ratio" in high_yield:
            parts.append(f"volume ratio >= {float(high_yield['min_volume_ratio']):g}x")
        if "max_gap_pct" in high_yield:
            parts.append(f"gap <= {float(high_yield['max_gap_pct']):g}%")
        if "max_price" in high_yield:
            parts.append(f"price <= {float(high_yield['max_price']):g}")
        return "\u9ad8\u6536\u76ca\u89e6\u53d1(high yield): " + ", ".join(parts)

    def _top_n(self, limit: int | None = None) -> int:
        if limit is not None:
            return max(int(limit), 0)
        scoring = self.config.get("scoring", {})
        if scoring.get("trigger_mode") == "high_yield_breakout":
            return int(scoring.get("high_yield", {}).get("top_n", scoring.get("top_n", 10)))
        return int(scoring.get("top_n", 10))

    def _min_score(self, signal_status: str) -> float:
        scoring = self.config.get("scoring", {})
        if scoring.get("trigger_mode") == "high_yield_breakout":
            high_yield = scoring.get("high_yield", {})
            if signal_status in {"WATCHLIST", "CONFIRMING"}:
                return float(high_yield.get("watchlist_min_score", high_yield.get("min_score", 50)))
            return float(high_yield.get("min_score", 50))
        if signal_status in {"WATCHLIST", "CONFIRMING"}:
            return float(scoring.get("watchlist_min_score", 50))
        return float(scoring.get("min_score", 60))
