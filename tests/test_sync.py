import pandas as pd
import pytest

from us_stock_signal.data_providers.universe import UniverseSymbol
from us_stock_signal.repository import MarketRepository
from us_stock_signal.sync import sync_daily_bars_from_provider, sync_universe_from_provider


def test_sync_universe_from_provider_upserts_all_symbols(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")

    count = sync_universe_from_provider(
        repo,
        provider=lambda: [
            UniverseSymbol(symbol="AAPL", name="Apple", exchange="NASDAQ"),
            UniverseSymbol(symbol="MSFT", name="Microsoft", exchange="NASDAQ"),
        ],
    )

    assert count == 2
    assert repo.count_rows("symbols") == 2


def test_sync_daily_bars_from_provider_upserts_history(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")
    repo.upsert_symbols([UniverseSymbol(symbol="AAPL", name="Apple", exchange="NASDAQ")])

    def provider(symbols, period):
        assert symbols == ["AAPL"]
        assert period == "1y"
        return {
            "AAPL": pd.DataFrame(
                {
                    "Open": [10.0],
                    "High": [11.0],
                    "Low": [9.5],
                    "Close": [10.5],
                    "Volume": [1000],
                },
                index=pd.to_datetime(["2026-01-02"]),
            )
        }

    count = sync_daily_bars_from_provider(repo, ["AAPL"], provider=provider, period="1y")

    assert count == 1
    assert repo.count_rows("daily_bars") == 1


def test_sync_daily_bars_uses_fallback_for_missing_primary_symbols(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")
    repo.upsert_symbols(
        [
            UniverseSymbol(symbol="AAPL", name="Apple", exchange="NASDAQ"),
            UniverseSymbol(symbol="MSFT", name="Microsoft", exchange="NASDAQ"),
        ]
    )

    def primary_provider(symbols, period):
        return {
            "AAPL": pd.DataFrame(
                {
                    "Open": [10.0],
                    "High": [11.0],
                    "Low": [9.5],
                    "Close": [10.5],
                    "Volume": [1000],
                },
                index=pd.to_datetime(["2026-01-02"]),
            )
        }

    def fallback_provider(symbols, period):
        assert symbols == ["MSFT"]
        assert period == "1mo"
        return {
            "MSFT": pd.DataFrame(
                {
                    "Open": [20.0],
                    "High": [21.0],
                    "Low": [19.5],
                    "Close": [20.5],
                    "Volume": [2000],
                },
                index=pd.to_datetime(["2026-01-02"]),
            )
        }

    count = sync_daily_bars_from_provider(
        repo,
        ["AAPL", "MSFT"],
        provider=primary_provider,
        fallback_provider=fallback_provider,
        period="1mo",
    )

    assert count == 2
    assert repo.count_rows("daily_bars") == 2


def test_sync_daily_bars_reports_progress_by_batch(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")
    events = []

    def provider(symbols, period):
        return {
            symbol: pd.DataFrame(
                {
                    "Open": [10.0],
                    "High": [11.0],
                    "Low": [9.5],
                    "Close": [10.5],
                    "Volume": [1000],
                },
                index=pd.to_datetime(["2026-01-02"]),
            )
            for symbol in symbols
        }

    count = sync_daily_bars_from_provider(
        repo,
        ["AAPL", "MSFT"],
        provider=provider,
        fallback_provider=None,
        period="1mo",
        batch_size=1,
        progress_callback=lambda done, total, rows: events.append((done, total, rows)),
    )

    assert count == 2
    assert events == [(1, 2, 1), (2, 2, 2)]


def test_sync_daily_bars_continues_after_one_batch_provider_failure(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")
    events = []

    def provider(symbols, period):
        if symbols == ["BAD"]:
            raise RuntimeError("temporary provider failure")
        return {
            symbol: pd.DataFrame(
                {
                    "Open": [10.0],
                    "High": [11.0],
                    "Low": [9.5],
                    "Close": [10.5],
                    "Volume": [1000],
                },
                index=pd.to_datetime(["2026-01-02"]),
            )
            for symbol in symbols
        }

    count = sync_daily_bars_from_provider(
        repo,
        ["AAPL", "BAD", "MSFT"],
        provider=provider,
        fallback_provider=None,
        period="1mo",
        batch_size=1,
        progress_callback=lambda done, total, rows: events.append((done, total, rows)),
    )

    assert count == 2
    assert repo.count_rows("daily_bars") == 2
    assert events == [(1, 3, 1), (2, 3, 1), (3, 3, 2)]


def test_sync_daily_bars_uses_fallback_when_primary_batch_raises(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")

    def primary_provider(symbols, period):
        raise RuntimeError("primary rate limited")

    def fallback_provider(symbols, period):
        assert symbols == ["AAPL"]
        return {
            "AAPL": pd.DataFrame(
                {
                    "Open": [10.0],
                    "High": [11.0],
                    "Low": [9.5],
                    "Close": [10.5],
                    "Volume": [1000],
                },
                index=pd.to_datetime(["2026-01-02"]),
            )
        }

    count = sync_daily_bars_from_provider(
        repo,
        ["AAPL"],
        provider=primary_provider,
        fallback_provider=fallback_provider,
        period="1mo",
    )

    assert count == 1
    assert repo.count_rows("daily_bars") == 1


def test_sync_daily_bars_does_not_retry_same_failing_fallback_twice(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")
    calls = {"fallback": 0}

    def primary_provider(symbols, period):
        raise RuntimeError("primary rate limited")

    def fallback_provider(symbols, period):
        calls["fallback"] += 1
        raise RuntimeError("fallback rate limited")

    count = sync_daily_bars_from_provider(
        repo,
        ["AAPL"],
        provider=primary_provider,
        fallback_provider=fallback_provider,
        period="1mo",
    )

    assert count == 0
    assert calls["fallback"] == 1


def test_sync_daily_bars_rejects_invalid_batch_size(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")

    with pytest.raises(ValueError, match="batch_size"):
        sync_daily_bars_from_provider(repo, ["AAPL"], provider=lambda symbols, period: {}, batch_size=0)
