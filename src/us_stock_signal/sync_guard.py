from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class DailySyncWindowDecision:
    allowed: bool
    window: str
    message: str
    market_time: datetime


def daily_sync_window_decision(
    schedule: dict[str, Any],
    market_timezone: str = "America/New_York",
    now: datetime | None = None,
    force: bool = False,
) -> DailySyncWindowDecision:
    market_now = _market_now(market_timezone, now)
    if force:
        return DailySyncWindowDecision(True, "forced", "forced by --force", market_now)
    if schedule.get("daily_sync_guard_enabled", True) is False:
        return DailySyncWindowDecision(True, "disabled", "daily sync guard disabled", market_now)

    after_close = _parse_hhmm(str(schedule.get("daily_sync_after", "20:30")))
    retry_after = _parse_hhmm(str(schedule.get("premarket_retry_after", "08:00")))
    retry_before = _parse_hhmm(str(schedule.get("premarket_retry_before", "09:20")))
    current = market_now.time().replace(second=0, microsecond=0)
    is_weekday = market_now.weekday() < 5

    if is_weekday and current >= after_close:
        return DailySyncWindowDecision(
            True,
            "after_close",
            f"US market daily bars are expected to be stable after {after_close:%H:%M} ET",
            market_now,
        )
    if is_weekday and retry_after <= current < retry_before:
        return DailySyncWindowDecision(
            True,
            "premarket_retry",
            f"premarket retry window {retry_after:%H:%M}-{retry_before:%H:%M} ET",
            market_now,
        )

    return DailySyncWindowDecision(
        False,
        "blocked",
        (
            f"US daily-bar sync is allowed only after {after_close:%H:%M} ET "
            f"or during {retry_after:%H:%M}-{retry_before:%H:%M} ET premarket retry; "
            f"current market time is {market_now:%Y-%m-%d %H:%M %Z}"
        ),
        market_now,
    )


def _market_now(market_timezone: str, now: datetime | None) -> datetime:
    zone = ZoneInfo(market_timezone)
    if now is None:
        return datetime.now(zone)
    if now.tzinfo is None:
        return now.replace(tzinfo=zone)
    return now.astimezone(zone)


def _parse_hhmm(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(int(hour_text), int(minute_text))
