"""src/guards/active_hours: Waking hours, DST, bedtime and stop requests."""
from datetime import datetime, timedelta

import pytest

from src.guards import action_guard as ag, active_hours as hours
from tests.helpers import TORONTO, stop_requested, clock


@pytest.mark.parametrize("when,awake", [
    ("2026-09-20T04:29:59-04:00", False),
    ("2026-09-20T04:30:00-04:00", True),
    ("2026-09-20T22:00:00-04:00", True),
    ("2026-09-20T23:29:59-04:00", True),
    ("2026-09-20T23:30:00-04:00", True),
    ("2026-09-20T23:59:59-04:00", True),
    ("2026-09-21T00:00:00-04:00", False),
    # Midnight EDT, then wake after the autumn clock change in EST.
    ("2026-11-01T03:59:59+00:00", True),
    ("2026-11-01T04:00:00+00:00", False),
    ("2026-11-01T09:29:59+00:00", False),
    ("2026-11-01T09:30:00+00:00", True),
    ("2026-11-02T04:59:59+00:00", True),
    ("2026-11-02T05:00:00+00:00", False),
    # Midnight EST, then wake after the spring clock change in EDT.
    ("2026-03-08T04:59:59+00:00", True),
    ("2026-03-08T05:00:00+00:00", False),
    ("2026-03-08T08:29:59+00:00", False),
    ("2026-03-08T08:30:00+00:00", True),
    ("2026-03-09T03:59:59+00:00", True),
    ("2026-03-09T04:00:00+00:00", False),
])
def test_exact_waking_boundaries_and_dst(when, awake):
    assert hours.is_active(datetime.fromisoformat(when)) is awake


def test_the_window_label_follows_the_constants():
    assert hours.window_label() == "04:30–00:00 America/Toronto"


def test_seconds_until_bedtime_counts_the_minutes(monkeypatch):
    clock(monkeypatch, datetime(2026, 9, 20, 23, tzinfo=TORONTO))
    assert hours.seconds_until_bedtime() == 3600
    clock(monkeypatch, datetime(2026, 9, 20, 23, 59, 59, tzinfo=TORONTO))
    assert hours.seconds_until_bedtime() == 1
    clock(monkeypatch, datetime(2026, 9, 21, 0, 0, tzinfo=TORONTO))
    assert hours.seconds_until_bedtime() == 0
    clock(monkeypatch, datetime(2026, 9, 21, 4, 29, tzinfo=TORONTO))
    assert hours.seconds_until_bedtime() == 0


@pytest.mark.parametrize("day", [(2026, 3, 8), (2026, 11, 1), (2026, 12, 31)])
def test_bedtime_is_the_next_midnight_after_wake(day):
    from datetime import timedelta
    now = datetime(*day, 23, 59, tzinfo=TORONTO)
    assert hours.bedtime(now) == now.replace(hour=0, minute=0) + timedelta(days=1)


@pytest.mark.parametrize("now,wake", [
    ("2026-09-20T23:45:00-04:00", "2026-09-21T04:30:00-04:00"),
    ("2026-09-21T03:00:00-04:00", "2026-09-21T04:30:00-04:00"),
    ("2026-10-31T23:45:00-04:00", "2026-11-01T04:30:00-05:00"),
])
def test_next_wake_after_bedtime(now, wake):
    local = datetime.fromisoformat(now).astimezone(TORONTO)
    assert hours.next_wake(local) == datetime.fromisoformat(wake)


def test_no_hardcoded_bedtime_outside_the_constants():
    """Bedtime moved from 22:00 to 23:30 on 2026-09-23; every clock reads
    active_hours.WAKE and BEDTIME, so the old hour must not come back."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"hour\s*=\s*22\b|time\(\s*22\b|\b22\s*\*\s*60\b|\b22:00\b|\b21:59\b")
    files = [*root.glob("src/**/*.py"), *root.glob("bin/*.py"), root / "main.py"]
    hits = [f"{path.relative_to(root)}:{n}" for path in files
            for n, line in enumerate(path.read_text().splitlines(), 1) if pattern.search(line)]
    assert hits == []


def test_every_day_comes_from_the_toronto_clock():
    """Issue #191: the like, follow and pin counters took their day from the
    Mac's clock, so a Mac in Europe opened a second quota in the Toronto
    evening. No calendar day in src/ is read from the Mac's clock: neither
    date.today(), datetime.now().date(), a strftime of the local time, nor
    the first ten characters of a naive datetime.now().isoformat(). Naive
    timestamps are out of scope."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"\b(date|datetime)\.today\(|datetime\.now\(\)\.(date|strftime)\("
                         r"|datetime\.now\(\)\.isoformat\([^)]*\)\[:10\]|time\.strftime\(")
    files = [*root.glob("src/**/*.py"), root / "main.py"]
    hits = [f"{path.relative_to(root)}:{n}" for path in files
            for n, line in enumerate(path.read_text().splitlines(), 1) if pattern.search(line)]
    assert hits == []


@pytest.mark.parametrize("stamped, past", [
    ("2026-10-13", True),
    ("2026-10-14", False),
    ("2026-10-15", False),   # stamped by a Mac ahead of Toronto: still today
    (None, True),
    ("", True),
    (20261014, True),
    ("not a day", True),
])
def test_a_stored_day_is_over_before_today_in_toronto_or_when_unreadable(monkeypatch, stamped, past):
    clock(monkeypatch, datetime(2026, 10, 14, 20, 30, tzinfo=TORONTO))

    assert hours.today_iso() == "2026-10-14"
    assert hours.is_past_day(stamped) is past


def test_night_rejects_all_posting_and_queued_jobs(monkeypatch):
    clock(monkeypatch, datetime(2026, 9, 21, 0, 0, tzinfo=TORONTO))
    called = []
    hours.awake_job(lambda: called.append(True))()
    assert not called
    for action in (ag.POST, ag.QUOTE, ag.REPLY, ag.RETWEET):
        assert not ag.can_post(action)[0]


def test_awake_job_starts_nothing_after_stop(monkeypatch):
    from src.guards.active_hours import awake_job

    ran = []
    job = awake_job(lambda: ran.append(True))
    stop_requested(monkeypatch)

    assert job() is None
    assert ran == []


def test_is_active_ignores_stop_for_the_scheduler_loop(monkeypatch):
    from src.guards import active_hours

    stop_requested(monkeypatch)

    assert active_hours.is_active() is True
    assert active_hours.may_act() is False


@pytest.fixture
def pause(settings_override):
    settings_override(HOURLY_BREAK_MINUTES=10)
    windows = [hours.break_window(datetime(2026, 10, 23, h, tzinfo=TORONTO))
               for h in range(24)]
    return next(window for window in windows if window)


def test_break_plan_is_repeatable_ten_minutes_and_only_during_waking_hours(settings_override):
    settings_override(HOURLY_BREAK_MINUTES=10)
    for day in (datetime(2026, 3, 8, tzinfo=TORONTO),
                datetime(2026, 10, 23, tzinfo=TORONTO),
                datetime(2026, 11, 1, tzinfo=TORONTO)):
        windows = [hours.break_window(day.replace(hour=h)) for h in range(24)]
        assert any(windows[6:]) and not all(windows[6:])
        assert not any(windows[:5])
        for window in filter(None, windows):
            start, end = window
            assert end - start == timedelta(minutes=10)
            assert 35 <= start.minute <= 50
            assert hours.is_active(start) and end <= hours.bedtime(start)
            assert hours.break_window(start + timedelta(minutes=3)) == window
            assert hours.break_until(start - timedelta(seconds=1)) is None
            assert hours.break_until(start) == end
            assert hours.break_until(end - timedelta(seconds=1)) == end
            assert hours.break_until(end) is None


def test_break_gates_jobs_browser_and_publication_then_resumes(monkeypatch, pause, unwalled):
    from src.x import safari
    start, end = pause
    clock(monkeypatch, start)
    ran = []
    job = hours.awake_job(lambda: ran.append(True))
    assert hours.is_active() and not hours.may_act()
    assert job() is None and not ran
    for action in (ag.POST, ag.REPLY, ag.QUOTE, ag.RETWEET):
        assert not ag.can_post(action)[0]
    with pytest.raises(hours.ScheduledBreak):
        hours.require_active()
    with pytest.raises(hours.ScheduledBreak):
        unwalled["_run_js"]("document.title")
    with pytest.raises(hours.ScheduledBreak):
        with safari._safari_lock:
            pytest.fail("Safari lock admitted work during a break")
    clock(monkeypatch, end)
    assert hours.may_act()
    job()
    assert ran == [True]


def test_model_budget_stops_at_break_and_breaks_are_not_failures(monkeypatch, pause):
    from src.core import health
    start, end = pause
    clock(monkeypatch, start - timedelta(seconds=42))
    assert hours.seconds_until_pause() == 42
    clock(monkeypatch, start)
    assert hours.seconds_until_pause() == 0
    monkeypatch.setattr(health, "record_failure", lambda *a: pytest.fail("break counted as failure"))
    monkeypatch.setattr(health, "record_success", lambda *a: pytest.fail("break counted as success"))
    health.wrap_job(hours.require_active, "test")()
    clock(monkeypatch, end)
    assert hours.seconds_until_pause() > 0


def test_zero_break_minutes_keeps_bedtime_budget(monkeypatch, settings_override):
    settings_override(HOURLY_BREAK_MINUTES=0)
    clock(monkeypatch, datetime(2026, 10, 23, 12, tzinfo=TORONTO))
    assert hours.break_window() is None
    assert hours.break_until() is None
    assert hours.seconds_until_pause() == hours.seconds_until_bedtime() == 12 * 3600
