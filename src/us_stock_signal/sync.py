from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

import pandas as pd

from .data_providers.yahoo_chart import fetch_yahoo_chart_daily_bars
from .data_providers.universe import UniverseSymbol, load_us_stock_universe
from .repository import MarketRepository


UniverseProvider = Callable[[], list[UniverseSymbol]]
DailyProvider = Callable[[list[str], str], dict[str, pd.DataFrame]]


def sync_universe_from_provider(
    repo: MarketRepository,
    provider: UniverseProvider = load_us_stock_universe,
) -> int:
    started_at = datetime.now(timezone.utc)
    try:
        symbols = provider()
        count = repo.upsert_symbols(symbols)
        repo.record_sync_run("universe", "success", count, "universe synced", started_at)
        return count
    except Exception as exc:
        repo.record_sync_run("universe", "failed", 0, str(exc), started_at)
        raise


def sync_daily_bars_from_provider(
    repo: MarketRepository,
    symbols: list[str],
    provider: DailyProvider | None = None,
    fallback_provider: DailyProvider | None = fetch_yahoo_chart_daily_bars,
    period: str = "1y",
    batch_size: int = 50,
    batch_delay_seconds: float = 0.0,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> int:
    if batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")
    if batch_delay_seconds < 0:
        raise ValueError("batch_delay_seconds must be non-negative")

    started_at = datetime.now(timezone.utc)
    provider = provider or fetch_yfinance_daily_bars
    total = 0
    failed_batches: list[str] = []
    try:
        for start in range(0, len(symbols), batch_size):
            batch = symbols[start : start + batch_size]
            frames: dict[str, pd.DataFrame] = {}
            fallback_attempted_symbols: set[str] = set()
            try:
                frames = provider(batch, period) or {}
            except Exception as exc:
                failed_batches.append(f"{batch[0]}-{batch[-1]} primary failed: {exc}")
                if fallback_provider:
                    fallback_attempted_symbols.update(batch)
                    try:
                        frames = fallback_provider(batch, period) or {}
                    except Exception as fallback_exc:
                        failed_batches.append(f"{batch[0]}-{batch[-1]} fallback failed: {fallback_exc}")
                        frames = {}

            missing_symbols = [
                symbol
                for symbol in batch
                if symbol not in fallback_attempted_symbols and (symbol not in frames or frames[symbol].empty)
            ]
            if fallback_provider and missing_symbols:
                fallback_attempted_symbols.update(missing_symbols)
                try:
                    fallback_frames = fallback_provider(missing_symbols, period) or {}
                    for symbol, frame in fallback_frames.items():
                        if symbol in missing_symbols and not frame.empty:
                            frames[symbol] = frame
                except Exception as exc:
                    failed_batches.append(f"{missing_symbols[0]}-{missing_symbols[-1]} fallback failed: {exc}")
            rows = []
            for symbol, frame in frames.items():
                rows.extend(_daily_rows_from_frame(symbol, frame))
            total += repo.upsert_daily_bars(rows)
            if progress_callback:
                progress_callback(min(start + len(batch), len(symbols)), len(symbols), total)
            if batch_delay_seconds and start + batch_size < len(symbols):
                time.sleep(batch_delay_seconds)

        status = "partial" if failed_batches else "success"
        message = f"synced {len(symbols)} symbols"
        if failed_batches:
            message += f"; failed batches: {len(failed_batches)}; " + " | ".join(failed_batches[:5])
        repo.record_sync_run("daily_bars", status, total, message, started_at)
        return total
    except Exception as exc:
        repo.record_sync_run("daily_bars", "failed", total, str(exc), started_at)
        raise


def fetch_yfinance_daily_bars(symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("yfinance is required for daily sync") from exc
    result: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            frame = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=False)
            if not frame.empty:
                result[symbol] = frame
        except Exception:
            continue
    return result


def _daily_rows_from_frame(symbol: str, frame: pd.DataFrame) -> list[dict]:
    rows = []
    if frame.empty:
        return rows
    for index, row in frame.iterrows():
        if any(column not in frame.columns for column in ["Open", "High", "Low", "Close", "Volume"]):
            continue
        if pd.isna(row["Close"]):
            continue
        rows.append(
            {
                "symbol": symbol,
                "bar_date": pd.Timestamp(index).date(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
            }
        )
    return rows
