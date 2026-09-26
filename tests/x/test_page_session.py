"""The page session (issue #253): it holds the Safari lock, closes each tab
it opened on every path, reads nothing when its page does not open, and a
nested session opens and closes nothing."""
import threading
from types import SimpleNamespace

import pytest

from src.guards.active_hours import OutsideActiveHours
from src.x import page_session, safari
from src.x.page_session import PageNotOpened
from tests.helpers import stop_requested

PROFILE = "https://x.com/TheAIShrink"


class Boom(Exception):
    pass


def _follower_count():
    from src.account import follower_tracker_bot
    return follower_tracker_bot._scrape_follower_count()


# Every session migrated to the page session: its run, and the one page it
# opens. Issues #254 and #255 add theirs.
MIGRATED = {
    "follower_count": (_follower_count, PROFILE),
}


@pytest.mark.parametrize("name", MIGRATED)
def test_a_session_closes_its_tab_once_on_the_nominal_path(memory_page, name):
    run, url = MIGRATED[name]
    memory_page.pages[url] = ["1"]
    run()
    assert memory_page.opened == [url]
    assert memory_page.closed == 1


@pytest.mark.parametrize("name", MIGRATED)
def test_a_session_closes_its_tab_once_when_a_read_raises(memory_page, name):
    run, url = MIGRATED[name]
    memory_page.pages[url] = [Boom("page script crashed")]
    try:
        run()
    except Boom:
        pass
    assert memory_page.scripts, "the scripted read raised"
    assert memory_page.closed == 1


@pytest.mark.parametrize("name", MIGRATED)
def test_a_session_reads_nothing_when_its_page_does_not_open(memory_page, name):
    run, url = MIGRATED[name]
    with pytest.raises(PageNotOpened):
        run()
    assert memory_page.opened == [url]
    assert (memory_page.scripts, memory_page.scrolls, memory_page.pressed) == ([], 0, [])
    assert memory_page.closed == 1, "a timed-out open may have opened its page"


def test_a_nested_session_opens_and_closes_nothing(memory_page):
    memory_page.pages[PROFILE] = ["outer", "inner"]
    with page_session.session("OUTER") as outer:
        outer.open(PROFILE)
        with page_session.session("INNER") as inner:
            inner.open("https://x.com/elsewhere")
            assert inner.run_js("1") == "outer"
        assert memory_page.closed == 0
        assert outer.run_js("1") == "inner"
    assert memory_page.opened == [PROFILE]
    assert memory_page.closed == 1


def test_a_session_that_opens_nothing_closes_nothing(memory_page):
    with page_session.session("READ") as page:
        page.run_js("1")
    assert memory_page.closed == 0


def test_a_session_holds_the_safari_lock(memory_page):
    memory_page.pages[PROFILE] = []

    def free():
        got = safari._safari_lock._lock.acquire(blocking=False)
        if got:
            safari._safari_lock._lock.release()
        seen.append(got)

    seen = []
    with page_session.session("LOCK") as page:
        page.open(PROFILE)
        worker = threading.Thread(target=free)
        worker.start()
        worker.join()
    free()
    assert seen == [False, True]


def test_open_waits_for_the_page_and_the_session_tags_its_scripts(memory_page):
    memory_page.pages[PROFILE] = []
    with page_session.session("TAG") as page:
        page.open(PROFILE, settle_s=7)
        page.scroll(2)
        page.run_js("1", 20, activate=True)
    assert memory_page.waits == [7]
    assert memory_page.scrolls == 2
    script = memory_page.scripts[0]
    assert (script.url, script.timeout_s, script.log_prefix, script.activate) \
        == (PROFILE, 20, "[TAG]", True)


def test_read_json_parses_the_answer_and_gives_none_otherwise(memory_page):
    memory_page.pages[PROFILE] = ['{"handles": ["a"]}', "", "{not json"]
    with page_session.session("JSON") as page:
        page.open(PROFILE)
        assert page.read_json("1") == {"handles": ["a"]}
        assert page.read_json("1") is None
        assert page.read_json("1") is None


def test_a_stop_at_the_lock_opens_nothing(memory_page, monkeypatch):
    stop_requested(monkeypatch)
    with pytest.raises(OutsideActiveHours), page_session.session("SLEEP") as page:
        page.open(PROFILE)
    assert memory_page.opened == []


# The Safari adapter, over the walled primitives.

@pytest.fixture
def primitives(monkeypatch):
    calls = []
    monkeypatch.setattr(safari, "open_url", lambda url: calls.append(("open", url)) or True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: calls.append(("close",)))
    monkeypatch.setattr(safari, "_scroll_page", lambda: calls.append(("scroll",)))
    monkeypatch.setattr(page_session.time, "sleep", lambda s: calls.append(("sleep", s)))

    def run_js(js, timeout_s=15, **kwargs):
        calls.append(("js", timeout_s, kwargs))
        return "42"
    monkeypatch.setattr(safari, "_run_js", run_js)
    monkeypatch.setattr(safari, "_run_applescript",
                        lambda script, **kwargs: calls.append(("keys", kwargs)) or True)
    return SimpleNamespace(calls=calls, monkeypatch=monkeypatch)


def test_the_safari_adapter_drives_the_safari_primitives(primitives):
    with page_session.session("SAFARI") as page:
        page.open(PROFILE, settle_s=7)
        page.scroll()
        assert page.run_js("1", 20, activate=True) == "42"
        assert page.keys('tell application "System Events" to keystroke tab')
    assert primitives.calls == [
        ("open", PROFILE), ("sleep", 7), ("scroll",),
        ("js", 20, {"log_prefix": "[SAFARI]", "activate": True, "raise_timeout": False}),
        ("keys", {"timeout_s": safari.KEYSTROKE_TIMEOUT_S}),
        ("close",)]


def test_bedtime_at_the_close_leaves_the_tab_open(primitives):
    """Today's behaviour, kept until the Operator decides (issue #250): the
    close goes through `_run_applescript`, which refuses after bedtime, so
    the tab stays open until the next Safari restart."""
    def asleep():
        raise OutsideActiveHours("Bot asleep")
    primitives.monkeypatch.setattr(safari, "close_front_tab", asleep)
    with pytest.raises(OutsideActiveHours), page_session.session("SAFARI") as page:
        page.open(PROFILE)
    assert primitives.calls == [("open", PROFILE)]


def test_without_a_memory_page_a_session_hits_the_wall():
    with (pytest.raises(AssertionError, match="TEST TRIED TO DRIVE SAFARI"),
          page_session.session("WALL") as page):
        page.open(PROFILE)
