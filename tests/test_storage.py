from pathlib import Path

import us_stock_signal.storage as storage
from datetime import datetime, timezone

from us_stock_signal.models import Recommendation, SignalEvent
from us_stock_signal.storage import (
    load_latest_scan_session,
    load_top1_signal_events,
    load_top1_signals,
    save_latest_recommendations,
    save_top1_signal,
    save_top1_signal_events,
)


def test_save_duckdb_recommendations_is_best_effort(monkeypatch):
    class BrokenDuckDB:
        @staticmethod
        def connect(path):
            raise OSError("database wal is locked")

    monkeypatch.setitem(__import__("sys").modules, "duckdb", BrokenDuckDB)

    storage._save_duckdb_recommendations([], Path("ignored.duckdb"))


def test_save_latest_recommendations_persists_scan_session_for_empty_results(tmp_path):
    save_latest_recommendations([], tmp_path, session="afterhours")

    assert load_latest_scan_session(tmp_path) == "afterhours"


def test_save_top1_signal_persists_single_record_and_deduplicates(tmp_path):
    rec = Recommendation(
        id="top1-abc",
        symbol="XYZ",
        rank=1,
        score=88.5,
        session="premarket",
        current_price=10.0,
        entry_price_low=10.0,
        entry_price_high=10.2,
        stop_loss=9.5,
        take_profit_1=10.9,
        take_profit_2=11.5,
        expiry="2 个交易日",
        invalidation_price=9.8,
        reasons=["breakout"],
        risk_flags=[],
        data_quality="duckdb_daily",
        ai_status="neutral_or_missing",
    )

    save_top1_signal(rec, tmp_path, session="premarket", scan_summary={"scanned_count": 100})
    save_top1_signal(rec, tmp_path, session="premarket", scan_summary={"scanned_count": 100})

    records = load_top1_signals(tmp_path)
    assert len(records) == 1
    assert records[0]["recommendation_id"] == "top1-abc"
    assert records[0]["scan_summary"]["scanned_count"] == 100


def test_save_top1_signal_events_only_keeps_significant_unique_events(tmp_path):
    rec = Recommendation(
        id="top1-track",
        symbol="ABC",
        rank=1,
        score=90.0,
        session="regular",
        current_price=20.0,
        entry_price_low=20.0,
        entry_price_high=20.3,
        stop_loss=19.0,
        take_profit_1=21.0,
        take_profit_2=22.0,
        expiry="1 个交易日",
        invalidation_price=19.5,
        reasons=[],
        risk_flags=[],
        data_quality="free_delayed",
        ai_status="available",
    )
    save_top1_signal(rec, tmp_path)
    now = datetime.now(timezone.utc)
    events = [
        SignalEvent(rec.id, rec.symbol, "HOLD", 20.5, now, "hold"),
        SignalEvent(rec.id, rec.symbol, "TAKE_PROFIT_1", 21.1, now, "tp1"),
        SignalEvent(rec.id, rec.symbol, "TAKE_PROFIT_1", 21.2, now, "tp1 again"),
    ]

    save_top1_signal_events(events, tmp_path)
    save_top1_signal_events(events, tmp_path)

    records = load_top1_signal_events(tmp_path)
    assert len(records) == 1
    assert records[0]["recommendation_id"] == "top1-track"
    assert records[0]["event_type"] == "TAKE_PROFIT_1"
