from __future__ import annotations

from .ai.deepseek import DeepSeekClient
from .config import Settings
from .data_providers.market_data import fetch_market_snapshots
from .data_providers.news import fetch_yahoo_news
from .data_providers.universe import load_us_stock_universe
from .models import MarketSnapshot, NewsBundle, Recommendation
from .recommender import RecommendationEngine


def collect_snapshots(
    settings: Settings,
    max_symbols_override: int | None = None,
    demo_mode: bool = False,
) -> list[MarketSnapshot]:
    universe = load_us_stock_universe()
    symbols = [item.symbol for item in universe]
    max_symbols = int(max_symbols_override or settings.universe.get("max_symbols_per_scan", 300))
    snapshots = fetch_market_snapshots(symbols, max_symbols=max_symbols)
    if not snapshots:
        if not demo_mode:
            return []
        snapshots = _demo_snapshots()
    return snapshots


def build_recommendations_from_snapshots(
    settings: Settings,
    session: str,
    snapshots: list[MarketSnapshot],
) -> list[Recommendation]:
    if not snapshots:
        return []

    pre_engine = RecommendationEngine(
        {
            "universe": settings.universe,
            "scoring": {**settings.scoring, "min_score": 0, "top_n": min(20, len(snapshots))},
            "pricing": settings.pricing,
        }
    )
    preliminary = pre_engine.recommend(snapshots, {}, session)
    candidate_symbols = [rec.symbol for rec in preliminary[:20]]
    news_by_symbol: dict[str, NewsBundle] = {}
    ai_client = DeepSeekClient(settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model)
    snapshot_by_symbol = {snapshot.symbol: snapshot for snapshot in snapshots}
    for symbol in candidate_symbols:
        bundle = fetch_yahoo_news(symbol)
        ai_score = ai_client.score_event(symbol, bundle.headlines)
        bundle.summary = ai_score.summary
        bundle.risk_notes.extend(ai_score.risk_notes)
        news_by_symbol[symbol] = bundle
        if symbol in snapshot_by_symbol:
            snapshot_by_symbol[symbol].ai_score = ai_score.score
            if ai_score.status != "available":
                snapshot_by_symbol[symbol].risk_flags.append(ai_score.summary)

    engine = RecommendationEngine(
        {"universe": settings.universe, "scoring": settings.scoring, "pricing": settings.pricing}
    )
    return engine.recommend(snapshots, news_by_symbol, session)


def run_scan(
    settings: Settings,
    session: str,
    max_symbols_override: int | None = None,
    demo_mode: bool = False,
) -> list[Recommendation]:
    snapshots = collect_snapshots(settings, max_symbols_override, demo_mode)
    return build_recommendations_from_snapshots(settings, session, snapshots)


def _demo_snapshots():
    from .models import MarketSnapshot

    symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "AMZN", "GOOGL", "COIN", "PLTR"]
    return [
        MarketSnapshot(
            symbol=symbol,
            current_price=10 + idx,
            recent_high_15m=10.2 + idx,
            atr14=0.5 + idx * 0.03,
            avg_dollar_volume_20d=20000000 + idx * 1000000,
            rule_score=75 - idx * 0.8,
            ml_score=70 - idx * 0.5,
            ai_score=50,
            reasons=["演示数据：真实行情源不可用"],
            risk_flags=["演示模式"],
            data_quality="demo",
        )
        for idx, symbol in enumerate(symbols)
    ]
