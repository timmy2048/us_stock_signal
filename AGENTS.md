# AGENTS.md

This file is the handoff note for future Codex sessions in `D:\Trading\us_stock_signal`.

## 1. Project Scope

- Project type: US stock short-term long-only recommendation and alert system.
- Current scope: research and signal alerts only.
- Not in scope:
  - no IBKR integration
  - no auto trading
  - no real position management
  - no portfolio-aware risk engine
- Delivery channel: DingTalk markdown alerts in Chinese.
- Runtime: local Windows for development, Ubuntu VPS in Docker for production scheduling.

## 2. Current Production Strategy

The active default strategy is still the high-yield breakout profile:

- `trigger_mode: high_yield_breakout`
- `profile_name: aggressive_150_60`
- `top_n: 2`
- `min_score: 80`
- `min_momentum_20_pct: 150`
- `min_momentum_5_pct: 60`
- `min_volume_ratio: 2`
- `min_atr_pct: 5`
- `max_gap_pct: 80`
- `max_price: 100`
- fixed stop width: `2%`
- `take_profit_2_atr_multiple: 7.0`
- current primary execution target: `TP2`
- current max holding / tracking window: `3` trading days
- current pending entry expiry: `1` trading day

Reference research log:

- [docs/strategy_research_log.md](D:\Trading\us_stock_signal\docs\strategy_research_log.md)

## 3. Critical Execution Rule

This is the most important recent change.

The DingTalk push, tracking events, and backtest exit logic must stay aligned.

Current rule:

- push message shows `回测触发价`, `回测止损价`, `回测主止盈`, and `参考止盈`
- actual default execution interpretation follows the backtest primary target
- current default primary target is `TP2`
- `TP1` is now informational unless the configured primary target is changed to `tp1`

The alignment layer is here:

- [src/us_stock_signal/execution_policy.py](D:\Trading\us_stock_signal\src\us_stock_signal\execution_policy.py)

Relevant files:

- [src/us_stock_signal/recommender.py](D:\Trading\us_stock_signal\src\us_stock_signal\recommender.py)
- [src/us_stock_signal/scoring_validation.py](D:\Trading\us_stock_signal\src\us_stock_signal\scoring_validation.py)
- [src/us_stock_signal/tracker.py](D:\Trading\us_stock_signal\src\us_stock_signal\tracker.py)
- [src/us_stock_signal/notifiers/dingtalk.py](D:\Trading\us_stock_signal\src\us_stock_signal\notifiers\dingtalk.py)
- [src/us_stock_signal/cli.py](D:\Trading\us_stock_signal\src\us_stock_signal\cli.py)
- [src/us_stock_signal/models.py](D:\Trading\us_stock_signal\src\us_stock_signal\models.py)

If a future session changes stop-loss / take-profit behavior, update all four surfaces together:

1. recommendation generation
2. backtest / validation
3. DingTalk push wording
4. tracking event trigger logic

## 4. Data and Scan Closed Loop

The intended daily loop is:

1. sync full stock universe
2. sync daily bars into DuckDB
3. scan full local database
4. push DingTalk signal
5. track latest recommendations

Current production timing is based on `America/New_York`:

- `20:30 ET`: full post-close sync
- `08:15 ET`: recent daily-bar retry plus premarket push
- tracking runs every 15 minutes during the configured window

Important:

- production scanning is database-driven, not full live-market fetch for 5000+ symbols
- `sync-daily` and `prepare-market` are protected by US-market time windows
- repeated daily syncs do not duplicate rows because daily bars are upserted by `(symbol, bar_date)`
- the local workspace has now moved from `latest_recommendations`-only tracking to `candidate_pool + tracked_signals`
- intraday monitoring is still **not** a full-market rescan; it monitors the latest persisted candidate pool and any still-active tracked signals

Reference:

- [docs_vps.md](D:\Trading\us_stock_signal\docs_vps.md)

## 5. Current Production Behavior

Production now runs in Docker on the VPS as the scheduler process:

- service name: `us-stock-signal`
- command: `python -m us_stock_signal.scheduler`

Current production behavior:

- premarket push is the main recommendation push
- intraday repeated Top recommendations were disabled
- track notifications are deduplicated
- track notifications only send first-time meaningful events
- daily-bar sourced recommendations explicitly say they are not intraday real-time prices

Local workspace behavior after the latest implementation:

- each scan persists:
  - `latest_recommendations.json` for the pushed TopN
  - `latest_candidate_pool.json` for the broader intraday monitor pool
  - `tracked_signal_history.jsonl` for lifecycle-managed active signals
- `track --notify` now monitors:
  - the latest candidate pool
  - any non-terminal historical tracked signals
- `track` no longer writes stop-loss or take-profit before `ENTRY_TRIGGERED`
- `track` messages now include:
  - morning rank
  - trigger price
  - chase cap
  - stop loss
  - primary take profit

## 6. Storage Layout

Main runtime state:

- DuckDB database under `data/`
- recommendation history JSON / JSONL under `data/`
- backtest and strategy search reports under `data/`

Important persistence:

- `latest_recommendations.json`
- `latest_candidate_pool.json`
- `recommendation_history.jsonl`
- `candidate_pool_history.jsonl`
- `signal_events.jsonl`
- `tracked_signal_history.jsonl`
- `top1_signal_history.jsonl`
- `top1_signal_events.jsonl`
- `us_stock_signal.duckdb`

Top1-specific persistence already exists:

- each scan with a rank-1 recommendation writes a dedicated Top1 record
- follow-up Top1 events are persisted separately for review

Generic tracked-signal persistence now also exists:

- DuckDB table: `tracked_signals`
- JSONL lifecycle store: `tracked_signal_history.jsonl`
- summary fields include:
  - `lifecycle_status`
  - `entered_at`
  - `final_event_type`
  - `final_event_price`
  - `final_event_at`
  - `closed_at`

## 7. Known Current State In This Workspace

As of the latest session:

- the backtest/push/track execution-alignment change is implemented locally
- the candidate-pool + tracked-signals monitoring layer is now implemented locally
- all local tests pass
- the earlier execution-alignment change had already been deployed to the VPS and verified inside the container
- the new candidate-pool monitoring layer has **not** yet been deployed to the VPS in this session
- GitHub has not yet been updated with this latest local monitoring-layer change

So if a future session starts by asking "is GitHub current?", the answer is:

- VPS: only up to the earlier execution-alignment change, not this latest monitoring-layer change
- local workspace: yes
- public GitHub repo: not yet for this latest change

## 8. Git and Deployment Notes

- repo root is already a git repo on `main`
- `.env` and `data/` must never be committed
- public GitHub repo already exists, but local direct `git push` / `git fetch` over HTTPS has been unreliable on this machine
- previous GitHub syncs were done via API fallback when necessary

If a future session needs to publish code:

1. verify local tests
2. check `git status`
3. do not commit `.env`, database, or generated runtime data
4. if normal `git push` fails due to network/reset issues, use the same GitHub API fallback approach

## 9. Useful Commands

Local verification:

```powershell
cd D:\Trading\us_stock_signal
python -m pytest -q -p no:cacheprovider
```

Manual scan:

```powershell
python -m us_stock_signal scan --session premarket --notify
python -m us_stock_signal scan --session regular --notify
python -m us_stock_signal scan --session afterhours --notify
```

Manual data prep:

```powershell
python -m us_stock_signal sync-universe
python -m us_stock_signal sync-daily --period 1y
python -m us_stock_signal prepare-market --session premarket --period 5d --notify
python -m us_stock_signal market-status
```

Research / validation:

```powershell
python -m us_stock_signal validate-scoring --lookback-days 365 --sample-days 40
python -m us_stock_signal strategy-search --lookback-days 365 --sample-days 40 --min-signals 30 --objective compound
```

## 10. Tests Added For The Latest Execution-Alignment Change

These tests are the first place to check if someone later breaks the alignment:

- [tests/test_notifier.py](D:\Trading\us_stock_signal\tests\test_notifier.py)
- [tests/test_recommender.py](D:\Trading\us_stock_signal\tests\test_recommender.py)
- [tests/test_tracker.py](D:\Trading\us_stock_signal\tests\test_tracker.py)

## 11. Recommended Next Steps

If the user resumes this project, likely next candidates are:

1. deploy the candidate-pool + tracked-signals monitoring layer to the VPS Docker service
2. push the latest local monitoring-layer change to GitHub
3. decide whether to move from `Top2` to strict `Top1-only`
4. if `Top1-only` is chosen, align:
   - backtest
   - DingTalk push
   - track logic
   - research report wording
5. consider a more explicit "shadow tracking vs production recommendation" report

## 12. Resume Rule For Future Sessions

If resuming this repo in a new session, do this first:

1. read this file
2. read [docs/strategy_research_log.md](D:\Trading\us_stock_signal\docs\strategy_research_log.md)
3. check `git status -sb`
4. if the task is about production behavior, verify whether local / VPS / GitHub are in sync before changing anything
5. if the task mentions intraday tracking, confirm whether it refers to:
   - the local `candidate_pool + tracked_signals` model
   - or the older VPS deployment that may still be on `latest_recommendations`-only tracking
