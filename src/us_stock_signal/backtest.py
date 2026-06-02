from __future__ import annotations

from .models import BacktestTradeResult


def run_path_backtest(
    prices,
    entry_price_high: float,
    stop_loss: float,
    take_profit_1: float,
    max_bars: int,
    slippage_bps: float,
    commission: float,
    take_profit_label: str = "TAKE_PROFIT_1",
    entry_expiry_bars: int | None = None,
) -> BacktestTradeResult:
    if len(prices) < 2:
        raise ValueError("prices must contain at least two rows")

    last_bar_index = min(len(prices) - 1, int(max_bars))
    entry_deadline_index = min(
        last_bar_index,
        int(max_bars) if entry_expiry_bars is None else max(1, int(entry_expiry_bars)),
    )
    entered = False
    entry_price = 0.0
    entry_bar_index = 0
    bars_held = 0
    rows = prices.reset_index(drop=True)
    for idx in range(1, last_bar_index + 1):
        row = rows.iloc[idx]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        if not entered and idx <= entry_deadline_index and high >= entry_price_high:
            entered = True
            entry_price = entry_price_high * (1 + slippage_bps / 10000)
            entry_bar_index = idx
            bars_held = 0
        if not entered:
            continue
        bars_held += 1
        if low <= stop_loss:
            exit_price = stop_loss * (1 - slippage_bps / 10000)
            return _result(entry_price, exit_price, "STOP_LOSS", bars_held, commission, entry_bar_index, idx)
        if high >= take_profit_1:
            exit_price = take_profit_1 * (1 - slippage_bps / 10000)
            return _result(entry_price, exit_price, take_profit_label, bars_held, commission, entry_bar_index, idx)
        if idx == last_bar_index:
            exit_price = close * (1 - slippage_bps / 10000)
            return _result(entry_price, exit_price, "TIME_EXIT", bars_held, commission, entry_bar_index, idx)
    if not entered:
        close = float(rows.iloc[entry_deadline_index]["close"])
        return BacktestTradeResult(
            entry_price=0.0,
            exit_price=close,
            exit_reason="NO_ENTRY",
            bars_held=0,
            return_pct=0.0,
            entry_bar_index=0,
            exit_bar_index=entry_deadline_index,
        )
    return _result(entry_price, float(rows.iloc[-1]["close"]), "TIME_EXIT", bars_held, commission, entry_bar_index, len(rows) - 1)


def _result(
    entry_price: float,
    exit_price: float,
    exit_reason: str,
    bars_held: int,
    commission: float,
    entry_bar_index: int,
    exit_bar_index: int,
) -> BacktestTradeResult:
    net_exit = max(0.0, exit_price - commission)
    return BacktestTradeResult(
        entry_price=round(entry_price, 4),
        exit_price=round(exit_price, 4),
        exit_reason=exit_reason,
        bars_held=bars_held,
        return_pct=round((net_exit - entry_price) / entry_price * 100, 4) if entry_price else 0.0,
        entry_bar_index=entry_bar_index,
        exit_bar_index=exit_bar_index,
    )
