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
    monkeypatch.setattr(watch, "_retry_after", {})
    monkeypatch.setattr(watch, "_pending", {})
    monkeypatch.setattr(watch.watch_discovery, "_tweets", {})
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
    tick()
    assert queries[0][0] == "from:builder -filter:replies -filter:retweets"
    assert queries[0][1] == {"tab": "live", "max_tweets": 20, "text_limit": 1200, "scroll_passes": 0}
    assert watched == [("like", original), ("repost", original),
                       ("replies", [original], {"max_generations": 1})]


def test_first_enable_sets_a_boundary_and_restart_keeps_it(watched, monkeypatch):
    watch.STATE.write({})
    monkeypatch.setenv("DRY_RUN", "0")
    now = active_hours.now_local()
    monkeypatch.setattr(active_hours, "now_local", lambda: now)
    before = now.isoformat()
    tick()
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
    tick()


def test_like_failure_does_not_hide_repost_or_reply(watched, monkeypatch):
    url = fresh("builder")
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **kw: [{"url": url, "text": "New tools"}])
    def fail(url):
        raise RuntimeError("like failed")
    monkeypatch.setattr(tc, "like_priority_post", fail)
    tick()
    assert watched == [("repost", url), ("replies", [url], {"max_generations": 1})]


@pytest.mark.parametrize("data", [{"builder": "bad"}, {"builder": "2026-10-23T12:00:00"}])
def test_malformed_watch_state_stops_before_browser(watched, monkeypatch, data):
    watch.STATE.write(data)
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **kw: pytest.fail("read with corrupt state"))
    with pytest.raises(StateUnreadable):
        tick()


def test_break_stops_watch_before_discovery(watched, monkeypatch):
    monkeypatch.setattr(active_hours, "break_until", lambda *a: active_hours.now_local())
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **kw: pytest.fail("read during break"))
    with pytest.raises(active_hours.ScheduledBreak):
        tick()


def test_refused_actions_back_off_without_hiding_replies(watched, monkeypatch):
    url = fresh("builder")
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **kw: [{"url": url, "text": "Yes"}])
    monkeypatch.setattr(watch.time, "monotonic", lambda: 1000)
    tick()
    watched.clear()
    tick()
    assert watched == [("replies", [url], {"max_generations": 1})]
    monkeypatch.setattr(watch.time, "monotonic", lambda: 5000)
    watched.clear()
    tick()
    assert [e[0] for e in watched] == ["like", "repost", "replies"]


def test_many_posts_do_not_delay_replies_behind_forty_page_visits(watched, monkeypatch):
    posts = [{"url": fresh("builder", n=i), "text": "New SI video tools"} for i in range(20)]
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **kw: posts)
    tick()
    assert len([e for e in watched if e[0] != "replies"]) == 4
    assert len(watched[-1][1]) == 20


def tick():
    watch.run_priority_watch_cycle()
    watch.run_priority_actions_cycle()
    watch.run_priority_reply_cycle()


def test_discovery_does_not_wait_for_a_model_or_actions(watched, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    older = fresh("builder", minutes=2)
    newer = fresh("builder", minutes=1)
    started, release = threading.Event(), threading.Event()
    watch.observe([{"url": older, "text": "A new SI model"}])
    def generate(job, candidates, cycle, **kw):
        started.set()
        assert release.wait(2)
    monkeypatch.setattr(reply_pipeline, "run", generate)
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **kw:
                        [{"url": newer, "text": "A newer SI model"}])
    with ThreadPoolExecutor(1) as pool:
        job = pool.submit(watch.run_priority_reply_cycle)
        assert started.wait(2)
        try:
            watch.run_priority_watch_cycle()
            assert watched == [], "discovery ran an action"
            watch.run_priority_actions_cycle()
            assert watched[:2] == [("like", newer), ("repost", newer)]
            assert list(watch._pending) == [newer, older]
        finally:
            release.set()
            job.result(2)


def test_feed_handoff_reaches_dispatch_without_another_poll(watched, monkeypatch):
    url = fresh("builder")
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **kw: pytest.fail("unexpected search"))
    watch.watch_discovery.offer([{"url": url, "text": "Look at this SI video"}])
    watch.run_priority_actions_cycle()
    watch.run_priority_reply_cycle()
    assert watched == [("like", url), ("repost", url),
                       ("replies", [url], {"max_generations": 1})]


def test_queue_bounds_keep_newest_originals_without_claiming_them(watched, settings_override):
    from src.guards import replied_store
    settings_override(PRIORITY_WATCH_QUEUE_LIMIT=2)
    urls = [fresh("builder", minutes=i) for i in range(1, 5)]
    watch.watch_discovery.offer([{"url": u, "text": "SI tools"} for u in urls])
    assert len(watch.watch_discovery._tweets) == 2
    watch.run_priority_reply_cycle()
    assert list(watch._pending) == urls[:2]
    assert not replied_store.load_replied()


def test_pending_dispatch_refuses_corrupt_boundaries_or_break(watched, monkeypatch):
    url = fresh("builder")
    watch.observe([{"url": url, "text": "New SI tools"}])
    watch.STATE.write({"builder": "bad"})
    with pytest.raises(StateUnreadable):
        watch.run_priority_actions_cycle()
    with pytest.raises(StateUnreadable):
        watch.run_priority_reply_cycle()
    assert watched == []
    monkeypatch.setattr(active_hours, "break_until", lambda *a: active_hours.now_local())
    with pytest.raises(active_hours.ScheduledBreak):
        watch.run_priority_reply_cycle()
    assert watched == []


def test_reply_retry_backoff_does_not_hide_a_newer_discovery(watched, monkeypatch, settings_override):
    settings_override(PRIORITY_WATCH_REPLY_RETRY_SECONDS=45)
    now = [1000]
    monkeypatch.setattr(watch.time, "monotonic", lambda: now[0])
    older, newer = fresh("builder", minutes=2), fresh("builder", minutes=1)
    attempted = []
    def fail(job, candidates, cycle, **kwargs):
        attempted.append(candidates[0].url)
        cycle.tried.add(candidates[0].url)
        return 0
    monkeypatch.setattr(reply_pipeline, "run", fail)
    watch.observe([{"url": older, "text": "SI video tools"}])
    watch.run_priority_reply_cycle()
    now[0] += 1
    watch.run_priority_reply_cycle()
    assert attempted == [older]
    watch.observe([{"url": newer, "text": "New SI video tools"}])
    watch.run_priority_reply_cycle()
    assert attempted == [older, newer]
    now[0] = 1045
    watch.run_priority_reply_cycle()
    assert attempted == [older, newer, older]
