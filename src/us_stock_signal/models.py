from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class TradePlan:
    entry_price_low: float
    entry_price_high: float
    max_chase_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    invalidation_price: float
    expiry: str


@dataclass(slots=True)
class MarketSnapshot:
    symbol: str
    current_price: float
    recent_high_15m: float
    atr14: float
    avg_dollar_volume_20d: float
    rule_score: float
    ml_score: float
    ai_score: float
    reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    data_quality: str = "unknown"
    sector: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NewsBundle:
    symbol: str
    headlines: list[str]
    summary: str = ""
    risk_notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Recommendation:
    id: str
    symbol: str
    rank: int
    score: float
    session: str
    current_price: float
    entry_price_low: float
    entry_price_high: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    expiry: str
    invalidation_price: float
    reasons: list[str]
    risk_flags: list[str]
    data_quality: str
    ai_status: str
    max_chase_price: float = 0.0
    primary_take_profit: str = ""
    direction: str = "LONG"
    signal_status: str = "ACTIONABLE"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


@dataclass(slots=True)
class SignalEvent:
    recommendation_id: str
    symbol: str
    event_type: str
    price: float
    timestamp: datetime
    message: str


@dataclass(slots=True)
class TrackedSignal:
    recommendation: Recommendation
    created_at: datetime
    status: str = "PENDING_ENTRY"
    events: list[SignalEvent] = field(default_factory=list)


@dataclass(slots=True)
class AIEventScore:
    score: float
    status: str
    summary: str
    risk_notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProviderResult:
    ok: bool
    data: Any = None
    error: str = ""
    data_quality: str = "unknown"


@dataclass(slots=True)
class BacktestTradeResult:
    entry_price: float
    exit_price: float
    exit_reason: str
    bars_held: int
    return_pct: float
    entry_bar_index: int = 0
    exit_bar_index: int = 0


@dataclass(slots=True)
class MarkdownMessage:
    title: str
    text: str
