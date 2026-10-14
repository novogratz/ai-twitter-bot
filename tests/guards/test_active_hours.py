"""Fixed Toronto activity windows, DST, breaks and stop requests."""
from datetime import datetime, timedelta

import pytest

from src.guards import action_guard as ag, active_hours as hours
from tests.helpers import TORONTO, stop_requested, clock


@pytest.mark.parametrize("when,awake", [
    ("2026-10-14T04:59:59-04:00", False), ("2026-10-14T05:00:00-04:00", True),
    ("2026-10-14T09:29:59-04:00", True), ("2026-10-14T09:30:00-04:00", False),
    ("2026-10-14T12:04:59-04:00", False), ("2026-10-14T12:05:00-04:00", True),
    ("2026-10-14T12:59:59-04:00", True), ("2026-10-14T13:00:00-04:00", False),
    ("2026-10-14T17:14:59-04:00", False), ("2026-10-14T17:15:00-04:00", True),
    ("2026-10-14T19:59:59-04:00", True), ("2026-10-14T20:00:00-04:00", False),
    ("2026-10-14T21:59:59-04:00", False), ("2026-10-14T22:00:00-04:00", True),
    ("2026-10-14T22:59:59-04:00", True), ("2026-10-14T23:00:00-04:00", False),
    ("2026-11-01T09:59:59+00:00", False), ("2026-11-01T10:00:00+00:00", True),
    ("2026-11-02T03:59:59+00:00", True), ("2026-11-02T04:00:00+00:00", False),
    ("2026-03-08T08:59:59+00:00", False), ("2026-03-08T09:00:00+00:00", True),
    ("2026-03-09T02:59:59+00:00", True), ("2026-03-09T03:00:00+00:00", False),
])
def test_exact_waking_boundaries_and_dst(when, awake):
    assert hours.is_active(datetime.fromisoformat(when)) is awake


def test_fixed_windows_apply_every_minute_every_day_without_jitter():
    monday = datetime(2026, 10, 12, tzinfo=TORONTO)
    for day in range(7):
        for minute in range(24 * 60):
            now = monday + timedelta(days=day, minutes=minute)
            expected = (300 <= minute < 570 or 725 <= minute < 780
                        or 1035 <= minute < 1200 or 1320 <= minute < 1380)
            assert hours.is_active(now) is expected


def test_the_window_label_follows_the_constants():
    assert hours.window_label() == "05:00–09:30, 12:05–13:00, 17:15–20:00, 22:00–23:00 America/Toronto"


@pytest.mark.parametrize("hour,minute,remaining", [
    (4, 59, 0), (9, 29, 60), (9, 30, 0), (12, 4, 0), (12, 5, 3300),
    (12, 59, 60), (13, 0, 0), (17, 14, 0), (19, 59, 60), (20, 0, 0),
    (21, 59, 0), (22, 0, 3600), (22, 59, 60), (23, 0, 0),
])
def test_seconds_until_bedtime_stops_at_each_close(monkeypatch, hour, minute, remaining):
    clock(monkeypatch, datetime(2026, 10, 14, hour, minute, tzinfo=TORONTO))
    assert hours.seconds_until_bedtime() == remaining


@pytest.mark.parametrize("now,wake", [
    ("2026-10-14T04:59:59-04:00", "2026-10-14T05:00:00-04:00"),
    ("2026-10-14T09:30:00-04:00", "2026-10-14T12:05:00-04:00"),
    ("2026-10-14T13:00:00-04:00", "2026-10-14T17:15:00-04:00"),
    ("2026-10-14T20:00:00-04:00", "2026-10-14T22:00:00-04:00"),
    ("2026-10-14T23:00:00-04:00", "2026-10-15T05:00:00-04:00"),
    ("2026-10-31T23:00:00-04:00", "2026-11-01T05:00:00-05:00"),
    ("2026-03-07T23:00:00-05:00", "2026-03-08T05:00:00-04:00"),
])
def test_next_wake_includes_each_break_and_dst(now, wake):
    local = datetime.fromisoformat(now).astimezone(TORONTO)
    assert hours.next_wake(local) == datetime.fromisoformat(wake)


@pytest.mark.parametrize("hour,minute", [(9, 30), (13, 0), (20, 0), (23, 0)])
def test_closing_each_window_stops_queued_jobs_and_writes(monkeypatch, hour, minute):
    clock(monkeypatch, datetime(2026, 10, 14, hour, minute, tzinfo=TORONTO))
    ran = []
    hours.awake_job(lambda: ran.append(True))()
    assert not ran
    with pytest.raises(hours.OutsideActiveHours):
        hours.require_active()
    for action in (ag.POST, ag.QUOTE, ag.REPLY, ag.RETWEET):
        assert not ag.can_post(action)[0]


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
    clock(monkeypatch, datetime(2026, 9, 20, 23, 30, tzinfo=TORONTO))
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
