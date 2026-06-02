# VPS Notes

## Daily Closed Loop

The production loop is:

1. After the US close, refresh the full universe and sync full-market daily bars.
2. Before the next US open, run one short recent-bars sync retry to catch delayed Yahoo/Nasdaq data.
3. After fresh data is available, scan the full local database and push DingTalk signals.
4. During the regular session, optional scans can refresh recommendation status, but the v1 signal is daily-bar driven unless `--live` is enabled.

This forms the data-to-signal loop:

`sync-universe -> sync-daily -> DuckDB upsert -> scan full database -> DingTalk alert -> track latest recommendations`

## Recommended Timing

Use America/New_York time in systemd timers.

- `20:30 ET`: full refresh after market close.
- `08:15 ET`: retry recent daily bars, then push the DingTalk premarket signal after the retry finishes. This targets delivery around one hour before the `09:30 ET` regular open.
- `09:45-15:45 ET`: regular-session scan every 15 minutes.

Note: `08:15 ET` is before the regular open at `09:30 ET`, but it is after the extended-hours premarket session starts at `04:00 ET`. If the desired alert time is before extended-hours premarket trading starts, move the retry/scan job earlier, for example `03:30 ET`, while keeping the after-close sync at `20:30 ET`.

The retry matters because free Yahoo data can appear late or be adjusted after the close. Daily bars are upserted by `(symbol, bar_date)`, so repeated syncs do not duplicate rows and can correct stale values.

The CLI also enforces this timing. `sync-daily`, `sync-all`, and `prepare-market` skip by default outside the allowed US/Eastern windows:

- after-close sync: `20:30 ET` or later
- premarket retry: `08:00-09:20 ET`

Use `--force` only for manual repair or historical backfill. Do not use `--force` in normal VPS timers.

## Batching and Rate Limits

Daily sync is batched. The VPS commands use `--batch-size 100`, so about 5,500 symbols are processed in roughly 55 batches rather than one all-at-once request. The default config also sets `daily_sync_batch_delay_seconds: 1.0`, adding a short pause between batches.

The after-close job uses `--period 1y` to maintain enough history for indicators and backtests. The premarket retry uses `--period 5d` so it only refreshes the most recent bars before scanning and pushing; older database history remains intact because daily bars are upserted by `(symbol, bar_date)`.

If a provider fails for one batch, the sync now tries the fallback provider for that batch. If both fail, that batch is recorded as failed and the next batch continues. This prevents one temporary API failure or rate-limit burst from crashing the whole daily loop.

## Commands

Full refresh after close:

```bash
python -m us_stock_signal sync-all --period 1y --batch-size 100
```

Premarket retry plus signal push:

```bash
python -m us_stock_signal prepare-market --session premarket --period 5d --batch-size 100 --notify
```

Manual full-database scan without refreshing data:

```bash
python -m us_stock_signal scan --session premarket --notify
```

Check database coverage:

```bash
python -m us_stock_signal market-status
```

Do not use `--max-symbols` in production. `--max-symbols` is only for local connectivity tests.

## Current Signal Profile

The active default profile is `aggressive_150_60`:

- high-yield breakout only
- `top_n: 2`
- score >= 80
- ATR >= 5%
- 20-day momentum >= 150%
- 5-day momentum >= 60%
- volume ratio >= 2x
- gap <= 80%
- price <= 100
- fixed 2% stop
- TP2 = 7 ATR

The `balanced_120_80` profile is retained in the strategy research log for later comparison but is not the active trigger profile.

## Deployment Notes

- Keep `.env` only on the VPS/local machine. Do not commit DingTalk webhook or DeepSeek keys.
- Keep `data/` persistent and backed up. It stores DuckDB, recommendations, history, and reports.
- If dependency installation fails on a very new Python version, use Python 3.12.
- Before relying on real-money signals, run shadow tracking for a while and compare DingTalk signals with actual execution prices.

## Docker Deployment

The container runs the scheduler:

```bash
docker compose up -d --build
docker compose logs -f --tail=100 us-stock-signal
```

Runtime state is mounted from the host:

- `./data:/app/data`
- `./configs:/app/configs:ro`
- `.env` is loaded by Compose through `env_file`
