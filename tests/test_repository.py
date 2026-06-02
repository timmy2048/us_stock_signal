from datetime import date, datetime, timezone

from us_stock_signal.data_providers.universe import UniverseSymbol
from us_stock_signal.models import MarketSnapshot
from us_stock_signal.repository import MarketRepository


def test_repository_read_only_skips_schema_initialization_and_connects_read_only():
    calls = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *args, **kwargs):
            calls.append(("execute", args, kwargs))
            return self

    class FakeDuckDB:
        def connect(self, path, read_only=False):
            calls.append(("connect", path, read_only))
            return FakeConnection()

    repo = MarketRepository("data/test.duckdb", duckdb_module=FakeDuckDB(), read_only=True)

    assert calls == []

    with repo._connect():
        pass

    assert len(calls) == 1
    assert calls[0][0] == "connect"
    assert calls[0][2] is True
    assert calls[0][1].endswith("test.duckdb")


def test_repository_upserts_symbols_without_duplicates(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")
    symbols = [
        UniverseSymbol(symbol="AAPL", name="Apple Inc", exchange="NASDAQ"),
        UniverseSymbol(symbol="AAPL", name="Apple Inc Updated", exchange="NASDAQ"),
        UniverseSymbol(symbol="MSFT", name="Microsoft", exchange="NASDAQ"),
    ]

    repo.upsert_symbols(symbols)

    assert repo.count_rows("symbols") == 2
    assert repo.load_symbols(limit=10) == ["AAPL", "MSFT"]


def test_repository_deactivates_symbols_missing_from_latest_universe(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")
    repo.upsert_symbols(
        [
            UniverseSymbol(symbol="AAPL", name="Apple Inc", exchange="NASDAQ"),
            UniverseSymbol(symbol="TEST", name="Test Issue", exchange="NASDAQ"),
        ]
    )

    repo.upsert_symbols([UniverseSymbol(symbol="AAPL", name="Apple Inc", exchange="NASDAQ")])

    assert repo.load_symbols(limit=10) == ["AAPL"]


def test_repository_upserts_daily_bars_by_symbol_and_date(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")
    rows = [
        {
            "symbol": "AAPL",
            "bar_date": date(2026, 1, 2),
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "close": 10.5,
            "volume": 1000,
        },
        {
            "symbol": "AAPL",
            "bar_date": date(2026, 1, 2),
            "open": 10.0,
            "high": 11.5,
            "low": 9.5,
            "close": 11.0,
            "volume": 2000,
        },
    ]

    repo.upsert_daily_bars(rows)

    assert repo.count_rows("daily_bars") == 1
    latest = repo.load_latest_daily_bars("AAPL", limit=1)
    assert latest.iloc[0]["close"] == 11.0
    assert latest.iloc[0]["volume"] == 2000


def test_repository_upserts_market_snapshots_and_loads_latest(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")
    snapshot = MarketSnapshot(
        symbol="AAPL",
        current_price=10,
        recent_high_15m=10.2,
        atr14=0.5,
        avg_dollar_volume_20d=20000000,
        rule_score=70,
        ml_score=65,
        ai_score=50,
        reasons=["strong"],
        risk_flags=[],
        data_quality="test",
    )

    repo.upsert_market_snapshots([snapshot], snapshot_time=datetime(2026, 1, 2, tzinfo=timezone.utc))

    loaded = repo.load_latest_market_snapshots(limit=5)
    assert len(loaded) == 1
    assert loaded[0].symbol == "AAPL"
    assert loaded[0].current_price == 10


def test_repository_builds_market_snapshots_from_daily_bars(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")
    repo.upsert_symbols([UniverseSymbol(symbol="AAPL", name="Apple", exchange="NASDAQ")])
    rows = []
    for idx in range(30):
        price = 10 + idx * 0.1
        rows.append(
            {
                "symbol": "AAPL",
                "bar_date": date(2026, 1, 1 + idx),
                "open": price,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price + 0.1,
                "volume": 2000000,
            }
        )
    repo.upsert_daily_bars(rows)

    snapshots = repo.load_market_snapshots_from_daily_bars(limit=10)

    assert len(snapshots) == 1
    assert snapshots[0].symbol == "AAPL"
    assert snapshots[0].data_quality == "duckdb_daily"
    assert snapshots[0].atr14 > 0


def test_repository_builds_market_snapshots_from_all_daily_bars_when_limit_is_none(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")
    repo.upsert_symbols(
        [
            UniverseSymbol(symbol="AAPL", name="Apple", exchange="NASDAQ"),
            UniverseSymbol(symbol="MSFT", name="Microsoft", exchange="NASDAQ"),
        ]
    )
    rows = []
    for symbol_idx, symbol in enumerate(["AAPL", "MSFT"]):
        for day_idx in range(30):
            price = 10 + symbol_idx + day_idx * 0.1
            rows.append(
                {
                    "symbol": symbol,
                    "bar_date": date(2026, 1, 1 + day_idx),
                    "open": price,
                    "high": price + 0.2,
                    "low": price - 0.2,
                    "close": price + 0.1,
                    "volume": 2000000,
                }
            )
    repo.upsert_daily_bars(rows)

    all_snapshots = repo.load_market_snapshots_from_daily_bars(limit=None)
    limited_snapshots = repo.load_market_snapshots_from_daily_bars(limit=1)

    assert {snapshot.symbol for snapshot in all_snapshots} == {"AAPL", "MSFT"}
    assert len(limited_snapshots) == 1


def test_repository_builds_market_snapshots_only_for_active_symbols(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")
    repo.upsert_symbols(
        [
            UniverseSymbol(symbol="AAPL", name="Apple", exchange="NASDAQ"),
            UniverseSymbol(symbol="OLD", name="Old", exchange="NASDAQ"),
        ]
    )
    repo.upsert_symbols([UniverseSymbol(symbol="AAPL", name="Apple", exchange="NASDAQ")])
    rows = []
    for symbol in ["AAPL", "OLD"]:
        for day_idx in range(30):
            rows.append(
                {
                    "symbol": symbol,
                    "bar_date": date(2026, 1, 1 + day_idx),
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "volume": 2000000,
                }
            )
    repo.upsert_daily_bars(rows)

    snapshots = repo.load_market_snapshots_from_daily_bars(limit=None)

    assert [snapshot.symbol for snapshot in snapshots] == ["AAPL"]


def test_repository_reports_market_data_coverage(tmp_path):
    repo = MarketRepository(tmp_path / "test.duckdb")
    repo.upsert_symbols(
        [
            UniverseSymbol(symbol="AAPL", name="Apple", exchange="NASDAQ"),
            UniverseSymbol(symbol="MSFT", name="Microsoft", exchange="NASDAQ"),
            UniverseSymbol(symbol="XYZ", name="No Data", exchange="NASDAQ"),
            UniverseSymbol(symbol="OLD", name="Old Data", exchange="NASDAQ"),
        ]
    )
    repo.upsert_symbols(
        [
            UniverseSymbol(symbol="AAPL", name="Apple", exchange="NASDAQ"),
            UniverseSymbol(symbol="MSFT", name="Microsoft", exchange="NASDAQ"),
            UniverseSymbol(symbol="XYZ", name="No Data", exchange="NASDAQ"),
        ]
    )
    rows = []
    for symbol in ["AAPL", "MSFT", "OLD"]:
        for day_idx in range(30):
            rows.append(
                {
                    "symbol": symbol,
                    "bar_date": date(2026, 1, 1 + day_idx),
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "volume": 1000,
                }
            )
    repo.upsert_daily_bars(rows)

    coverage = repo.market_data_coverage(min_daily_bars=25)

    assert coverage["active_symbols"] == 3
    assert coverage["symbols_with_daily_bars"] == 2
    assert coverage["symbols_ready_for_scan"] == 2
    assert coverage["daily_bar_rows"] == 60
    assert coverage["latest_daily_bar_date"] == "2026-01-30"
    assert coverage["coverage_pct"] == 66.67
