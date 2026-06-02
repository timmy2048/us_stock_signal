import pandas as pd

from us_stock_signal.backtest import run_path_backtest


def test_backtest_uses_future_prices_after_entry_without_lookahead():
    prices = pd.DataFrame(
        {
            "close": [10.0, 10.1, 10.4, 10.9, 11.0],
            "high": [10.1, 10.2, 10.5, 11.0, 11.1],
            "low": [9.9, 10.0, 10.3, 10.8, 10.9],
        }
    )

    result = run_path_backtest(
        prices,
        entry_price_high=10.2,
        stop_loss=9.5,
        take_profit_1=10.8,
        max_bars=4,
        slippage_bps=0,
        commission=0,
    )

    assert result.exit_reason == "TAKE_PROFIT_1"
    assert result.return_pct > 0


def test_backtest_can_label_alternate_take_profit_target():
    prices = pd.DataFrame(
        {
            "close": [10.0, 10.1, 10.4],
            "high": [10.1, 10.2, 12.1],
            "low": [9.9, 10.0, 10.3],
        }
    )

    result = run_path_backtest(
        prices,
        entry_price_high=10.2,
        stop_loss=9.5,
        take_profit_1=12.0,
        max_bars=2,
        slippage_bps=0,
        commission=0,
        take_profit_label="TAKE_PROFIT_2",
    )

    assert result.exit_reason == "TAKE_PROFIT_2"


def test_backtest_expires_entry_before_max_holding_window():
    prices = pd.DataFrame(
        {
            "close": [10.0, 10.0, 10.0, 10.5, 11.5],
            "high": [10.0, 10.1, 10.1, 10.6, 11.6],
            "low": [9.9, 9.9, 9.9, 10.4, 11.4],
        }
    )

    result = run_path_backtest(
        prices,
        entry_price_high=10.5,
        stop_loss=9.5,
        take_profit_1=11.5,
        max_bars=4,
        entry_expiry_bars=2,
        slippage_bps=0,
        commission=0,
    )

    assert result.exit_reason == "NO_ENTRY"
    assert result.entry_bar_index == 0
    assert result.exit_bar_index == 2


def test_backtest_keeps_holding_after_entry_window_when_entry_triggered():
    prices = pd.DataFrame(
        {
            "close": [10.0, 10.0, 10.6, 10.8, 11.5],
            "high": [10.0, 10.1, 10.6, 10.9, 11.6],
            "low": [9.9, 9.9, 10.4, 10.7, 11.4],
        }
    )

    result = run_path_backtest(
        prices,
        entry_price_high=10.5,
        stop_loss=9.5,
        take_profit_1=11.5,
        max_bars=4,
        entry_expiry_bars=2,
        slippage_bps=0,
        commission=0,
    )

    assert result.exit_reason == "TAKE_PROFIT_1"
    assert result.entry_bar_index == 2
    assert result.exit_bar_index == 4
