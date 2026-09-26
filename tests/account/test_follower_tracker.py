"""follower_tracker_job reads the Account's follower count through a page
session (issue #253), on a memory page: no Safari primitive, no sleep."""
import os

import pytest

from src.account import follower_tracker_bot as tracker
from src.guards.active_hours import OutsideActiveHours
from src.guards.follow_policy import FOLLOWER_HISTORY
from src.x.page_session import PageNotOpened

PROFILE = "https://x.com/TheAIShrink"


def test_it_reads_the_profile_with_its_timeout_prefix_and_activate(memory_page):
    memory_page.pages[PROFILE] = ["1,234"]

    assert tracker._scrape_follower_count() == 1234
    assert memory_page.opened == [PROFILE]
    assert memory_page.waits == [7]
    [script] = memory_page.scripts
    assert (script.url, script.timeout_s, script.log_prefix, script.activate) \
        == (PROFILE, 20, "[FOLLOWER]", True)
    assert 'a[href$="/followers"]' in script.js
    assert memory_page.closed == 1


def test_a_cycle_appends_the_count_to_the_history(memory_page):
    memory_page.pages[PROFILE] = ["1.2K", "1.5K"]

    tracker.run_follower_tracker_cycle()
    tracker.run_follower_tracker_cycle()
    assert [row["count"] for row in FOLLOWER_HISTORY.read()] == [1200, 1500]


@pytest.mark.parametrize("answer", ["", "1.2.3"])
def test_a_failed_or_unparsable_read_saves_nothing(memory_page, answer):
    memory_page.pages[PROFILE] = [answer]

    assert tracker._scrape_follower_count() == 0
    tracker.run_follower_tracker_cycle()
    assert FOLLOWER_HISTORY.read() == []


def test_a_profile_that_does_not_open_is_a_failed_cycle(memory_page, monkeypatch):
    """The count used to be read from whatever profile was in front."""
    from src.core import health

    failures = []
    monkeypatch.setattr(health, "record_failure", lambda label="", exc=None: failures.append(label))
    with pytest.raises(PageNotOpened):
        tracker._scrape_follower_count()
    tracker.safe_run_follower_tracker_cycle()
    assert memory_page.scripts == []
    assert failures == ["follower_tracker"]
    assert FOLLOWER_HISTORY.read() == []


def test_bedtime_reaches_the_job_and_is_not_a_safari_failure(memory_page, monkeypatch):
    """Bedtime raised by the page script reaches the job's `except
    Exception`, which must not count it toward a Safari restart."""
    from src.core import health

    restarts = []
    monkeypatch.setattr(health, "_restart_safari", lambda: restarts.append(1) or True)
    memory_page.pages[PROFILE] = [OutsideActiveHours("Bot asleep")]
    with pytest.raises(OutsideActiveHours):
        tracker._scrape_follower_count()
    for _ in range(health.RECOVERY_THRESHOLD + 1):
        memory_page.pages[PROFILE] = [OutsideActiveHours("Bot asleep")]
        tracker.safe_run_follower_tracker_cycle()
    assert restarts == []
    assert not os.path.exists(health.HEALTH.path), "the failure counter is left alone"


def test_a_test_without_a_memory_page_fails_on_the_wall():
    with pytest.raises(AssertionError, match="TEST TRIED TO DRIVE SAFARI"):
        tracker._scrape_follower_count()
