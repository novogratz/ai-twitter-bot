from concurrent.futures import ThreadPoolExecutor

from src.core import reply_diagnostics as diagnostics


def test_window_resets_without_inventing_confirmations_and_is_bounded():
    tracker = diagnostics.Tracker()
    tracker.record("send", "shipped", 10, now=60)
    tracker.record("send", "unconfirmed", 5, now=120)
    tracker.record("send", "dry_run", 0, now=180)
    report = tracker.snapshot(now=240)
    assert report["confirmed_per_hour"] == 20
    assert report["stages"]["send"]["shipped"]["count"] == 1
    for minute in range(5, 500):
        tracker.record("discovery", "empty", now=minute * 60)
    assert len(tracker.buckets) <= 60
    assert "send" not in tracker.snapshot(now=500 * 60)["stages"]
    assert diagnostics.Tracker().snapshot(now=500 * 60)["confirmed_per_hour"] is None


def test_concurrent_workers_do_not_lose_counts_or_sum_durations_as_wall_time():
    tracker = diagnostics.Tracker()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: tracker.record("generation", "timeout", 300, now=100), range(80)))
    report = tracker.snapshot(now=160)
    row = report["stages"]["generation"]["timeout"]
    assert row["count"] == 80 and row["seconds"] == 24000 and row["mean_seconds"] == 300
    assert report["observed_seconds"] == 60


def test_optional_diagnostics_failures_are_contained(monkeypatch):
    def broken(*args, **kw):
        raise OSError("telemetry unavailable")
    monkeypatch.setattr(diagnostics.TRACKER, "record", broken)
    monkeypatch.setattr(diagnostics.TRACKER, "snapshot", broken)
    diagnostics.record("send", "shipped", 1)
    assert diagnostics.snapshot() == {"unavailable": True}
