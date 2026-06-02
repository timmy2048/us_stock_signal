from us_stock_signal.scheduler import service


def test_scheduler_uses_eastern_time_and_does_not_notify_scan_overnight(monkeypatch):
    created = {}

    class FakeScheduler:
        def __init__(self, timezone):
            created["timezone"] = timezone
            self.jobs = []

        def add_job(self, func, trigger, **kwargs):
            self.jobs.append({"func": func, "trigger": trigger, **kwargs})

        def start(self):
            created["started"] = True

    fake_scheduler = FakeScheduler("America/New_York")
    calls = []
    monkeypatch.setattr(service, "_blocking_scheduler", lambda timezone: fake_scheduler)
    monkeypatch.setattr(service, "_locked_main", lambda argv: calls.append(argv) or 0)

    service.run_scheduler()

    assert created["timezone"] == "America/New_York"
    assert created["started"] is True
    jobs_by_id = {job["id"]: job for job in fake_scheduler.jobs}
    assert jobs_by_id["after_close_full_sync"]["hour"] == 20
    assert jobs_by_id["premarket_retry_and_scan"]["hour"] == 8
    assert jobs_by_id["premarket_retry_and_scan"]["minute"] == 15
    assert "regular_scan_0945" not in jobs_by_id
    assert "regular_scan_day" not in jobs_by_id
    assert jobs_by_id["track"]["hour"] == "4-20"
    assert jobs_by_id["track"]["minute"] == "*/15"
    assert all(job["trigger"] == "cron" for job in fake_scheduler.jobs)

    jobs_by_id["premarket_retry_and_scan"]["func"]()
    jobs_by_id["track"]["func"]()
    assert calls == [
        ["prepare-market", "--session", "premarket", "--period", "5d", "--batch-size", "100", "--notify"],
        ["track", "--notify"],
    ]
