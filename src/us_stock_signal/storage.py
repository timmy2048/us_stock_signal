from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import MarketSnapshot, Recommendation, SignalEvent


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
    raw = json.loads(path.read_text(encoding="utf-8"))
    recs = []
    for item in raw:
        item = dict(item)
        if isinstance(item.get("created_at"), str):
            item["created_at"] = datetime.fromisoformat(item["created_at"])
        recs.append(Recommendation(**item))
    return recs


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
    serializable = json.dumps(payload, ensure_ascii=False, default=str)
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
