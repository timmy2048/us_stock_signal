from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Mapping

import pandas as pd
import requests


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_CHART_RANGES = {"5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}


def yahoo_chart_symbol(symbol: str) -> str:
    return symbol.upper().replace(".", "-")


def fetch_yahoo_chart_daily_bars(
    symbols: list[str],
    period: str = "1y",
    max_workers: int = 12,
) -> dict[str, pd.DataFrame]:
    range_value = period if period in YAHOO_CHART_RANGES else "1y"
    frames: dict[str, pd.DataFrame] = {}
    if not symbols:
        return frames
    if max_workers <= 1 or len(symbols) == 1:
        for symbol in symbols:
            frame = _fetch_one_yahoo_chart_daily_bar(symbol, range_value)
            if not frame.empty:
                frames[symbol] = frame
        return frames

    workers = max(1, min(max_workers, len(symbols)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_fetch_one_yahoo_chart_daily_bar, symbol, range_value): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                frame = future.result()
            except Exception:
                continue
            if not frame.empty:
                frames[symbol] = frame
    return frames


def _fetch_one_yahoo_chart_daily_bar(symbol: str, range_value: str) -> pd.DataFrame:
    yahoo_symbol = yahoo_chart_symbol(symbol)
    try:
        response = requests.get(
            YAHOO_CHART_URL.format(symbol=yahoo_symbol),
            params={"range": range_value, "interval": "1d", "includePrePost": "false"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        if response.status_code != 200:
            return _empty_frame()
        return frame_from_yahoo_chart_payload(response.json())
    except Exception:
        return _empty_frame()


def frame_from_yahoo_chart_payload(payload: Mapping[str, Any]) -> pd.DataFrame:
    chart = payload.get("chart")
    if not isinstance(chart, Mapping) or chart.get("error"):
        return _empty_frame()
    results = chart.get("result")
    if not results:
        return _empty_frame()
    result = results[0]
    if not isinstance(result, Mapping):
        return _empty_frame()
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quotes = indicators.get("quote") if isinstance(indicators, Mapping) else None
    if not timestamps or not quotes:
        return _empty_frame()
    quote = quotes[0]
    if not isinstance(quote, Mapping):
        return _empty_frame()

    rows = []
    row_timestamps = []
    for index, timestamp in enumerate(timestamps):
        close = _list_value(quote, "close", index)
        if close is None or pd.isna(close):
            continue
        row_timestamps.append(timestamp)
        volume = _list_value(quote, "volume", index)
        rows.append(
            {
                "Open": _float_or_none(_list_value(quote, "open", index)),
                "High": _float_or_none(_list_value(quote, "high", index)),
                "Low": _float_or_none(_list_value(quote, "low", index)),
                "Close": float(close),
                "Volume": int(volume) if volume is not None and not pd.isna(volume) else 0,
            }
        )
    if not rows:
        return _empty_frame()
    frame = pd.DataFrame(rows)
    frame.index = pd.to_datetime(row_timestamps, unit="s", utc=True).tz_convert("America/New_York").tz_localize(None)
    return frame


def _list_value(quote: Mapping[str, Any], key: str, index: int) -> Any:
    values = quote.get(key) or []
    if index >= len(values):
        return None
    return values[index]


def _float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
