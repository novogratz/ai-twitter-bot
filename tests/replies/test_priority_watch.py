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
def watched(monkeypatch, settings_override):
    settings_override(PRIORITY_WATCH_NOTIFICATIONS=False)
    monkeypatch.setattr(watch, "_retry_after", {})
    monkeypatch.setattr(watch, "_reply_retry_delays", {})
    monkeypatch.setattr(watch, "_action_retry_delays", {})
    monkeypatch.setattr(watch, "_pending", {})
    monkeypatch.setattr(watch, "_catchup_after", {})
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
    assert queries[0][1] == {"tab": "live", "max_tweets": 20, "text_limit": 1200, "scroll_passes": 3}
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


def test_fulfilled_actions_are_not_reopened_each_hour(watched, monkeypatch):
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
    assert [e[0] for e in watched] == ["replies"]


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


def test_new_notification_is_verified_and_handed_off_before_regular_search(watched, settings_override, monkeypatch):
    settings_override(PRIORITY_WATCH_NOTIFICATIONS=True)
    url, other = fresh("builder"), fresh("other", n=2)
    monkeypatch.setattr(scraper, "scrape_priority_notifications", lambda *a: [other, url])
    reads = []
    monkeypatch.setattr(tc, "read_priority_post", lambda target: reads.append(target) or
                        dict(url=target, text="The new SI model is here", likes=4, views=500))
    def search(*args, **kwargs):
        assert url in watch._pending
        return []
    monkeypatch.setattr(scraper, "scrape_x_search", search)
    watch.run_priority_watch_cycle()
    watch.run_priority_reply_cycle()
    watch.run_priority_watch_cycle()
    assert reads == [url]
    assert watched[-1][1] == [url]


@pytest.mark.parametrize("answered", [False, True])
def test_reply_exclusion_or_prior_reply_does_not_suppress_notification_actions(
        watched, settings_override, monkeypatch, answered):
    from src.guards import replied_store
    settings_override(PRIORITY_WATCH_NOTIFICATIONS=True)
    profile = replace(account.current(), reply_excluded_handles=("builder",))
    monkeypatch.setattr(account, "current", lambda: profile)
    url = fresh("builder")
    if answered:
        replied_store.claim(url)
    reads = []
    monkeypatch.setattr(scraper, "scrape_priority_notifications", lambda *a: [url])
    monkeypatch.setattr(tc, "read_priority_post", lambda target: reads.append(target) or
                        dict(url=target, text="New SI tools"))
    tick()
    tick()
    assert reads == [url]
    assert watched == [("like", url), ("repost", url)]
    assert bool(replied_store.load_replied()) is answered


def test_notification_discovery_still_refuses_blocked_accounts(watched, settings_override, monkeypatch):
    settings_override(PRIORITY_WATCH_NOTIFICATIONS=True)
    profile = account.current()
    profile = replace(profile, network=replace(profile.network, blocked_accounts=("builder",)))
    monkeypatch.setattr(account, "current", lambda: profile)
    monkeypatch.setattr(scraper, "scrape_priority_notifications", lambda *a: [fresh("builder")])
    monkeypatch.setattr(tc, "read_priority_post", lambda *a: pytest.fail("read blocked account"))
    tick()
    assert watched == []


@pytest.mark.parametrize("uncertain", [False, True])
def test_repost_spacing_waits_without_failure_backoff_or_blocking_likes(watched, monkeypatch, uncertain):
    from src.guards import action_guard, repost_store
    from tests.helpers import clock
    profile = replace(account.current(), watched_reposts_independent=True)
    monkeypatch.setattr(account, "current", lambda: profile)
    now = active_hours.now_local()
    clock(monkeypatch, now)
    first, second = fresh("builder", n=1), fresh("builder", n=2)
    if uncertain:
        assert repost_store.claim(first)
    else:
        action_guard.record(action_guard.WATCH_REPOST, first)
    watch.observe([dict(url=second, text="New SI tools")])
    watch.run_priority_actions_cycle()
    assert watched == [("like", second)]
    assert (second, "repost") not in watch._action_retry_delays
    clock(monkeypatch, now + timedelta(seconds=59))
    watch.run_priority_actions_cycle()
    assert watched == [("like", second)]
    clock(monkeypatch, now + timedelta(seconds=60))
    watch.run_priority_actions_cycle()
    assert watched == [("like", second), ("repost", second)]


def test_remembered_repost_is_not_dispatched_again_after_restart(watched):
    from src.guards import repost_store
    url = fresh("builder")
    repost_store.remember(url, "observed")
    watch.observe([dict(url=url, text="New SI tools")])
    watch.run_priority_actions_cycle()
    assert watched == [("like", url)]


def test_refused_actions_back_off_exponentially_without_delaying_new_posts(watched, monkeypatch):
    url = fresh("builder")
    watch.observe([dict(url=url, text="New SI tools")])
    stamp, calls = [1000], []
    monkeypatch.setattr(watch.time, "monotonic", lambda: stamp[0])
    monkeypatch.setattr(tc, "like_priority_post", lambda url: calls.append(url) or tc.LikeOutcome.REFUSED)
    monkeypatch.setattr(tc, "repost_tweet", lambda url: tc.WriteOutcome.REFUSED)
    watch.run_priority_actions_cycle()
    assert watch._retry_after[(url, "like")] == 1300
    stamp[0] = 1300
    watch.run_priority_actions_cycle()
    assert watch._retry_after[(url, "like")] == 1900
    fresh_url = fresh("builder", n=1)
    watch.observe([dict(url=fresh_url, text="A new SI video model")])
    watch.run_priority_actions_cycle()
    assert calls == [url, url, fresh_url]


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


@pytest.mark.parametrize("maximum, delays", [(900, (60, 120, 240, 480, 900, 900)),
                                           (180, (60, 120, 180, 180))])
def test_repeated_reply_failures_back_off_across_polls_and_remain_retryable(watched, monkeypatch,
                                                                         settings_override, maximum, delays):
    from src.guards import replied_store
    settings_override(PRIORITY_WATCH_REPLY_RETRY_SECONDS=60, PRIORITY_WATCH_REPLY_RETRY_MAX_SECONDS=maximum)
    now = [1000]
    monkeypatch.setattr(watch.time, "monotonic", lambda: now[0])
    url = fresh("builder")
    post = {"url": url, "text": "New SI tools"}
    attempts = []
    def fail(job, candidates, cycle, **kwargs):
        attempts.append(candidates[0].url)
        cycle.tried.add(candidates[0].url)
        return 0
    monkeypatch.setattr(reply_pipeline, "run", fail)
    watch.observe([post])
    watch.run_priority_reply_cycle()
    for count, delay in enumerate(delays, start=1):
        now[0] += delay - 1
        # Rediscovering the same post must not reset its growing cooldown.
        watch.observe([post])
        watch.run_priority_reply_cycle()
        assert len(attempts) == count
        now[0] += 1
        watch.run_priority_reply_cycle()
        assert len(attempts) == count + 1
    assert not replied_store.load_replied(), "a cooldown is never a permanent Reply claim"
    watch.run_priority_actions_cycle()
    assert watched == [("like", url), ("repost", url)], "Reply backoff must not delay other actions"


def test_reply_backoff_memory_is_pruned_with_discoveries(watched, settings_override):
    settings_override(PRIORITY_WATCH_QUEUE_LIMIT=1)
    older, newer = fresh("builder", minutes=2), fresh("builder", minutes=1)
    watch.observe([{"url": older, "text": "SI tools"}])
    watch._backoff_reply(older)
    watch.observe([{"url": newer, "text": "New SI tools"}])
    # Also cover a generation finishing after its parent left the bounded queue.
    watch._backoff_reply(older)
    assert watch._reply_retry_delays == {}
    assert (older, "reply") not in watch._retry_after
    assert watch._ready(newer, "reply")


def test_reply_backoff_preserves_a_longer_configured_retry(watched, settings_override):
    settings_override(PRIORITY_WATCH_REPLY_RETRY_SECONDS=1800)
    url = fresh("builder")
    watch.observe([{"url": url, "text": "SI tools"}])
    for _ in range(2):
        watch._backoff_reply(url)
        assert watch._reply_retry_delays[url] == 1800


pytestmark = pytest.mark.usefixtures("open_topic_account")
