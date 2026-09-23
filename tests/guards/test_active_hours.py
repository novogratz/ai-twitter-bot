"""src/guards/active_hours: Waking hours, DST, bedtime and stop requests."""
from datetime import datetime

import pytest

from src.guards import action_guard as ag, active_hours as hours
from tests.helpers import TORONTO, stop_requested, clock


@pytest.mark.parametrize("when,awake", [
    ("2026-09-20T04:29:59-04:00", False),
    ("2026-09-20T04:30:00-04:00", True),
    ("2026-09-20T21:59:59-04:00", True),
    ("2026-09-20T22:00:00-04:00", False),
    ("2026-09-21T00:00:00-04:00", False),
    ("2026-11-01T09:29:59+00:00", False),
    ("2026-11-01T09:30:00+00:00", True),
    ("2026-03-08T08:29:59+00:00", False),
    ("2026-03-08T08:30:00+00:00", True),
])
def test_exact_waking_boundaries_and_dst(when, awake):
    assert hours.is_active(datetime.fromisoformat(when)) is awake


def test_night_rejects_all_posting_and_queued_jobs(monkeypatch):
    clock(monkeypatch, datetime(2026, 9, 20, 22, tzinfo=TORONTO))
    called = []
    hours.awake_job(lambda: called.append(True))()
    assert not called
    for action in (ag.POST, ag.QUOTE, ag.REPLY, ag.RETWEET):
        assert not ag.can_post(action, urgent=True, high_value=True)[0]


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
