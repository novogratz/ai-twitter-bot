"""src/guards/active_hours: Waking hours, DST, bedtime and stop requests."""
from datetime import datetime

import pytest

from src.guards import action_guard as ag, active_hours as hours
from tests.helpers import TORONTO, stop_requested, clock


@pytest.mark.parametrize("hour,minute,awake", [
    (4,59,False),(5,0,True),(9,59,True),(10,0,False),
    (13,59,False),(14,0,True),(14,59,True),(15,0,False),
    (16,59,False),(17,0,True),(18,59,True),(19,0,False),
    (21,59,False),(22,0,True),(23,59,True),(0,0,False),
])
@pytest.mark.parametrize("day", [(2026,9,20),(2026,11,1),(2026,3,8)])
def test_exact_waking_boundaries_and_dst(hour, minute, awake, day):
    assert hours.is_active(datetime(*day, hour, minute, tzinfo=TORONTO)) is awake


def test_next_window_and_midnight(monkeypatch):
    now = datetime(2026,9,20,10,tzinfo=TORONTO)
    assert hours.next_wake(now) == now.replace(hour=14)
    clock(monkeypatch, now.replace(hour=14,minute=30))
    assert hours.seconds_until_bedtime() == 1800
    clock(monkeypatch, now.replace(hour=23))
    assert hours.seconds_until_bedtime() == 3600
    assert hours.next_wake(now.replace(hour=23)).day == 21


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
    clock(monkeypatch, datetime(2026, 10, 14, 18, 30, tzinfo=TORONTO))

    assert hours.today_iso() == "2026-10-14"
    assert hours.is_past_day(stamped) is past


def test_night_rejects_all_posting_and_queued_jobs(monkeypatch):
    clock(monkeypatch, datetime(2026, 9, 20, 10, 0, tzinfo=TORONTO))
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
