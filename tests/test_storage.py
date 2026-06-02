from pathlib import Path
import json

import us_stock_signal.storage as storage
from datetime import datetime, timezone
import duckdb

from us_stock_signal.models import Recommendation, SignalEvent
from us_stock_signal.storage import (
    load_candidate_pool_recommendations,
    load_latest_scan_session,
    load_tracked_signals,
    load_top1_signal_events,
    load_top1_signals,
    save_candidate_pool,
    save_latest_recommendations,
    save_tracked_signals,
    save_top1_signal,
    save_top1_signal_events,
    update_tracked_signal_summaries,
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
    assert records[0]["lifecycle_status"] == "PENDING_ENTRY"
    assert records[0]["final_event_type"] is None
    assert records[0]["entered_at"] is None
    assert records[0]["closed_at"] is None


def test_save_candidate_pool_round_trips_recommendations(tmp_path):
    rec = Recommendation(
        id="pool-1",
        symbol="XYZ",
        rank=1,
        score=88.5,
        session="premarket",
        current_price=10.0,
        entry_price_low=10.0,
        entry_price_high=10.2,
        max_chase_price=10.25,
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

    save_candidate_pool([rec], tmp_path, session="premarket", scan_summary={"candidate_count": 1})

    loaded = load_candidate_pool_recommendations(tmp_path)
    assert [item.id for item in loaded] == ["pool-1"]
    assert loaded[0].max_chase_price == 10.25


def test_save_tracked_signals_and_update_lifecycle_summary(tmp_path):
    rec = Recommendation(
        id="tracked-1",
        symbol="XYZ",
        rank=3,
        score=83.0,
        session="premarket",
        current_price=10.0,
        entry_price_low=10.0,
        entry_price_high=10.2,
        max_chase_price=10.25,
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
    save_tracked_signals([rec], tmp_path, session="premarket", scan_summary={"candidate_count": 1})
    entry_time = datetime(2026, 6, 3, 13, 0, tzinfo=timezone.utc)
    exit_time = datetime(2026, 6, 3, 14, 0, tzinfo=timezone.utc)

    update_tracked_signal_summaries(
        [SignalEvent(rec.id, rec.symbol, "ENTRY_TRIGGERED", 10.22, entry_time, "entry")],
        tmp_path,
    )
    update_tracked_signal_summaries(
        [SignalEvent(rec.id, rec.symbol, "TAKE_PROFIT_2", 11.5, exit_time, "tp2")],
        tmp_path,
    )

    records = load_tracked_signals(tmp_path)
    assert len(records) == 1
    assert records[0]["lifecycle_status"] == "TAKE_PROFIT_2"
    assert records[0]["entered_at"] == entry_time.isoformat()
    assert records[0]["final_event_type"] == "TAKE_PROFIT_2"
    assert records[0]["closed_at"] == exit_time.isoformat()

    active = load_tracked_signals(tmp_path, active_only=True)
    assert active == []

    conn = duckdb.connect(str(tmp_path / "us_stock_signal.duckdb"))
    try:
        row = conn.execute(
            """
            select rank, lifecycle_status, final_event_type, entered_at, closed_at
            from tracked_signals
            where recommendation_id = ?
            """,
            [rec.id],
        ).fetchone()
    finally:
        conn.close()

    assert row[0] == 3
    assert row[1] == "TAKE_PROFIT_2"
    assert row[2] == "TAKE_PROFIT_2"
    assert row[3].isoformat() == entry_time.replace(tzinfo=None).isoformat()
    assert row[4].isoformat() == exit_time.replace(tzinfo=None).isoformat()


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
        SignalEvent(rec.id, rec.symbol, "ENTRY_TRIGGERED", 20.3, now, "entry"),
        SignalEvent(rec.id, rec.symbol, "TAKE_PROFIT_1", 21.1, now, "tp1"),
        SignalEvent(rec.id, rec.symbol, "TAKE_PROFIT_1", 21.2, now, "tp1 again"),
    ]

    save_top1_signal_events(events, tmp_path)
    save_top1_signal_events(events, tmp_path)

    records = load_top1_signal_events(tmp_path)
    assert len(records) == 2
    assert records[0]["recommendation_id"] == "top1-track"
    assert records[0]["event_type"] == "ENTRY_TRIGGERED"
    assert records[1]["event_type"] == "TAKE_PROFIT_1"


def test_save_top1_signal_events_rejects_stop_or_take_profit_before_entry(tmp_path):
    rec = Recommendation(
        id="top1-preentry-guard",
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
        expiry="1 涓氦鏄撴棩",
        invalidation_price=19.5,
        reasons=[],
        risk_flags=[],
        data_quality="free_delayed",
        ai_status="available",
    )
    save_top1_signal(rec, tmp_path)
    now = datetime.now(timezone.utc)

    save_top1_signal_events(
        [SignalEvent(rec.id, rec.symbol, "STOP_LOSS", 19.0, now, "stop before entry")],
        tmp_path,
    )

    assert load_top1_signal_events(tmp_path) == []
    top1 = load_top1_signals(tmp_path)[0]
    assert top1["lifecycle_status"] == "PENDING_ENTRY"
    assert top1["final_event_type"] is None


def test_save_top1_signal_events_updates_top1_lifecycle_summary(tmp_path):
    rec = Recommendation(
        id="top1-summary",
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
    entry_time = datetime(2026, 6, 2, 13, 0, tzinfo=timezone.utc)
    exit_time = datetime(2026, 6, 2, 14, 15, tzinfo=timezone.utc)

    save_top1_signal_events(
        [SignalEvent(rec.id, rec.symbol, "ENTRY_TRIGGERED", 20.3, entry_time, "entry")],
        tmp_path,
    )
    save_top1_signal_events(
        [SignalEvent(rec.id, rec.symbol, "STOP_LOSS", 19.0, exit_time, "stop")],
        tmp_path,
    )

    records = load_top1_signals(tmp_path)
    assert len(records) == 1
    assert records[0]["lifecycle_status"] == "STOP_LOSS"
    assert records[0]["final_event_type"] == "STOP_LOSS"
    assert records[0]["final_event_price"] == 19.0
    assert records[0]["entered_at"] == entry_time.isoformat()
    assert records[0]["closed_at"] == exit_time.isoformat()

    conn = duckdb.connect(str(tmp_path / "us_stock_signal.duckdb"))
    try:
        row = conn.execute(
            """
            select lifecycle_status, final_event_type, final_event_price, entered_at, closed_at
            from top1_signals
            where recommendation_id = ?
            """,
            [rec.id],
        ).fetchone()
    finally:
        conn.close()

    assert row[0] == "STOP_LOSS"
    assert row[1] == "STOP_LOSS"
    assert row[2] == 19.0
    assert row[3].isoformat() == entry_time.replace(tzinfo=None).isoformat()
    assert row[4].isoformat() == exit_time.replace(tzinfo=None).isoformat()


def test_reconcile_top1_signal_summaries_backfills_existing_event_history(tmp_path):
    rec = Recommendation(
        id="top1-backfill",
        symbol="XYZ",
        rank=1,
        score=88.0,
        session="regular",
        current_price=10.0,
        entry_price_low=10.0,
        entry_price_high=10.2,
        stop_loss=9.5,
        take_profit_1=10.9,
        take_profit_2=11.5,
        expiry="1 个交易日",
        invalidation_price=9.8,
        reasons=[],
        risk_flags=[],
        data_quality="test",
        ai_status="available",
    )
    save_top1_signal(rec, tmp_path)
    event_time = datetime(2026, 6, 2, 15, 0, tzinfo=timezone.utc)
    (tmp_path / "top1_signal_events.jsonl").write_text(
        json.dumps(
            {
                "recommendation_id": rec.id,
                "symbol": rec.symbol,
                "event_type": "TAKE_PROFIT_2",
                "price": 11.5,
                "timestamp": event_time.isoformat(),
                "message": "tp2",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    storage._reconcile_top1_signal_summaries(tmp_path)

    records = load_top1_signals(tmp_path)
    assert records[0]["lifecycle_status"] == "TAKE_PROFIT_2"
    assert records[0]["final_event_type"] == "TAKE_PROFIT_2"
    assert records[0]["final_event_price"] == 11.5
    assert records[0]["closed_at"] == event_time.isoformat()
