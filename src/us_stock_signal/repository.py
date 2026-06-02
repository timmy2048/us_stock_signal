from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .data_providers.universe import UniverseSymbol
from .features.technical import average_true_range, score_technical_snapshot, technical_snapshot_features
from .models import MarketSnapshot
from .models_ml.simple_model import heuristic_ml_score


class MarketRepository:
    def __init__(self, db_path: str | Path, read_only: bool = False, duckdb_module: Any | None = None) -> None:
        self.db_path = Path(db_path)
        self.read_only = read_only
        if not read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if duckdb_module is None:
            try:
                import duckdb
            except Exception as exc:  # pragma: no cover
                raise RuntimeError("DuckDB is required. Install dependencies with: python -m pip install -e .") from exc
            self._duckdb = duckdb
        else:
            self._duckdb = duckdb_module
        if not read_only:
            self._init_schema()

    def upsert_symbols(self, symbols: list[UniverseSymbol]) -> int:
        if not symbols:
            return 0
        deduped: dict[str, dict[str, Any]] = {}
        for rank, item in enumerate(symbols, start=1):
            deduped[item.symbol.upper()] = {
                "symbol": item.symbol.upper(),
                "name": item.name,
                "exchange": item.exchange,
                "is_etf": item.is_etf,
                "priority_rank": rank,
                "updated_at": _now(),
            }
        rows = list(deduped.values())
        with self._connect() as conn:
            conn.register("symbol_rows", pd.DataFrame(rows))
            conn.execute(
                """
                insert into symbols(symbol, name, exchange, is_etf, priority_rank, updated_at)
                select symbol, name, exchange, is_etf, priority_rank, updated_at from symbol_rows
                on conflict(symbol) do update set
                    name = excluded.name,
                    exchange = excluded.exchange,
                    is_etf = excluded.is_etf,
                    priority_rank = excluded.priority_rank,
                    updated_at = excluded.updated_at
                """
            )
            conn.execute("update symbols set is_active = false where symbol not in (select symbol from symbol_rows)")
            conn.execute("update symbols set is_active = true where symbol in (select symbol from symbol_rows)")
        return len({row["symbol"] for row in rows})

    def load_symbols(self, limit: int | None = None) -> list[str]:
        query = "select symbol from symbols where is_active order by priority_rank asc, symbol asc"
        params: list[Any] = []
        if limit:
            query += " limit ?"
            params.append(limit)
        with self._connect() as conn:
            return [row[0] for row in conn.execute(query, params).fetchall()]

    def upsert_daily_bars(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        normalized_by_key: dict[tuple[str, date], dict[str, Any]] = {}
        for row in rows:
            symbol = str(row["symbol"]).upper()
            bar_date = row["bar_date"]
            normalized_by_key[(symbol, bar_date)] = {
                "symbol": symbol,
                "bar_date": bar_date,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "updated_at": _now(),
            }
        normalized = list(normalized_by_key.values())
        with self._connect() as conn:
            conn.register("daily_rows", pd.DataFrame(normalized))
            conn.execute(
                """
                insert into daily_bars
                select symbol, bar_date, open, high, low, close, volume, updated_at from daily_rows
                on conflict(symbol, bar_date) do update set
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    updated_at = excluded.updated_at
                """
            )
        return len({(row["symbol"], row["bar_date"]) for row in normalized})

    def load_latest_daily_bars(self, symbol: str, limit: int = 90):
        with self._connect() as conn:
            return conn.execute(
                """
                select symbol, bar_date, open, high, low, close, volume
                from daily_bars
                where symbol = ?
                order by bar_date desc
                limit ?
                """,
                [symbol.upper(), limit],
            ).fetchdf()

    def upsert_market_snapshots(
        self,
        snapshots: list[MarketSnapshot],
        snapshot_time: datetime | None = None,
    ) -> int:
        if not snapshots:
            return 0
        snapshot_time = snapshot_time or datetime.now(timezone.utc)
        rows = []
        for snapshot in snapshots:
            data = asdict(snapshot)
            rows.append(
                {
                    "symbol": snapshot.symbol.upper(),
                    "snapshot_time": snapshot_time,
                    "current_price": snapshot.current_price,
                    "recent_high_15m": snapshot.recent_high_15m,
                    "atr14": snapshot.atr14,
                    "avg_dollar_volume_20d": snapshot.avg_dollar_volume_20d,
                    "rule_score": snapshot.rule_score,
                    "ml_score": snapshot.ml_score,
                    "ai_score": snapshot.ai_score,
                    "reasons_json": json.dumps(snapshot.reasons, ensure_ascii=False),
                    "risk_flags_json": json.dumps(snapshot.risk_flags, ensure_ascii=False),
                    "data_quality": snapshot.data_quality,
                    "payload_json": json.dumps(data, ensure_ascii=False, default=str),
                    "updated_at": _now(),
                }
            )
        with self._connect() as conn:
            conn.register("snapshot_rows", pd.DataFrame(rows))
            conn.execute(
                """
                insert into market_snapshots
                select
                    symbol, snapshot_time, current_price, recent_high_15m, atr14,
                    avg_dollar_volume_20d, rule_score, ml_score, ai_score,
                    reasons_json, risk_flags_json, data_quality, payload_json, updated_at
                from snapshot_rows
                on conflict(symbol, snapshot_time) do update set
                    current_price = excluded.current_price,
                    recent_high_15m = excluded.recent_high_15m,
                    atr14 = excluded.atr14,
                    avg_dollar_volume_20d = excluded.avg_dollar_volume_20d,
                    rule_score = excluded.rule_score,
                    ml_score = excluded.ml_score,
                    ai_score = excluded.ai_score,
                    reasons_json = excluded.reasons_json,
                    risk_flags_json = excluded.risk_flags_json,
                    data_quality = excluded.data_quality,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """
            )
        return len(rows)

    def load_latest_market_snapshots(self, limit: int | None = 300) -> list[MarketSnapshot]:
        limit_clause = "limit ?" if limit is not None else ""
        params: list[Any] = [limit] if limit is not None else []
        with self._connect() as conn:
            df = conn.execute(
                f"""
                select payload_json
                from market_snapshots
                qualify row_number() over (partition by symbol order by snapshot_time desc) = 1
                order by avg_dollar_volume_20d desc
                {limit_clause}
                """,
                params,
            ).fetchdf()
        snapshots: list[MarketSnapshot] = []
        for payload in df["payload_json"].tolist():
            data = json.loads(payload)
            snapshots.append(MarketSnapshot(**data))
        return snapshots

    def load_market_snapshots_from_daily_bars(self, limit: int | None = 300) -> list[MarketSnapshot]:
        limit_clause = "limit ?" if limit is not None else ""
        params: list[Any] = [limit] if limit is not None else []
        with self._connect() as conn:
            all_bars = conn.execute(
                f"""
                with selected_symbols as (
                    select daily_bars.symbol, max(close * volume) as liquidity
                    from daily_bars
                    inner join symbols on symbols.symbol = daily_bars.symbol and symbols.is_active
                    group by daily_bars.symbol
                    having count(*) >= 25
                    order by liquidity desc
                    {limit_clause}
                ),
                ranked_bars as (
                    select
                        daily_bars.symbol,
                        daily_bars.bar_date,
                        daily_bars.open,
                        daily_bars.high,
                        daily_bars.low,
                        daily_bars.close,
                        daily_bars.volume,
                        row_number() over (partition by daily_bars.symbol order by daily_bars.bar_date desc) as row_num
                    from daily_bars
                    inner join selected_symbols on selected_symbols.symbol = daily_bars.symbol
                )
                select symbol, bar_date, open, high, low, close, volume
                from ranked_bars
                where row_num <= 90
                order by symbol asc, bar_date asc
                """,
                params,
            ).fetchdf()
        if all_bars.empty:
            return []
        snapshots: list[MarketSnapshot] = []
        for symbol, frame in all_bars.groupby("symbol", sort=False):
            if frame.empty or len(frame) < 25:
                continue
            frame = frame.sort_values("bar_date")
            opens = frame["open"].tolist()
            closes = frame["close"].tolist()
            highs = frame["high"].tolist()
            lows = frame["low"].tolist()
            volumes = frame["volume"].tolist()
            current_price = float(closes[-1])
            atr = average_true_range(highs, lows, closes, period=14)
            if current_price <= 0 or atr <= 0:
                continue
            avg_dollar_volume = float(frame["volume"].tail(20).mean()) * current_price
            rule_score, reasons, risks = score_technical_snapshot(closes, volumes, current_price)
            volume_mean = float(frame["volume"].tail(20).mean())
            volume_ratio = float(frame["volume"].iloc[-1]) / volume_mean if volume_mean else 1.0
            ml_score = heuristic_ml_score(rule_score, atr / current_price, volume_ratio)
            extra = technical_snapshot_features(closes, highs, volumes, current_price, opens=opens, lows=lows)
            extra["atr_pct"] = atr / current_price * 100
            snapshots.append(
                MarketSnapshot(
                    symbol=symbol,
                    current_price=current_price,
                    recent_high_15m=current_price,
                    atr14=float(atr),
                    avg_dollar_volume_20d=float(avg_dollar_volume),
                    rule_score=rule_score,
                    ml_score=ml_score,
                    ai_score=50,
                    reasons=reasons + ["数据库日线预备观察"],
                    risk_flags=risks,
                    data_quality="duckdb_daily",
                    extra=extra,
                )
            )
        return snapshots

    def count_rows(self, table_name: str) -> int:
        allowed = {"symbols", "daily_bars", "market_snapshots", "recommendations", "signal_events", "sync_runs"}
        if table_name not in allowed:
            raise ValueError(f"unsupported table: {table_name}")
        with self._connect() as conn:
            return int(conn.execute(f"select count(*) from {table_name}").fetchone()[0])

    def market_data_coverage(self, min_daily_bars: int = 25) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                with daily_counts as (
                    select daily_bars.symbol, count(*) as bar_count, max(bar_date) as latest_bar_date
                    from daily_bars
                    inner join symbols on symbols.symbol = daily_bars.symbol and symbols.is_active
                    group by daily_bars.symbol
                )
                select
                    (select count(*) from symbols where is_active) as active_symbols,
                    (select count(*) from daily_counts) as symbols_with_daily_bars,
                    (select count(*) from daily_counts where bar_count >= ?) as symbols_ready_for_scan,
                    (
                        select count(*)
                        from daily_bars
                        inner join symbols on symbols.symbol = daily_bars.symbol and symbols.is_active
                    ) as daily_bar_rows,
                    (select max(latest_bar_date) from daily_counts) as latest_daily_bar_date
                """,
                [min_daily_bars],
            ).fetchone()
        active_symbols = int(row[0] or 0)
        ready_symbols = int(row[2] or 0)
        latest_date = row[4].isoformat() if row[4] else None
        return {
            "active_symbols": active_symbols,
            "symbols_with_daily_bars": int(row[1] or 0),
            "symbols_ready_for_scan": ready_symbols,
            "daily_bar_rows": int(row[3] or 0),
            "latest_daily_bar_date": latest_date,
            "coverage_pct": round((ready_symbols / active_symbols * 100), 2) if active_symbols else 0.0,
        }

    def load_daily_bars_for_validation(self, max_symbols: int | None = None):
        limit_clause = "limit ?" if max_symbols is not None else ""
        params: list[Any] = [max_symbols] if max_symbols is not None else []
        with self._connect() as conn:
            return conn.execute(
                f"""
                with selected_symbols as (
                    select daily_bars.symbol, max(close * volume) as liquidity
                    from daily_bars
                    inner join symbols on symbols.symbol = daily_bars.symbol and symbols.is_active
                    group by daily_bars.symbol
                    having count(*) >= 60
                    order by liquidity desc
                    {limit_clause}
                )
                select daily_bars.symbol, bar_date, open, high, low, close, volume
                from daily_bars
                inner join selected_symbols on selected_symbols.symbol = daily_bars.symbol
                order by daily_bars.symbol asc, bar_date asc
                """,
                params,
            ).fetchdf()

    def record_sync_run(
        self,
        sync_type: str,
        status: str,
        rows_processed: int,
        message: str = "",
        started_at: datetime | None = None,
    ) -> None:
        started_at = started_at or datetime.now(timezone.utc)
        with self._connect() as conn:
            conn.execute(
                """
                insert into sync_runs(sync_type, status, rows_processed, message, started_at, finished_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                [sync_type, status, rows_processed, message, started_at, datetime.now(timezone.utc)],
            )

    def _connect(self):
        return self._duckdb.connect(str(self.db_path), read_only=self.read_only)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists symbols (
                    symbol varchar primary key,
                    name varchar,
                    exchange varchar,
                    is_etf boolean,
                    is_active boolean default true,
                    priority_rank integer default 1000000,
                    updated_at timestamp
                )
                """
            )
            conn.execute(
                """
                create table if not exists daily_bars (
                    symbol varchar,
                    bar_date date,
                    open double,
                    high double,
                    low double,
                    close double,
                    volume bigint,
                    updated_at timestamp,
                    primary key(symbol, bar_date)
                )
                """
            )
            conn.execute(
                """
                create table if not exists market_snapshots (
                    symbol varchar,
                    snapshot_time timestamp,
                    current_price double,
                    recent_high_15m double,
                    atr14 double,
                    avg_dollar_volume_20d double,
                    rule_score double,
                    ml_score double,
                    ai_score double,
                    reasons_json varchar,
                    risk_flags_json varchar,
                    data_quality varchar,
                    payload_json varchar,
                    updated_at timestamp,
                    primary key(symbol, snapshot_time)
                )
                """
            )
            conn.execute(
                """
                create table if not exists sync_runs (
                    sync_type varchar,
                    status varchar,
                    rows_processed integer,
                    message varchar,
                    started_at timestamp,
                    finished_at timestamp
                )
                """
            )


def _now() -> datetime:
    return datetime.now(timezone.utc)
