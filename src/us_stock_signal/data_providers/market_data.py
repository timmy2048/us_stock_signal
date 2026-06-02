from __future__ import annotations

import pandas as pd

from us_stock_signal.features.technical import average_true_range, score_technical_snapshot, technical_snapshot_features
from us_stock_signal.models import MarketSnapshot
from us_stock_signal.models_ml.simple_model import heuristic_ml_score


def fetch_market_snapshots(symbols: list[str], max_symbols: int = 50) -> list[MarketSnapshot]:
    try:
        import yfinance as yf
    except Exception:
        return []

    snapshots: list[MarketSnapshot] = []
    for symbol in symbols[:max_symbols]:
        try:
            ticker = yf.Ticker(symbol)
            daily = ticker.history(period="90d", interval="1d", auto_adjust=True)
            intraday = ticker.history(period="5d", interval="15m", prepost=True, auto_adjust=True)
            snapshot = _snapshot_from_frames(symbol, daily, intraday)
            if snapshot:
                snapshots.append(snapshot)
        except Exception:
            continue
    return snapshots


def _snapshot_from_frames(symbol: str, daily: pd.DataFrame, intraday: pd.DataFrame) -> MarketSnapshot | None:
    if daily.empty or len(daily) < 25:
        return None
    current_price = _last_valid(intraday["Close"]) if not intraday.empty and "Close" in intraday else _last_valid(daily["Close"])
    if current_price <= 0:
        return None
    recent_high = (
        float(intraday["High"].tail(8).max())
        if not intraday.empty and "High" in intraday and not intraday["High"].tail(8).isna().all()
        else current_price
    )
    atr = average_true_range(
        daily["High"].tolist(),
        daily["Low"].tolist(),
        daily["Close"].tolist(),
        period=14,
    )
    avg_volume = float(daily["Volume"].tail(20).mean()) if "Volume" in daily else 0.0
    avg_dollar_volume = avg_volume * current_price
    rule_score, reasons, risks = score_technical_snapshot(daily["Close"].tolist(), daily["Volume"].tolist(), current_price)
    atr_pct = atr / current_price if current_price else 0.0
    vol20 = float(daily["Volume"].tail(20).mean()) if "Volume" in daily else 0.0
    volume_ratio = float(daily["Volume"].iloc[-1]) / vol20 if vol20 else 1.0
    ml_score = heuristic_ml_score(rule_score, atr_pct, volume_ratio)
    extra = technical_snapshot_features(
        daily["Close"].tolist(),
        daily["High"].tolist(),
        daily["Volume"].tolist(),
        current_price,
        opens=daily["Open"].tolist() if "Open" in daily else None,
        lows=daily["Low"].tolist() if "Low" in daily else None,
    )
    extra["atr_pct"] = atr_pct * 100
    return MarketSnapshot(
        symbol=symbol,
        current_price=float(current_price),
        recent_high_15m=float(max(recent_high, current_price)),
        atr14=float(atr),
        avg_dollar_volume_20d=float(avg_dollar_volume),
        rule_score=rule_score,
        ml_score=ml_score,
        ai_score=50,
        reasons=reasons,
        risk_flags=risks,
        data_quality="free_yfinance",
        extra=extra,
    )


def fetch_latest_prices(symbols: list[str]) -> dict[str, float]:
    try:
        import yfinance as yf
    except Exception:
        return {}
    result: dict[str, float] = {}
    for symbol in symbols:
        try:
            hist = yf.Ticker(symbol).history(period="1d", interval="1m", prepost=True)
            if hist.empty:
                hist = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=True)
            if not hist.empty and "Close" in hist:
                result[symbol] = _last_valid(hist["Close"])
        except Exception:
            continue
    return result


def _last_valid(series) -> float:
    values = series.dropna()
    return float(values.iloc[-1]) if len(values) else 0.0
