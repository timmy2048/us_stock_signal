from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


VALID_SESSIONS = {"premarket", "regular", "afterhours"}


def now_in_timezone(timezone_name: str) -> datetime:
    return datetime.now(ZoneInfo(timezone_name))


def infer_us_session(now_market: datetime | None = None) -> str:
    market_now = now_market or now_in_timezone("America/New_York")
    current = market_now.time()
    if time(4, 0) <= current < time(9, 30):
        return "premarket"
    if time(9, 30) <= current < time(16, 0):
        return "regular"
    return "afterhours"


def validate_session(session: str) -> str:
    if session not in VALID_SESSIONS:
        raise ValueError(f"session must be one of {sorted(VALID_SESSIONS)}")
    return session

