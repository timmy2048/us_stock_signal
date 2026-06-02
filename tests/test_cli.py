import os
from datetime import datetime, timezone
from types import SimpleNamespace

from us_stock_signal import cli
from us_stock_signal.models import MarketSnapshot, Recommendation
from us_stock_signal.storage import load_top1_signal_events, load_top1_signals, save_top1_signal


def test_scan_notify_sends_latest_message(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: {tmp_path.as_posix()}
  database_path: {tmp_path.as_posix()}/test.duckdb
universe: {{}}
scoring: {{}}
pricing: {{}}
backtest: {{}}
schedule: {{}}
""",
        encoding="utf-8",
    )
    rec = Recommendation(
        id="r1",
        symbol="XYZ",
        rank=1,
        score=80,
        session="afterhours",
        current_price=10,
        entry_price_low=10,
        entry_price_high=10.2,
        stop_loss=9.5,
        take_profit_1=10.9,
        take_profit_2=11.5,
        expiry="2 个交易日",
        invalidation_price=9.9,
        reasons=[],
        risk_flags=[],
        data_quality="test",
        ai_status="available",
        signal_status="WATCHLIST",
    )
    sent_messages = []

    class FakeNotifier:
        def __init__(self, webhook, secret):
            pass

        def send_markdown(self, message):
            sent_messages.append(message)
            return True

    monkeypatch.setattr(cli, "collect_snapshots", lambda settings, max_symbols, demo: [])
    monkeypatch.setattr(cli, "build_recommendations_from_snapshots", lambda settings, session, snapshots: [rec])
    monkeypatch.setattr(cli, "DingTalkNotifier", FakeNotifier)

    exit_code = cli.main(["--config", str(config_path), "scan", "--session", "afterhours", "--notify", "--live"])

    assert exit_code == 0
    assert sent_messages
    assert sent_messages[0].title == "美股短线 Top10 预备观察名单"


def test_live_scan_uses_database_snapshot_fallback_when_live_snapshot_empty(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: {tmp_path.as_posix()}
  database_path: {tmp_path.as_posix()}/test.duckdb
universe: {{}}
scoring: {{}}
pricing: {{}}
backtest: {{}}
schedule: {{}}
""",
        encoding="utf-8",
    )
    snapshot = MarketSnapshot(
        symbol="AAPL",
        current_price=10,
        recent_high_15m=10.2,
        atr14=0.5,
        avg_dollar_volume_20d=20000000,
        rule_score=70,
        ml_score=65,
        ai_score=50,
        data_quality="db_snapshot",
    )
    received = {}

    class FakeRepo:
        def upsert_market_snapshots(self, snapshots):
            received["upsert_count"] = len(snapshots)

        def load_latest_market_snapshots(self, limit):
            received["fallback_limit"] = limit
            return []

        def load_market_snapshots_from_daily_bars(self, limit):
            received["daily_fallback_limit"] = limit
            return [snapshot]

    monkeypatch.setattr(cli, "_repo", lambda settings, read_only=False: FakeRepo())
    monkeypatch.setattr(cli, "collect_snapshots", lambda settings, max_symbols, demo: [])
    def fake_build(settings, session, snapshots):
        received["snapshots"] = snapshots
        return []

    monkeypatch.setattr(cli, "build_recommendations_from_snapshots", fake_build)

    exit_code = cli.main(["--config", str(config_path), "scan", "--session", "regular", "--max-symbols", "30", "--live"])

    assert exit_code == 0
    assert received["upsert_count"] == 0
    assert received["fallback_limit"] == 30
    assert received["daily_fallback_limit"] == 30
    assert received["snapshots"] == [snapshot]


def test_track_notify_only_sends_first_significant_event(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: {tmp_path.as_posix()}
  database_path: {tmp_path.as_posix()}/test.duckdb
universe: {{}}
scoring: {{}}
pricing:
  max_tracking_trading_days: 3
backtest: {{}}
schedule: {{}}
""",
        encoding="utf-8",
    )
    rec = Recommendation(
        id="r-track",
        symbol="XYZ",
        rank=1,
        score=80,
        session="premarket",
        current_price=10,
        entry_price_low=10,
        entry_price_high=10.2,
        stop_loss=9.5,
        take_profit_1=11.0,
        take_profit_2=12.0,
        expiry="1 个交易日",
        invalidation_price=9.8,
        reasons=[],
        risk_flags=[],
        data_quality="test",
        ai_status="available",
        created_at=datetime.now(timezone.utc),
    )
    sent_messages = []
    save_top1_signal(rec, tmp_path)
    monkeypatch.setattr(cli, "load_latest_recommendations", lambda data_dir: [rec])
    monkeypatch.setattr(cli, "fetch_latest_prices", lambda symbols: {"XYZ": 11.2})
    monkeypatch.setattr(cli, "_send_dingtalk", lambda settings, message: sent_messages.append(message) or True)

    assert cli.main(["--config", str(config_path), "track", "--notify"]) == 0
    assert cli.main(["--config", str(config_path), "track", "--notify"]) == 0

    assert len(sent_messages) == 1
    assert sent_messages[0].title == "美股信号跟踪提醒"
    assert "触发第一止盈" in sent_messages[0].text
    event_records = load_top1_signal_events(tmp_path)
    assert len(event_records) == 1
    assert event_records[0]["recommendation_id"] == "r-track"
    assert event_records[0]["event_type"] == "TAKE_PROFIT_1"


def test_scan_persists_top1_record_for_review(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: {tmp_path.as_posix()}
  database_path: {tmp_path.as_posix()}/test.duckdb
universe: {{}}
scoring: {{}}
pricing: {{}}
backtest: {{}}
schedule: {{}}
""",
        encoding="utf-8",
    )
    rec = Recommendation(
        id="scan-top1",
        symbol="PLTR",
        rank=1,
        score=91.2,
        session="afterhours",
        current_price=20.0,
        entry_price_low=20.0,
        entry_price_high=20.3,
        stop_loss=19.0,
        take_profit_1=21.0,
        take_profit_2=22.5,
        expiry="1 个交易日",
        invalidation_price=19.6,
        reasons=["breakout"],
        risk_flags=[],
        data_quality="duckdb_daily",
        ai_status="neutral_or_missing",
        signal_status="WATCHLIST",
    )

    class FakeRepo:
        def load_market_snapshots_from_daily_bars(self, limit):
            return []

        def load_latest_market_snapshots(self, limit):
            return []

    monkeypatch.setattr(cli, "_repo", lambda settings, read_only=False: FakeRepo())
    monkeypatch.setattr(cli, "build_recommendations_from_snapshots", lambda settings, session, snapshots: [rec])

    assert cli.main(["--config", str(config_path), "scan", "--session", "afterhours"]) == 0

    top1_records = load_top1_signals(tmp_path)
    assert len(top1_records) == 1
    assert top1_records[0]["recommendation_id"] == "scan-top1"
    assert top1_records[0]["symbol"] == "PLTR"


def test_afterhours_scan_uses_daily_database_before_live_fetch(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: {tmp_path.as_posix()}
  database_path: {tmp_path.as_posix()}/test.duckdb
universe: {{}}
scoring: {{}}
pricing: {{}}
backtest: {{}}
schedule: {{}}
""",
        encoding="utf-8",
    )
    snapshot = MarketSnapshot(
        symbol="PLTR",
        current_price=20,
        recent_high_15m=20.5,
        atr14=1.0,
        avg_dollar_volume_20d=30000000,
        rule_score=80,
        ml_score=75,
        ai_score=50,
        data_quality="duckdb_daily",
    )
    received = {}

    class FakeRepo:
        def upsert_market_snapshots(self, snapshots):
            received["upsert_called"] = True

        def load_latest_market_snapshots(self, limit):
            received["snapshot_fallback_limit"] = limit
            return []

        def load_market_snapshots_from_daily_bars(self, limit):
            received["daily_fallback_limit"] = limit
            return [snapshot]

    def live_fetch_should_not_run(settings, max_symbols, demo):
        raise AssertionError("afterhours scan should use daily database unless --live is set")

    monkeypatch.setattr(cli, "_repo", lambda settings, read_only=False: FakeRepo())
    monkeypatch.setattr(cli, "collect_snapshots", live_fetch_should_not_run)

    def fake_build(settings, session, snapshots):
        received["snapshots"] = snapshots
        return []

    monkeypatch.setattr(cli, "build_recommendations_from_snapshots", fake_build)

    exit_code = cli.main(["--config", str(config_path), "scan", "--session", "afterhours", "--max-symbols", "30"])

    assert exit_code == 0
    assert "upsert_called" not in received
    assert received["daily_fallback_limit"] == 30
    assert "snapshot_fallback_limit" not in received
    assert received["snapshots"] == [snapshot]


def test_scan_without_max_symbols_uses_full_daily_database(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: {tmp_path.as_posix()}
  database_path: {tmp_path.as_posix()}/test.duckdb
universe:
  max_symbols_per_scan: 300
scoring: {{}}
pricing: {{}}
backtest: {{}}
schedule: {{}}
""",
        encoding="utf-8",
    )
    snapshots = [
        MarketSnapshot(
            symbol="AAPL",
            current_price=10,
            recent_high_15m=10.2,
            atr14=0.5,
            avg_dollar_volume_20d=20000000,
            rule_score=70,
            ml_score=65,
            ai_score=50,
            data_quality="duckdb_daily",
        ),
        MarketSnapshot(
            symbol="MSFT",
            current_price=20,
            recent_high_15m=20.4,
            atr14=0.8,
            avg_dollar_volume_20d=30000000,
            rule_score=72,
            ml_score=66,
            ai_score=50,
            data_quality="duckdb_daily",
        ),
    ]
    received = {}

    class FakeRepo:
        def load_market_snapshots_from_daily_bars(self, limit):
            received["daily_limit"] = limit
            return snapshots

        def load_latest_market_snapshots(self, limit):
            received["snapshot_limit"] = limit
            return []

        def upsert_market_snapshots(self, snapshots):
            received["upsert_called"] = True

    monkeypatch.setattr(cli, "_repo", lambda settings, read_only=False: FakeRepo())
    monkeypatch.setattr(cli, "collect_snapshots", lambda settings, max_symbols, demo: (_ for _ in ()).throw(AssertionError("live fetch should not run")))

    def fake_build(settings, session, items):
        received["snapshots"] = items
        return []

    monkeypatch.setattr(cli, "build_recommendations_from_snapshots", fake_build)

    exit_code = cli.main(["--config", str(config_path), "scan", "--session", "afterhours"])

    assert exit_code == 0
    assert received["daily_limit"] is None
    assert "snapshot_limit" not in received
    assert "upsert_called" not in received
    assert received["snapshots"] == snapshots


def test_daily_provider_selection_defaults_to_yahoo_chart():
    provider, fallback = cli._daily_sync_providers("yahoo-chart")

    assert provider is cli.fetch_yahoo_chart_daily_bars
    assert fallback is None


def test_daily_provider_selection_auto_uses_yfinance_then_yahoo_chart():
    provider, fallback = cli._daily_sync_providers("auto")

    assert provider is cli.fetch_yfinance_daily_bars
    assert fallback is cli.fetch_yahoo_chart_daily_bars


def test_sync_daily_skips_outside_guard_window_without_opening_database(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: {tmp_path.as_posix()}
  database_path: {tmp_path.as_posix()}/test.duckdb
universe: {{}}
scoring: {{}}
pricing: {{}}
backtest: {{}}
schedule: {{}}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "daily_sync_window_decision",
        lambda schedule, market_timezone, force=False: SimpleNamespace(
            allowed=False,
            message="blocked for test",
        ),
    )
    monkeypatch.setattr(cli, "_repo", lambda settings, read_only=False: (_ for _ in ()).throw(AssertionError("database should not open")))

    exit_code = cli.main(["--config", str(config_path), "sync-daily"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "跳过日线同步：blocked for test" in output
    assert "--force" in output


def test_sync_all_force_flag_bypasses_guard(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: {tmp_path.as_posix()}
  database_path: {tmp_path.as_posix()}/test.duckdb
universe: {{}}
scoring: {{}}
pricing: {{}}
backtest: {{}}
schedule: {{}}
""",
        encoding="utf-8",
    )
    received = {}

    def fake_decision(schedule, market_timezone, force=False):
        received["force"] = force
        return SimpleNamespace(allowed=False, message="forced flag observed")

    monkeypatch.setattr(cli, "daily_sync_window_decision", fake_decision)
    monkeypatch.setattr(cli, "_repo", lambda settings, read_only=False: (_ for _ in ()).throw(AssertionError("database should not open")))

    exit_code = cli.main(["--config", str(config_path), "sync-all", "--force"])

    assert exit_code == 0
    assert received["force"] is True


def test_prepare_market_syncs_full_universe_then_scans_database(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: {tmp_path.as_posix()}
  database_path: {tmp_path.as_posix()}/test.duckdb
universe:
  max_symbols_per_scan: 300
scoring: {{}}
pricing: {{}}
backtest: {{}}
schedule: {{}}
""",
        encoding="utf-8",
    )
    snapshot = MarketSnapshot(
        symbol="AAPL",
        current_price=10,
        recent_high_15m=10.2,
        atr14=0.5,
        avg_dollar_volume_20d=20000000,
        rule_score=70,
        ml_score=65,
        ai_score=50,
        data_quality="duckdb_daily",
    )
    received = {}

    class FakeRepo:
        def load_symbols(self, limit=None):
            received["load_symbols_limit"] = limit
            return ["AAPL", "MSFT"]

        def load_market_snapshots_from_daily_bars(self, limit):
            received["daily_scan_limit"] = limit
            return [snapshot]

        def load_latest_market_snapshots(self, limit):
            return []

    monkeypatch.setattr(cli, "_repo", lambda settings, read_only=False: FakeRepo())
    monkeypatch.setattr(cli, "sync_universe_from_provider", lambda repo: received.setdefault("universe_synced", True) or 2)

    def fake_sync_daily(
        repo,
        symbols,
        provider,
        fallback_provider,
        period,
        batch_size,
        batch_delay_seconds=0.0,
        progress_callback=None,
    ):
        received["synced_symbols"] = symbols
        received["period"] = period
        received["batch_size"] = batch_size
        received["batch_delay_seconds"] = batch_delay_seconds
        return 60

    monkeypatch.setattr(cli, "sync_daily_bars_from_provider", fake_sync_daily)
    monkeypatch.setattr(cli, "build_recommendations_from_snapshots", lambda settings, session, snapshots: [])

    exit_code = cli.main(["--config", str(config_path), "prepare-market", "--session", "premarket", "--force"])

    assert exit_code == 0
    assert received["load_symbols_limit"] is None
    assert received["synced_symbols"] == ["AAPL", "MSFT"]
    assert received["batch_delay_seconds"] == 0.0
    assert received["daily_scan_limit"] is None


def test_market_status_prints_database_coverage(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: {tmp_path.as_posix()}
  database_path: {tmp_path.as_posix()}/test.duckdb
universe: {{}}
scoring: {{}}
pricing: {{}}
backtest: {{}}
schedule: {{}}
""",
        encoding="utf-8",
    )

    class FakeRepo:
        def market_data_coverage(self, min_daily_bars=25):
            return {
                "active_symbols": 5718,
                "symbols_with_daily_bars": 5600,
                "symbols_ready_for_scan": 5500,
                "daily_bar_rows": 1200000,
                "latest_daily_bar_date": "2026-05-29",
                "coverage_pct": 96.19,
            }

    monkeypatch.setattr(cli, "_repo", lambda settings, read_only=False: FakeRepo())

    exit_code = cli.main(["--config", str(config_path), "market-status"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "股票池总数：5718" in output
    assert "可参与扫描：5500" in output
    assert "覆盖率：96.19%" in output


def test_validate_scoring_runs_real_database_validation(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: {tmp_path.as_posix()}
  database_path: {tmp_path.as_posix()}/test.duckdb
universe: {{}}
scoring: {{}}
pricing: {{}}
backtest:
  slippage_bps: 10
schedule: {{}}
""",
        encoding="utf-8",
    )
    received = {}

    class FakeRepo:
        def load_daily_bars_for_validation(self, max_symbols=None):
            received["max_symbols"] = max_symbols
            return "daily-bars"

    def fake_validate(daily_bars, config, lookback_days, top_n, sample_days, max_holding_days):
        received["daily_bars"] = daily_bars
        received["lookback_days"] = lookback_days
        received["top_n"] = top_n
        received["sample_days"] = sample_days
        received["max_holding_days"] = max_holding_days
        return {
            "lookback_days": lookback_days,
            "top_n": top_n,
            "sample_days_requested": sample_days,
            "sample_days_evaluated": 2,
            "first_signal_date": "2026-01-01",
            "last_signal_date": "2026-01-02",
            "summary": {
                "signal_count": 4,
                "entry_rate": 0.75,
                "win_rate": 0.5,
                "avg_return_pct": 1.25,
                "profit_factor": 1.4,
                "max_drawdown_pct": 2.5,
                "exit_reason_counts": {"TAKE_PROFIT_1": 2, "STOP_LOSS": 1},
            },
            "rank_metrics": [],
            "sample_signals": [],
        }

    monkeypatch.setattr(cli, "_repo", lambda settings, read_only=False: FakeRepo())
    monkeypatch.setattr(cli, "validate_scoring_from_daily_bars", fake_validate)

    exit_code = cli.main(
        [
            "--config",
            str(config_path),
            "validate-scoring",
            "--lookback-days",
            "30",
            "--sample-days",
            "2",
            "--top-n",
            "3",
            "--max-symbols",
            "5",
            "--max-holding-days",
            "7",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert received == {
        "max_symbols": 5,
        "daily_bars": "daily-bars",
        "lookback_days": 30,
        "top_n": 3,
        "sample_days": 2,
        "max_holding_days": 7,
    }
    assert "评分效果验证完成" in output


def test_strategy_search_runs_parameter_search(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: {tmp_path.as_posix()}
  database_path: {tmp_path.as_posix()}/test.duckdb
universe: {{}}
scoring: {{}}
pricing: {{}}
backtest:
  slippage_bps: 10
schedule: {{}}
""",
        encoding="utf-8",
    )
    received = {}

    class FakeRepo:
        def load_daily_bars_for_validation(self, max_symbols=None):
            received["max_symbols"] = max_symbols
            return "daily-bars"

    def fake_search(
        daily_bars,
        base_config,
        lookback_days,
        sample_days,
        max_holding_days,
        objective,
        min_signal_count,
        top_results,
    ):
        received["daily_bars"] = daily_bars
        received["lookback_days"] = lookback_days
        received["sample_days"] = sample_days
        received["max_holding_days"] = max_holding_days
        received["objective"] = objective
        received["min_signal_count"] = min_signal_count
        received["top_results"] = top_results
        return {
            "sample_days_evaluated": 2,
            "objective": objective,
            "min_signal_count": min_signal_count,
            "results": [
                {
                    "variant": {"name": "fast", "top_n": 5, "take_profit_2_atr_multiple": 6},
                    "summary": {
                        "signal_count": 20,
                        "entry_rate": 0.8,
                        "win_rate": 0.35,
                        "avg_return_pct": 5.5,
                        "avg_return_pct_all_signals": 4.4,
                        "profit_factor": 1.9,
                        "max_drawdown_pct": 60,
                    },
                }
            ],
        }

    monkeypatch.setattr(cli, "_repo", lambda settings, read_only=False: FakeRepo())
    monkeypatch.setattr(cli, "search_high_yield_strategies_from_daily_bars", fake_search)

    exit_code = cli.main(
        [
            "--config",
            str(config_path),
            "strategy-search",
            "--lookback-days",
            "30",
            "--sample-days",
            "2",
            "--max-symbols",
            "5",
            "--max-holding-days",
            "7",
            "--objective",
            "avg_all",
            "--min-signals",
            "10",
            "--top-results",
            "3",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert received == {
        "max_symbols": 5,
        "daily_bars": "daily-bars",
        "lookback_days": 30,
        "sample_days": 2,
        "max_holding_days": 7,
        "objective": "avg_all",
        "min_signal_count": 10,
        "top_results": 3,
    }
    assert "策略搜索完成" in output
    assert "fast" in output


def test_scan_skips_when_runtime_lock_exists(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  timezone: Asia/Shanghai
  market_timezone: America/New_York
  data_dir: {tmp_path.as_posix()}
  database_path: {tmp_path.as_posix()}/test.duckdb
universe: {{}}
scoring: {{}}
pricing: {{}}
backtest: {{}}
schedule: {{}}
""",
        encoding="utf-8",
    )
    (tmp_path / "us_stock_signal.lock").write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setattr(cli, "_repo", lambda settings, read_only=False: (_ for _ in ()).throw(AssertionError("database should not open")))

    exit_code = cli.main(["--config", str(config_path), "scan", "--session", "afterhours"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "已有同步或扫描任务正在运行" in output
