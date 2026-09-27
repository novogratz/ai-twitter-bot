"""The page session (issue #253): it holds the Safari lock, closes each tab
it opened on every path, reads nothing when its page does not open, and a
nested session opens and closes nothing and reads only the page asked."""
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from src.guards.active_hours import OutsideActiveHours
from src.x import page_session, safari
from src.x.page_session import PageNotOpened
from src.x.twitter_client import LikeOutcome
from tests.helpers import stop_requested

PROFILE = "https://x.com/TheAIShrink"
SEARCH = "https://x.com/search?q=AI"
THEIR_PROFILE = "https://x.com/TheBTCTherapist"
FOLLOWERS = "https://x.com/TheAIShrink/followers"


class Boom(Exception):
    pass


def _follower_count():
    from src.account import follower_tracker_bot
    return follower_tracker_bot._scrape_follower_count()


def _search_likes():
    from src.x import twitter_client
    return twitter_client.like_search_posts(SEARCH, 3, 60)


def _profile_likes():
    from src.x import twitter_client
    return twitter_client.visit_profile_and_like("TheBTCTherapist", like_count=2)


def _reply_likes():
    from src.x import twitter_client
    return twitter_client.like_own_tweet_replies()


def _followback():
    from src.account import followback_bot
    return followback_bot.run_followback_cycle()


def _scrape(name, *args, **kwargs):
    def run():
        from src.x import scraper
        return getattr(scraper, name)(*args, **kwargs)
    return run


def _no_posts(page):
    return [json.dumps({"page": page, "posts": []})]


NO_READ = object()
WALK_FAILED = [LikeOutcome.FAILED]


@dataclass
class Migrated:
    """A session on the page session: its run, the one page it opens, that
    page's answers on the nominal path, and what the run gives when the page
    does not open and when a read raises `Boom`, an exception class meaning
    that it raises it (`NO_READ`: the session runs no script)."""
    run: Callable
    url: str
    answers: list
    not_opened: object = PageNotOpened
    crashed: object = Boom


# Every session migrated to the page session. The like walks (#255) report a
# page that did not open as [FAILED], and list the posts of a page they
# accept: any other answer takes that path. A scrape gives its failure answer
# when its page does not open, and the tweet scrapes count a crashed read as
# a blank page (#254).
MIGRATED = {
    "follower_count": Migrated(_follower_count, PROFILE, ["1"]),
    "search_likes": Migrated(_search_likes, SEARCH, _no_posts(SEARCH), WALK_FAILED),
    "profile_likes": Migrated(_profile_likes, THEIR_PROFILE, _no_posts(THEIR_PROFILE),
                              WALK_FAILED),
    "reply_likes": Migrated(_reply_likes, PROFILE,
                            _no_posts("https://x.com/TheAIShrink/status/2063500000000000301"),
                            WALK_FAILED),
    "followback": Migrated(_followback, FOLLOWERS, ["1"]),
    "refresh_feed": Migrated(_scrape("refresh_feed"), "https://x.com/home", [], None, NO_READ),
    "profile_tweets": Migrated(_scrape("scrape_profile_tweets", "TheAIShrink"), PROFILE,
                               ["[]"], [], []),
    "mentions": Migrated(_scrape("scrape_mentions"), "https://x.com/notifications/mentions",
                         ["[]"], [], []),
    "home_feed": Migrated(_scrape("scrape_home_feed"), "https://x.com/home", ["[]"], [], []),
    "following_feed": Migrated(_scrape("scrape_following_feed"), "https://x.com/home",
                               ["CLICKED", "[]"], []),
    "x_search": Migrated(_scrape("scrape_x_search", "ai"),
                         "https://x.com/search?q=ai&src=typed_query&f=top", ["[]"], [], []),
    "own_replies": Migrated(_scrape("scrape_own_tweet_and_replies"), PROFILE, ["{}"], None),
}


@pytest.fixture(autouse=True)
def _no_blank_run():
    """A crashed tweet read counts a blank page: no count outlives its test."""
    from src.x import scraper
    scraper._reset_blank_page_count()
    yield
    scraper._reset_blank_page_count()


def _gives(run, expected):
    if isinstance(expected, type) and issubclass(expected, BaseException):
        with pytest.raises(expected):
            run()
    else:
        assert run() == expected


@pytest.mark.parametrize("name", MIGRATED)
def test_a_session_closes_its_tab_once_on_the_nominal_path(memory_page, name):
    migrated = MIGRATED[name]
    memory_page.pages[migrated.url] = list(migrated.answers)
    result = migrated.run()
    if migrated.not_opened == WALK_FAILED:
        assert result == [], "the walk accepted its listed page"
    assert memory_page.opened == [migrated.url]
    assert memory_page.closed == 1


@pytest.mark.parametrize("name", [name for name, m in MIGRATED.items() if m.crashed is not NO_READ])
def test_a_session_closes_its_tab_once_when_a_read_raises(memory_page, name):
    migrated = MIGRATED[name]
    memory_page.pages[migrated.url] = [Boom("page script crashed")]
    _gives(migrated.run, migrated.crashed)
    assert memory_page.scripts, "the scripted read raised"
    assert memory_page.closed == 1


@pytest.mark.parametrize("name", MIGRATED)
def test_a_session_reads_nothing_when_its_page_does_not_open(memory_page, name):
    migrated = MIGRATED[name]
    memory_page.pages["https://x.com/front"] = ["front tab"]
    memory_page.front = "https://x.com/front"
    _gives(migrated.run, migrated.not_opened)
    assert memory_page.opened == [migrated.url]
    assert (memory_page.scripts, memory_page.scrolls, memory_page.pressed) == ([], 0, [])
    assert memory_page.closed == 1, "a timed-out open may have opened its page"


def test_a_page_caught_not_opening_still_reads_nothing(memory_page):
    memory_page.pages["https://x.com/front"] = ["front tab"]
    memory_page.front = "https://x.com/front"
    with page_session.session("CAUGHT") as page:
        with pytest.raises(PageNotOpened):
            page.open(PROFILE)
        for act in (lambda: page.run_js("1"), lambda: page.read_json("1"),
                    lambda: page.keys("keystroke tab"), page.scroll):
            with pytest.raises(PageNotOpened):
                act()
    assert (memory_page.scripts, memory_page.scrolls, memory_page.pressed) == ([], 0, [])


def test_a_page_reads_again_once_an_open_succeeds(memory_page):
    memory_page.pages[PROFILE] = ["profile"]
    with page_session.session("RETRY") as page:
        with pytest.raises(PageNotOpened):
            page.open("https://x.com/missing")
        page.open(PROFILE)
        assert page.run_js("1") == "profile"
    assert memory_page.closed == 2


def test_a_nested_session_opens_and_closes_nothing(memory_page):
    memory_page.pages[PROFILE] = ["outer", "inner", "outer again"]
    with page_session.session("OUTER") as outer:
        outer.open(PROFILE)
        with page_session.session("INNER") as inner:
            assert inner.run_js("1") == "outer"
            inner.open(PROFILE.upper() + "/")
            assert inner.run_js("1") == "inner"
        assert memory_page.closed == 0
        assert outer.run_js("1") == "outer again"
    assert memory_page.opened == [PROFILE]
    assert memory_page.closed == 1


def test_a_nested_session_refuses_another_page(memory_page):
    memory_page.pages[PROFILE] = ["outer"]
    with page_session.session("OUTER") as outer:
        outer.open(PROFILE)
        with page_session.session("INNER") as inner:
            with pytest.raises(PageNotOpened):
                inner.open("https://x.com/elsewhere")
            with pytest.raises(PageNotOpened):
                inner.run_js("1")
        assert outer.run_js("1") == "outer"
    assert memory_page.opened == [PROFILE]


def test_a_nested_session_refuses_a_page_the_outer_did_not_open(memory_page):
    memory_page.pages["https://x.com/front"] = ["front tab"]
    memory_page.front = "https://x.com/front"
    with (page_session.session("OUTER"), page_session.session("INNER") as inner,
          pytest.raises(PageNotOpened)):
        inner.open(PROFILE)
    with page_session.session("OUTER") as outer:
        with pytest.raises(PageNotOpened):
            outer.open(PROFILE)
        with page_session.session("INNER") as inner:
            with pytest.raises(PageNotOpened):
                inner.open(PROFILE)
            with pytest.raises(PageNotOpened):
                inner.run_js("1")
    assert memory_page.scripts == []


def test_a_page_may_answer_as_a_function_of_the_script(memory_page):
    memory_page.pages[PROFILE] = lambda js: js.upper()
    with page_session.session("FUNCTION") as page:
        page.open(PROFILE)
        assert page.run_js("one") == "ONE"
        assert page.run_js("two") == "TWO"


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


def test_a_read_error_is_logged_before_the_close_can_replace_it(primitives):
    warnings = []
    primitives.monkeypatch.setattr(page_session.log, "warning",
                                   lambda msg, *a, **k: warnings.append(msg))

    def asleep():
        raise OutsideActiveHours("Bot asleep")
    primitives.monkeypatch.setattr(safari, "close_front_tab", asleep)
    with pytest.raises(OutsideActiveHours), page_session.session("SAFARI") as page:
        page.open(PROFILE)
        raise Boom("page script crashed")
    assert warnings == ["[SAFARI] Session failed, closing its tab: Boom: page script crashed"]


def test_without_a_memory_page_a_session_hits_the_wall():
    with (pytest.raises(AssertionError, match="TEST TRIED TO DRIVE SAFARI"),
          page_session.session("WALL") as page):
        page.open(PROFILE)
