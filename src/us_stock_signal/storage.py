from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import MarketSnapshot, Recommendation, SignalEvent

_TOP1_TRACK_EVENT_TYPES = {
    "ENTRY_TRIGGERED",
    "STOP_LOSS",
    "TAKE_PROFIT_1",
    "TAKE_PROFIT_2",
    "INVALIDATED",
    "EXPIRED",
}

_TOP1_TERMINAL_EVENT_TYPES = {
    "STOP_LOSS",
    "TAKE_PROFIT_1",
    "TAKE_PROFIT_2",
    "INVALIDATED",
    "EXPIRED",
}

_TRACKED_SIGNAL_TERMINAL_EVENT_TYPES = _TOP1_TERMINAL_EVENT_TYPES


def ensure_data_dir(data_dir: str | Path) -> Path:
    path = Path(data_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_latest_recommendations(
    recommendations: list[Recommendation],
    data_dir: str | Path,
    session: str | None = None,
    scan_summary: dict[str, Any] | None = None,
) -> Path:
    path = ensure_data_dir(data_dir) / "latest_recommendations.json"
    payload = [rec.as_dict() for rec in recommendations]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _save_latest_scan_meta(ensure_data_dir(data_dir), session or _session_from_payload(payload), scan_summary)
    _append_jsonl(ensure_data_dir(data_dir) / "recommendation_history.jsonl", {"timestamp": _now(), "recommendations": payload})
    _save_duckdb_recommendations(payload, ensure_data_dir(data_dir) / "us_stock_signal.duckdb")
    return path


def load_latest_recommendations(data_dir: str | Path) -> list[Recommendation]:
    path = Path(data_dir) / "latest_recommendations.json"
    if not path.exists():
        return []
    return _recommendations_from_payload(json.loads(path.read_text(encoding="utf-8")))


def save_candidate_pool(
    recommendations: list[Recommendation],
    data_dir: str | Path,
    session: str | None = None,
    scan_summary: dict[str, Any] | None = None,
) -> Path:
    path = ensure_data_dir(data_dir) / "latest_candidate_pool.json"
    payload = [rec.as_dict() for rec in recommendations]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _append_jsonl(
        ensure_data_dir(data_dir) / "candidate_pool_history.jsonl",
        {
            "timestamp": _now(),
            "session": session or _session_from_payload(payload),
            "scan_summary": scan_summary or {},
            "recommendations": payload,
        },
    )
    return path


def load_candidate_pool_recommendations(data_dir: str | Path) -> list[Recommendation]:
    path = Path(data_dir) / "latest_candidate_pool.json"
    if not path.exists():
        return []
    return _recommendations_from_payload(json.loads(path.read_text(encoding="utf-8")))


def load_latest_scan_session(data_dir: str | Path) -> str | None:
    data = load_latest_scan_meta(data_dir)
    session = data.get("session")
    return str(session) if session else None


def load_latest_scan_meta(data_dir: str | Path) -> dict[str, Any]:
    path = Path(data_dir) / "latest_scan_meta.json"
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def save_signal_events(events: list[SignalEvent], data_dir: str | Path) -> Path:
    path = ensure_data_dir(data_dir) / "signal_events.jsonl"
    for event in events:
        _append_jsonl(path, asdict(event))
    return path


def save_top1_signal(
    recommendation: Recommendation | None,
    data_dir: str | Path,
    session: str | None = None,
    scan_summary: dict[str, Any] | None = None,
) -> Path | None:
    if recommendation is None or int(recommendation.rank) != 1:
        return None
    path = ensure_data_dir(data_dir) / "top1_signal_history.jsonl"
    existing_ids = {item["recommendation_id"] for item in load_top1_signals(data_dir)}
    if recommendation.id in existing_ids:
        return path
    payload = recommendation.as_dict()
    record = {
        "recommendation_id": recommendation.id,
        "symbol": recommendation.symbol,
        "session": session or recommendation.session,
        "rank": recommendation.rank,
        "score": recommendation.score,
        "signal_status": recommendation.signal_status,
        "lifecycle_status": "PENDING_ENTRY",
        "final_event_type": None,
        "final_event_price": None,
        "final_event_at": None,
        "entered_at": None,
        "closed_at": None,
        "recorded_at": _now(),
        "created_at": payload.get("created_at"),
        "scan_summary": scan_summary or {},
        "payload": payload,
    }
    _append_jsonl(path, record)
    _save_duckdb_top1_signal(record, ensure_data_dir(data_dir) / "us_stock_signal.duckdb")
    return path


def save_top1_signal_events(events: list[SignalEvent], data_dir: str | Path) -> Path | None:
    if not events:
        return None
    path = ensure_data_dir(data_dir) / "top1_signal_events.jsonl"
    top1_signals = load_top1_signals(data_dir)
    top1_ids = {item["recommendation_id"] for item in top1_signals}
    if not top1_ids:
        return None
    lifecycle_status_by_id = {
        item["recommendation_id"]: item.get("lifecycle_status", "PENDING_ENTRY")
        for item in top1_signals
        if item.get("recommendation_id")
    }
    existing_keys = {
        (item["recommendation_id"], item["event_type"])
        for item in load_top1_signal_events(data_dir)
    }
    new_records: list[dict[str, Any]] = []
    for event in events:
        if event.recommendation_id not in top1_ids or event.event_type not in _TOP1_TRACK_EVENT_TYPES:
            continue
        if not _top1_event_allowed_before_persist(event.event_type, lifecycle_status_by_id.get(event.recommendation_id, "PENDING_ENTRY")):
            continue
        event_key = (event.recommendation_id, event.event_type)
        if event_key in existing_keys:
            continue
        record = {
            "recommendation_id": event.recommendation_id,
            "symbol": event.symbol,
            "event_type": event.event_type,
            "price": event.price,
            "timestamp": event.timestamp,
            "message": event.message,
        }
        _append_jsonl(path, record)
        new_records.append(record)
        existing_keys.add(event_key)
        lifecycle_status_by_id[event.recommendation_id] = _next_lifecycle_status(
            lifecycle_status_by_id.get(event.recommendation_id, "PENDING_ENTRY"),
            event.event_type,
        )
    if new_records:
        _save_duckdb_top1_signal_events(new_records, ensure_data_dir(data_dir) / "us_stock_signal.duckdb")
    _reconcile_top1_signal_summaries(data_dir)
    return path if new_records else None


def save_tracked_signals(
    recommendations: list[Recommendation],
    data_dir: str | Path,
    session: str | None = None,
    scan_summary: dict[str, Any] | None = None,
) -> Path | None:
    if not recommendations:
        return None
    path = ensure_data_dir(data_dir) / "tracked_signal_history.jsonl"
    existing_ids = {item["recommendation_id"] for item in load_tracked_signals(data_dir)}
    new_records: list[dict[str, Any]] = []
    for recommendation in recommendations:
        if recommendation.id in existing_ids:
            continue
        payload = recommendation.as_dict()
        record = {
            "recommendation_id": recommendation.id,
            "symbol": recommendation.symbol,
            "session": session or recommendation.session,
            "rank": recommendation.rank,
            "score": recommendation.score,
            "signal_status": recommendation.signal_status,
            "lifecycle_status": "PENDING_ENTRY",
            "final_event_type": None,
            "final_event_price": None,
            "final_event_at": None,
            "entered_at": None,
            "closed_at": None,
            "recorded_at": _now(),
            "created_at": payload.get("created_at"),
            "scan_summary": scan_summary or {},
            "payload": payload,
        }
        _append_jsonl(path, record)
        new_records.append(record)
    if new_records:
        _save_duckdb_tracked_signals(new_records, ensure_data_dir(data_dir) / "us_stock_signal.duckdb")
    return path if new_records else None


def load_tracked_signals(data_dir: str | Path, active_only: bool = False) -> list[dict[str, Any]]:
    path = Path(data_dir) / "tracked_signal_history.jsonl"
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if active_only and item.get("lifecycle_status") in _TRACKED_SIGNAL_TERMINAL_EVENT_TYPES:
            continue
        records.append(item)
    return records


def update_tracked_signal_summaries(events: list[SignalEvent], data_dir: str | Path) -> None:
    if not events:
        return
    significant_events = [event for event in events if event.event_type in _TOP1_TRACK_EVENT_TYPES]
    if not significant_events:
        return
    records = load_tracked_signals(data_dir)
    if not records:
        return
    updates = [
        _tracked_signal_summary_update_from_event(asdict(event))
        for event in sorted(significant_events, key=lambda item: item.timestamp)
    ]
    if not updates:
        return
    data_path = ensure_data_dir(data_dir)
    _update_tracked_signal_history(records, updates, data_path / "tracked_signal_history.jsonl")
    _update_duckdb_tracked_signal_summary(updates, data_path / "us_stock_signal.duckdb")


def load_signal_events(data_dir: str | Path) -> list[SignalEvent]:
    path = Path(data_dir) / "signal_events.jsonl"
    if not path.exists():
        return []
    events: list[SignalEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item.get("timestamp"), str):
            try:
                item["timestamp"] = datetime.fromisoformat(item["timestamp"])
            except ValueError:
                item["timestamp"] = datetime.now(timezone.utc)
        try:
            events.append(SignalEvent(**item))
        except TypeError:
            continue
    return events


def load_top1_signals(data_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(data_dir) / "top1_signal_history.jsonl"
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        records.append(item)
    return records


def load_top1_signal_events(data_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(data_dir) / "top1_signal_events.jsonl"
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        records.append(item)
    return records


def save_backtest_report(report: dict[str, Any], data_dir: str | Path) -> Path:
    path = ensure_data_dir(data_dir) / "backtest_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def save_strategy_search_report(report: dict[str, Any], data_dir: str | Path) -> Path:
    path = ensure_data_dir(data_dir) / "strategy_search_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def save_market_snapshots_parquet(snapshots: list[MarketSnapshot], data_dir: str | Path) -> Path | None:
    if not snapshots:
        return None
    try:
        import pandas as pd
    except Exception:
        return None
    path = ensure_data_dir(data_dir) / "latest_market_snapshots.parquet"
    rows = [asdict(snapshot) for snapshot in snapshots]
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    serializable = json.dumps(payload, ensure_ascii=False, default=_json_default)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(serializable + "\n")


def _save_latest_scan_meta(data_dir: Path, session: str | None, scan_summary: dict[str, Any] | None) -> None:
    meta_path = data_dir / "latest_scan_meta.json"
    meta_path.write_text(
        json.dumps(
            {"timestamp": _now(), "session": session, "scan_summary": scan_summary or {}},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _session_from_payload(payload: list[dict[str, Any]]) -> str | None:
    if not payload:
        return None
    session = payload[0].get("session")
    return str(session) if session else None


def _save_duckdb_recommendations(payload: list[dict[str, Any]], db_path: Path) -> None:
    try:
        import duckdb
    except Exception:
        return
    conn = None
    try:
        conn = duckdb.connect(str(db_path))
        conn.execute(
            """
            create table if not exists recommendations (
                id varchar,
                symbol varchar,
                rank integer,
                score double,
                session varchar,
                payload json,
                created_at timestamp
            )
            """
        )
        for item in payload:
            conn.execute(
                """
                insert into recommendations
                (id, symbol, rank, score, session, payload, created_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    item.get("id"),
                    item.get("symbol"),
                    item.get("rank"),
                    item.get("score"),
                    item.get("session"),
                    json.dumps(item, ensure_ascii=False),
                    item.get("created_at"),
                ],
            )
    except Exception:
        return
    finally:
        if conn is not None:
            conn.close()


def _save_duckdb_top1_signal(record: dict[str, Any], db_path: Path) -> None:
    try:
        import duckdb
    except Exception:
        return
    conn = None
    try:
        conn = duckdb.connect(str(db_path))
        _ensure_top1_signals_table(conn)
        conn.execute(
            """
            insert into top1_signals
            (
                recommendation_id,
                symbol,
                session,
                rank,
                score,
                signal_status,
                lifecycle_status,
                final_event_type,
                final_event_price,
                final_event_at,
                entered_at,
                closed_at,
                created_at,
                recorded_at,
                scan_summary_json,
                payload
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(recommendation_id) do nothing
            """,
            [
                record.get("recommendation_id"),
                record.get("symbol"),
                record.get("session"),
                record.get("rank"),
                record.get("score"),
                record.get("signal_status"),
                record.get("lifecycle_status"),
                record.get("final_event_type"),
                record.get("final_event_price"),
                record.get("final_event_at"),
                record.get("entered_at"),
                record.get("closed_at"),
                record.get("created_at"),
                record.get("recorded_at"),
                json.dumps(record.get("scan_summary", {}), ensure_ascii=False),
                json.dumps(record.get("payload", {}), ensure_ascii=False),
            ],
        )
    except Exception:
        return
    finally:
        if conn is not None:
            conn.close()


def _save_duckdb_top1_signal_events(records: list[dict[str, Any]], db_path: Path) -> None:
    if not records:
        return
    try:
        import duckdb
    except Exception:
        return
    conn = None
    try:
        conn = duckdb.connect(str(db_path))
        conn.execute(
            """
            create table if not exists top1_signal_events (
                event_key varchar primary key,
                recommendation_id varchar,
                symbol varchar,
                event_type varchar,
                price double,
                event_timestamp timestamp,
                message varchar,
                payload json
            )
            """
        )
        for record in records:
            conn.execute(
                """
                insert into top1_signal_events
                (event_key, recommendation_id, symbol, event_type, price, event_timestamp, message, payload)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(event_key) do nothing
                """,
                [
                    f"{record.get('recommendation_id')}:{record.get('event_type')}",
                    record.get("recommendation_id"),
                    record.get("symbol"),
                    record.get("event_type"),
                    record.get("price"),
                    record.get("timestamp"),
                    record.get("message"),
                    json.dumps(record, ensure_ascii=False, default=_json_default),
                ],
            )
    except Exception:
        return
    finally:
        if conn is not None:
            conn.close()


def _save_duckdb_tracked_signals(records: list[dict[str, Any]], db_path: Path) -> None:
    if not records:
        return
    try:
        import duckdb
    except Exception:
        return
    conn = None
    try:
        conn = duckdb.connect(str(db_path))
        _ensure_tracked_signals_table(conn)
        for record in records:
            conn.execute(
                """
                insert into tracked_signals
                (
                    recommendation_id,
                    symbol,
                    session,
                    rank,
                    score,
                    signal_status,
                    lifecycle_status,
                    final_event_type,
                    final_event_price,
                    final_event_at,
                    entered_at,
                    closed_at,
                    created_at,
                    recorded_at,
                    scan_summary_json,
                    payload
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(recommendation_id) do nothing
                """,
                [
                    record.get("recommendation_id"),
                    record.get("symbol"),
                    record.get("session"),
                    record.get("rank"),
                    record.get("score"),
                    record.get("signal_status"),
                    record.get("lifecycle_status"),
                    record.get("final_event_type"),
                    record.get("final_event_price"),
                    record.get("final_event_at"),
                    record.get("entered_at"),
                    record.get("closed_at"),
                    record.get("created_at"),
                    record.get("recorded_at"),
                    json.dumps(record.get("scan_summary", {}), ensure_ascii=False),
                    json.dumps(record.get("payload", {}), ensure_ascii=False),
                ],
            )
    except Exception:
        return
    finally:
        if conn is not None:
            conn.close()


def _top1_summary_update_from_event(record: dict[str, Any]) -> dict[str, Any]:
    event_type = record.get("event_type")
    timestamp = _serialize_timestamp(record.get("timestamp"))
    update = {
        "recommendation_id": record.get("recommendation_id"),
        "lifecycle_status": event_type,
    }
    if event_type == "ENTRY_TRIGGERED":
        update["entered_at"] = timestamp
        return update
    if event_type in _TOP1_TERMINAL_EVENT_TYPES:
        update["final_event_type"] = event_type
        update["final_event_price"] = record.get("price")
        update["final_event_at"] = timestamp
        update["closed_at"] = timestamp
    return update


def _tracked_signal_summary_update_from_event(record: dict[str, Any]) -> dict[str, Any]:
    return _top1_summary_update_from_event(record)


def _top1_event_allowed_before_persist(event_type: str, lifecycle_status: str) -> bool:
    if lifecycle_status in _TOP1_TERMINAL_EVENT_TYPES:
        return False
    if event_type in {"STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2"}:
        return lifecycle_status == "ENTRY_TRIGGERED"
    if event_type == "ENTRY_TRIGGERED":
        return lifecycle_status == "PENDING_ENTRY"
    return True


def _next_lifecycle_status(lifecycle_status: str, event_type: str) -> str:
    if event_type == "ENTRY_TRIGGERED":
        return "ENTRY_TRIGGERED"
    if event_type in _TOP1_TERMINAL_EVENT_TYPES:
        return event_type
    return lifecycle_status


def _update_top1_signal_history(
    records: list[dict[str, Any]],
    updates: list[dict[str, Any]],
    path: Path,
) -> None:
    if not records or not updates:
        return
    records_by_id = {item.get("recommendation_id"): item for item in records if item.get("recommendation_id")}
    changed = False
    for update in updates:
        record = records_by_id.get(update.get("recommendation_id"))
        if not update or record is None:
            continue
        changed = _apply_top1_summary_update(record, update) or changed
    if not changed:
        return
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, default=_json_default) for item in records) + "\n",
        encoding="utf-8",
    )


def _update_tracked_signal_history(
    records: list[dict[str, Any]],
    updates: list[dict[str, Any]],
    path: Path,
) -> None:
    if not records or not updates:
        return
    records_by_id = {item.get("recommendation_id"): item for item in records if item.get("recommendation_id")}
    changed = False
    for update in updates:
        record = records_by_id.get(update.get("recommendation_id"))
        if not update or record is None:
            continue
        changed = _apply_top1_summary_update(record, update) or changed
    if not changed:
        return
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, default=_json_default) for item in records) + "\n",
        encoding="utf-8",
    )


def _apply_top1_summary_update(record: dict[str, Any], update: dict[str, Any]) -> bool:
    changed = False
    for field in ["lifecycle_status", "final_event_type", "final_event_price", "final_event_at", "closed_at"]:
        if field in update and record.get(field) != update.get(field):
            record[field] = update.get(field)
            changed = True
    if update.get("entered_at") and not record.get("entered_at"):
        record["entered_at"] = update["entered_at"]
        changed = True
    return changed


def _update_duckdb_top1_signal_summary(updates: list[dict[str, Any]], db_path: Path) -> None:
    if not updates:
        return
    try:
        import duckdb
    except Exception:
        return
    conn = None
    try:
        conn = duckdb.connect(str(db_path))
        _ensure_top1_signals_table(conn)
        for update in updates:
            conn.execute(
                """
                update top1_signals
                set
                    lifecycle_status = coalesce(?, lifecycle_status),
                    final_event_type = coalesce(?, final_event_type),
                    final_event_price = coalesce(?, final_event_price),
                    final_event_at = coalesce(?, final_event_at),
                    entered_at = coalesce(entered_at, ?),
                    closed_at = coalesce(?, closed_at)
                where recommendation_id = ?
                """,
                [
                    update.get("lifecycle_status"),
                    update.get("final_event_type"),
                    update.get("final_event_price"),
                    update.get("final_event_at"),
                    update.get("entered_at"),
                    update.get("closed_at"),
                    update.get("recommendation_id"),
                ],
            )
    except Exception:
        return
    finally:
        if conn is not None:
            conn.close()


def _update_duckdb_tracked_signal_summary(updates: list[dict[str, Any]], db_path: Path) -> None:
    if not updates:
        return
    try:
        import duckdb
    except Exception:
        return
    conn = None
    try:
        conn = duckdb.connect(str(db_path))
        _ensure_tracked_signals_table(conn)
        for update in updates:
            conn.execute(
                """
                update tracked_signals
                set
                    lifecycle_status = coalesce(?, lifecycle_status),
                    final_event_type = coalesce(?, final_event_type),
                    final_event_price = coalesce(?, final_event_price),
                    final_event_at = coalesce(?, final_event_at),
                    entered_at = coalesce(entered_at, ?),
                    closed_at = coalesce(?, closed_at)
                where recommendation_id = ?
                """,
                [
                    update.get("lifecycle_status"),
                    update.get("final_event_type"),
                    update.get("final_event_price"),
                    update.get("final_event_at"),
                    update.get("entered_at"),
                    update.get("closed_at"),
                    update.get("recommendation_id"),
                ],
            )
    except Exception:
        return
    finally:
        if conn is not None:
            conn.close()


def _reconcile_top1_signal_summaries(data_dir: str | Path) -> None:
    records = load_top1_signals(data_dir)
    if not records:
        return
    event_records = load_top1_signal_events(data_dir)
    if not event_records:
        return
    updates = [
        _top1_summary_update_from_event(record)
        for record in sorted(event_records, key=_event_timestamp_sort_key)
        if record.get("recommendation_id")
    ]
    if not updates:
        return
    data_path = ensure_data_dir(data_dir)
    _update_top1_signal_history(records, updates, data_path / "top1_signal_history.jsonl")
    _update_duckdb_top1_signal_summary(updates, data_path / "us_stock_signal.duckdb")


def _ensure_top1_signals_table(conn) -> None:
    conn.execute(
        """
        create table if not exists top1_signals (
            recommendation_id varchar primary key,
            symbol varchar,
            session varchar,
            rank integer,
            score double,
            signal_status varchar,
            lifecycle_status varchar,
            final_event_type varchar,
            final_event_price double,
            final_event_at timestamp,
            entered_at timestamp,
            closed_at timestamp,
            created_at timestamp,
            recorded_at timestamp,
            scan_summary_json varchar,
            payload json
        )
        """
    )
    for statement in [
        "alter table top1_signals add column if not exists lifecycle_status varchar",
        "alter table top1_signals add column if not exists final_event_type varchar",
        "alter table top1_signals add column if not exists final_event_price double",
        "alter table top1_signals add column if not exists final_event_at timestamp",
        "alter table top1_signals add column if not exists entered_at timestamp",
        "alter table top1_signals add column if not exists closed_at timestamp",
    ]:
        try:
            conn.execute(statement)
        except Exception:
            continue


def _ensure_tracked_signals_table(conn) -> None:
    conn.execute(
        """
        create table if not exists tracked_signals (
            recommendation_id varchar primary key,
            symbol varchar,
            session varchar,
            rank integer,
            score double,
            signal_status varchar,
            lifecycle_status varchar,
            final_event_type varchar,
            final_event_price double,
            final_event_at timestamp,
            entered_at timestamp,
            closed_at timestamp,
            created_at timestamp,
            recorded_at timestamp,
            scan_summary_json varchar,
            payload json
        )
        """
    )
    for statement in [
        "alter table tracked_signals add column if not exists signal_status varchar",
        "alter table tracked_signals add column if not exists lifecycle_status varchar",
        "alter table tracked_signals add column if not exists final_event_type varchar",
        "alter table tracked_signals add column if not exists final_event_price double",
        "alter table tracked_signals add column if not exists final_event_at timestamp",
        "alter table tracked_signals add column if not exists entered_at timestamp",
        "alter table tracked_signals add column if not exists closed_at timestamp",
    ]:
        try:
            conn.execute(statement)
        except Exception:
            continue


def _serialize_timestamp(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _json_default(value: Any) -> str:
    serialized = _serialize_timestamp(value)
    return serialized if isinstance(serialized, str) else str(serialized)


def _event_timestamp_sort_key(record: dict[str, Any]) -> str:
    return str(record.get("timestamp") or "")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _recommendations_from_payload(payload: list[dict[str, Any]]) -> list[Recommendation]:
    recommendations: list[Recommendation] = []
    for item in payload:
        item = dict(item)
        if isinstance(item.get("created_at"), str):
            item["created_at"] = datetime.fromisoformat(item["created_at"])
        recommendations.append(Recommendation(**item))
    return recommendations
