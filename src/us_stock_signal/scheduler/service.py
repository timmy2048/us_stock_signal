from __future__ import annotations

from threading import Lock

from us_stock_signal.cli import main

_JOB_LOCK = Lock()


def run_scheduler() -> None:
    scheduler = _blocking_scheduler("America/New_York")
    scheduler.add_job(
        lambda: _locked_main(["sync-all", "--period", "1y", "--batch-size", "100"]),
        "cron",
        day_of_week="mon-fri",
        hour=20,
        minute=30,
        id="after_close_full_sync",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        lambda: _locked_main(["prepare-market", "--session", "premarket", "--period", "5d", "--batch-size", "100", "--notify"]),
        "cron",
        day_of_week="mon-fri",
        hour=8,
        minute=15,
        id="premarket_retry_and_scan",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        lambda: _locked_main(["track", "--notify"]),
        "cron",
        day_of_week="mon-fri",
        hour="4-20",
        minute="*/15",
        id="track",
        max_instances=1,
        coalesce=True,
    )
    print("Starting us-stock-signal scheduler with America/New_York cron jobs.", flush=True)
    scheduler.start()


def _blocking_scheduler(timezone: str):
    from apscheduler.schedulers.blocking import BlockingScheduler

    return BlockingScheduler(timezone=timezone)


def _locked_main(argv: list[str]) -> int:
    if not _JOB_LOCK.acquire(blocking=False):
        print(f"Skip job because another sync or scan job is running: {' '.join(argv)}", flush=True)
        return 0
    try:
        return main(argv)
    finally:
        _JOB_LOCK.release()
