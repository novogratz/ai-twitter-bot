"""The operator-picked watcher sees new originals and independently attempts each action."""
from dataclasses import replace
from datetime import timedelta

import pytest

from src.core import account
from src.core.state_errors import StateUnreadable
from src.guards import active_hours
from src.replies import priority_watch as watch, reply_pipeline
from src.x import scraper, twitter_client as tc
from tests.helpers import fresh


@pytest.fixture
def watched(monkeypatch):
    profile = replace(account.current(), auto_engage_handles=("builder",))
    monkeypatch.setattr(account, "current", lambda: profile)
    watch.STATE.write({"builder": (active_hours.now_local() - timedelta(days=1)).isoformat()})
    events = []
    monkeypatch.setattr(tc, "like_priority_post", lambda url: events.append(("like", url)) or tc.LikeOutcome.LIKED)
    monkeypatch.setattr(tc, "repost_tweet", lambda url: events.append(("repost", url)) or tc.WriteOutcome.SHIPPED)
    monkeypatch.setattr(reply_pipeline, "run", lambda job, candidates, cycle, **kw:
                        events.append(("replies", [c.url for c in candidates], kw)) or 0)
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **kw: [])
    return events


def test_watch_reads_latest_and_acts_only_on_new_originals(watched, monkeypatch):
    original, comment, other, old = (fresh("builder", n=1), fresh("builder", n=2),
                                      fresh("other", n=3), fresh("builder", minutes=1500, n=4))
    queries = []
    def search(query, **kw):
        queries.append((query, kw))
        return [{"url": original, "text": "A new Starship launch is coming"},
                {"url": original, "text": "same post"},
                {"url": comment, "text": "a comment", "is_reply": True},
                {"url": other, "text": "not this author"},
                {"url": old, "text": "an old post"}]
    monkeypatch.setattr(scraper, "scrape_x_search", search)
    watch.run_priority_watch_cycle()
    assert queries[0][0] == "from:builder -filter:replies -filter:retweets"
    assert queries[0][1] == {"tab": "live", "max_tweets": 20, "text_limit": 1000}
    assert watched == [("like", original), ("repost", original),
                       ("replies", [original], {"max_generations": 2})]


def test_first_enable_sets_a_boundary_and_restart_keeps_it(watched, monkeypatch):
    watch.STATE.write({})
    monkeypatch.setenv("DRY_RUN", "0")
    now = active_hours.now_local()
    monkeypatch.setattr(active_hours, "now_local", lambda: now)
    before = now.isoformat()
    watch.run_priority_watch_cycle()
    assert watch.STATE.read() == {"builder": before}
    monkeypatch.setattr(active_hours, "now_local", lambda: pytest.fail("boundary was reset"))
    # Reading existing boundaries never consults the clock or replaces them.
    assert watch._start_times(("builder",))["builder"].isoformat() == before


def test_pre_activation_post_is_excluded_even_when_recent(watched):
    url = fresh("builder", minutes=1)
    from src.x.x_urls import posted_at
    assert watch._candidates("builder", [{"url": url, "text": "A new post"}],
                             posted_at(url) + timedelta(seconds=1)) == []


def test_disabled_watch_does_nothing(monkeypatch):
    profile = replace(account.current(), auto_engage_handles=())
    monkeypatch.setattr(account, "current", lambda: profile)
    monkeypatch.setattr(watch.STATE, "read", lambda: pytest.fail("read disabled watch state"))
    watch.run_priority_watch_cycle()


def test_like_failure_does_not_hide_repost_or_reply(watched, monkeypatch):
    url = fresh("builder")
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **kw: [{"url": url, "text": "New tools"}])
    def fail(url):
        raise RuntimeError("like failed")
    monkeypatch.setattr(tc, "like_priority_post", fail)
    watch.run_priority_watch_cycle()
    assert watched == [("repost", url), ("replies", [url], {"max_generations": 2})]


@pytest.mark.parametrize("data", [{"builder": "bad"}, {"builder": "2026-10-23T12:00:00"}])
def test_malformed_watch_state_stops_before_browser(watched, monkeypatch, data):
    watch.STATE.write(data)
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **kw: pytest.fail("read with corrupt state"))
    with pytest.raises(StateUnreadable):
        watch.run_priority_watch_cycle()


def test_break_stops_watch_before_discovery(watched, monkeypatch):
    monkeypatch.setattr(active_hours, "break_until", lambda *a: active_hours.now_local())
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **kw: pytest.fail("read during break"))
    with pytest.raises(active_hours.ScheduledBreak):
        watch.run_priority_watch_cycle()
