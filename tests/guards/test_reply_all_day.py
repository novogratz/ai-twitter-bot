"""The restored pipeline can work overnight without opening other write lanes."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime

import pytest

from src.guards import active_hours as hours, action_guard as guard
from tests.helpers import TORONTO, clock


@pytest.mark.parametrize("hour,minute", [(0, 0), (2, 30), (4, 29), (12, 0), (23, 59)])
def test_all_day_reply_hours_still_respect_stop(monkeypatch, settings_override, hour, minute):
    clock(monkeypatch, datetime(2026, 11, 19, hour, minute, tzinfo=TORONTO))
    settings_override(REPLY_ALL_DAY=True)
    assert hours.may_reply()
    with hours.reply_activity():
        hours.require_active()
        assert hours.seconds_until_pause() > 600
        monkeypatch.setattr(hours, "stop_requested", lambda: True)
        assert not hours.may_reply()
        assert hours.seconds_until_pause() == 0
        with pytest.raises(hours.OutsideActiveHours):
            hours.require_active()


def test_only_reply_io_and_required_parent_likes_receive_overnight_scope(monkeypatch, settings_override, memory_ledger):
    clock(monkeypatch, datetime(2026, 11, 19, 2, tzinfo=TORONTO))
    settings_override(REPLY_ALL_DAY=True)
    assert not hours.may_act()
    with pytest.raises(hours.OutsideActiveHours):
        hours.require_active()
    with hours.reply_activity():
        hours.require_active()
        assert guard.can_post(guard.REPLY)[0]
        assert guard.can_post(guard.LIKE, reply_parent=True)[0]
        assert not guard.can_post(guard.LIKE)[0]
        assert not guard.can_post(guard.FOLLOW)[0]
        assert not guard.can_post(guard.POST)[0]
        assert not guard.can_post(guard.RETWEET)[0]
        with ThreadPoolExecutor(1) as pool:
            assert pool.submit(copy_context().run, hours.require_active).result() is None
    with pytest.raises(hours.OutsideActiveHours):
        hours.require_active()


def test_queued_reply_job_runs_overnight_but_ordinary_job_waits(monkeypatch, settings_override):
    clock(monkeypatch, datetime(2026, 11, 19, 1, tzinfo=TORONTO))
    settings_override(REPLY_ALL_DAY=True)
    calls = []

    def job():
        hours.require_active()
        calls.append(True)

    hours.awake_job(job)()
    assert calls == []
    hours.awake_job(job, reply=True)()
    assert calls == [True]
    monkeypatch.setattr(hours, "stop_requested", lambda: True)
    hours.awake_job(job, reply=True)()
    assert calls == [True]
