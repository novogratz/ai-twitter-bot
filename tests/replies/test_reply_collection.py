"""Fresh broad discovery leaves browser time for independently approved Replies."""
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from src.core import account, reply_queue, reply_style
from src.core.state_errors import StateUnreadable
from src.guards import active_hours
from src.replies import direct_reply as direct, early_bird_bot as early, feed_sweeper_bot as feed
from src.replies import mega_watch_bot as mega, reply_pipeline as pipeline
from src.x import scraper, twitter_client
from tests.helpers import fresh


PARENT = "AI inference benefits from memory bandwidth."


@pytest.fixture
def drafting(monkeypatch, llm):
    llm.default = "Bandwidth matters."
    monkeypatch.setattr(reply_style, "choose_length", lambda: reply_style.Length.FULL)
    monkeypatch.setattr(reply_style, "choose_smiley", lambda: False)
    monkeypatch.setattr(twitter_client, "reply_to_tweet", lambda *a, **k: pytest.fail("collector published"))
    return llm


@pytest.mark.parametrize("likes", [0, 1, 2, 3, None, "3"])
def test_latest_queries_use_the_shared_three_like_floor_without_an_author_gate(likes):
    queries = account.current().searches.replies
    assert queries
    for query in queries:
        assert not any(term in query for term in ("min_faves:", "min_replies:", "min_retweets:", "from:"))
        assert "-filter:replies" in query
    tweet = {"url": fresh("newbuilder"), "text": PARENT, "likes": likes}
    expected = [tweet["url"]] if likes == 3 else []
    assert [c.url for c in direct._search_candidates([tweet], queries[0])] == expected


def test_regular_queries_use_latest_and_popular_queries_use_top(monkeypatch, settings_override):
    loaded = account.current()
    searches = replace(loaded.searches, replies=("AI recent one", "SI recent two"), hot_tab=("AI popular",))
    monkeypatch.setattr(account, "current", lambda: replace(loaded, searches=searches))
    settings_override(VIP_SCAN_HANDLES="", DIRECT_REPLY_QUERIES_PER_CYCLE=3)
    monkeypatch.setattr(direct.random, "shuffle", lambda rows: None)
    calls = []
    monkeypatch.setattr(direct, "scrape_x_search", lambda query, **k: calls.append((query, k["tab"])) or [])
    direct.run_direct_reply_cycle()
    assert calls == [("AI recent one", "latest"), ("AI popular", "top"), ("SI recent two", "latest")]


def test_ranked_budget_counts_declined_drafts_across_queries(monkeypatch, settings_override, drafting):
    drafting.default = "SKIP"
    settings_override(VIP_SCAN_HANDLES="", DIRECT_REPLY_MAX_PER_CYCLE=3, DIRECT_REPLY_QUERIES_PER_CYCLE=99)
    calls = []
    def discover(query, **kwargs):
        calls.append(query)
        return [{"likes": 3, "url": fresh("builder", n=len(calls)), "text": PARENT}]
    monkeypatch.setattr(direct, "scrape_x_search", discover)
    direct.run_direct_reply_cycle()
    assert len(calls) == len(drafting.calls) == 3
    assert reply_queue.ready() == {}
    assert len(reply_queue.QUEUE.read()) == 3


def test_vip_and_search_share_the_ranked_preparation_budget(monkeypatch, settings_override, drafting):
    settings_override(VIP_SCAN_HANDLES="builder", DIRECT_REPLY_MAX_PER_CYCLE=3)
    vip = [{"likes": 3, "url": fresh("builder", n=n), "text": PARENT} for n in (1, 2)]
    monkeypatch.setattr(scraper, "scrape_x_search", lambda *a, **k: vip)
    calls = []
    def discover(query, **kwargs):
        calls.append(query)
        return [{"likes": 3, "url": fresh("another", n=n), "text": PARENT} for n in (3, 4, 5)]
    monkeypatch.setattr(direct, "scrape_x_search", discover)
    direct.run_direct_reply_cycle()
    assert len(calls) == 1 and len(drafting.calls) == len(reply_queue.ready()) == 3


def test_vip_scan_rotates_one_profile_per_ranked_cycle(monkeypatch, settings_override):
    settings_override(VIP_SCAN_HANDLES="first,second,third")
    seen = []
    monkeypatch.setattr(scraper, "scrape_x_search", lambda query, **k: seen.append(query) or [])
    for _ in range(4):
        direct._run_vip_scan(pipeline.Cycle())
    assert seen == ["from:first", "from:second", "from:third", "from:first"]


def fill_queue():
    for n in range(reply_queue.MAX_PENDING):
        assert reply_queue.reserve(pipeline.Candidate(fresh("builder", n=n), PARENT, "TEST"))


@pytest.mark.parametrize("run", [direct.run_direct_reply_cycle, feed.run_feed_sweep_cycle,
                                  early.run_early_bird_cycle, mega.run_mega_watch_cycle])
def test_full_queue_stops_every_collector_before_browser_work(monkeypatch, run):
    fill_queue()
    monkeypatch.setattr(early, "_scan_pool", lambda: ["builder"])
    monkeypatch.setattr(mega, "_watch_pool", lambda: ["builder"])
    monkeypatch.setattr(pipeline, "scrape", lambda *a, **k: pytest.fail("scraped with full queue"))
    run()
    assert not reply_queue.has_capacity()


def test_for_you_gets_three_of_four_first_passes_when_only_one_feed_fits(monkeypatch):
    monkeypatch.setattr(feed, "_FEED_ROTATION_OFFSET", [0])
    available = iter((True, False) * 8)
    monkeypatch.setattr(pipeline, "discovery_available", lambda: next(available))
    seen = []
    monkeypatch.setattr(feed, "_sweep_one_feed", lambda source, *a: seen.append(source))
    for _ in range(8):
        feed.run_feed_sweep_cycle()
    assert seen == ["FEED", "FEED", "FEED", "FOLLOWING"] * 2


def test_queue_capacity_ignores_rejected_and_expired_work(monkeypatch):
    fill_queue()
    assert not reply_queue.has_capacity()
    sid = next(iter(reply_queue.QUEUE.read()))
    reply_queue.discard(sid, "declined")
    assert reply_queue.has_capacity()
    assert reply_queue.reserve(pipeline.Candidate(fresh("new", n=99), PARENT, "TEST"))
    assert not reply_queue.has_capacity()
    later = active_hours.now_local() + timedelta(minutes=31)
    monkeypatch.setattr(active_hours, "now_local", lambda: later)
    assert reply_queue.has_capacity()


def test_corrupt_queue_stops_discovery_without_overwriting():
    path = Path(reply_queue.QUEUE.path)
    path.write_text('{"broken":null}')
    with pytest.raises(StateUnreadable):
        pipeline.discovery_available()
    assert path.read_text() == '{"broken":null}'


def test_mega_watch_counts_preparation_instead_of_zero_publications(monkeypatch, drafting):
    monkeypatch.setattr(mega, "_watch_pool", lambda: ["builder"])
    monkeypatch.setattr(mega, "scrape_profile_tweets", lambda *a, **k: [
        {"likes": 3, "url": fresh("builder", minutes=1, n=n), "text": PARENT} for n in range(5)])
    mega.run_mega_watch_cycle()
    assert len(drafting.calls) == len(reply_queue.ready()) == mega.MAX_REPLIES_PER_CYCLE


@pytest.mark.parametrize("run", [direct.run_direct_reply_cycle, feed.run_feed_sweep_cycle,
                                  early.run_early_bird_cycle, mega.run_mega_watch_cycle])
def test_collectors_and_drafts_keep_parent_evidence_after_200_characters(monkeypatch, settings_override, drafting, run):
    parent = "SI model details. " * 22 + "Conclusion: latency depends on batching."
    url = fresh("builder", minutes=1)
    settings_override(VIP_SCAN_HANDLES="builder", DIRECT_REPLY_MAX_PER_CYCLE=1)
    monkeypatch.setattr(early, "_scan_pool", lambda: ["builder"])
    monkeypatch.setattr(mega, "_watch_pool", lambda: ["builder"])
    requested = []
    def scrape(*args, **kwargs):
        requested.append(kwargs["text_limit"])
        return [{"likes": 3, "url": url, "text": parent}]
    monkeypatch.setattr(pipeline, "scrape", scrape)
    run()
    assert requested and set(requested) == {4000}
    assert len(drafting.calls) == 1
    assert "Conclusion: latency depends on batching." in drafting.calls[0].prompt
    assert next(iter(reply_queue.ready().values()))["parent"] == parent


def test_topic_search_uses_the_same_parent_limit_as_the_vip_pass(monkeypatch, settings_override):
    settings_override(VIP_SCAN_HANDLES="", DIRECT_REPLY_QUERIES_PER_CYCLE=1)
    seen = []
    monkeypatch.setattr(direct, "scrape_x_search", lambda *a, **k: seen.append(k["text_limit"]) or [])
    direct.run_direct_reply_cycle()
    assert seen == [4000]


@pytest.mark.parametrize("run", [direct.run_direct_reply_cycle, feed.run_feed_sweep_cycle,
                                  early.run_early_bird_cycle, mega.run_mega_watch_cycle])
@pytest.mark.parametrize("likes", [0, 1, 2, 3, None, "3"])
def test_every_collector_requires_three_likes_before_drafting(monkeypatch, settings_override, drafting, run, likes):
    settings_override(VIP_SCAN_HANDLES="builder", DIRECT_REPLY_MAX_PER_CYCLE=1)
    monkeypatch.setattr(early, "_scan_pool", lambda: ["builder"])
    monkeypatch.setattr(mega, "_watch_pool", lambda: ["builder"])
    url = fresh("builder", minutes=1)
    monkeypatch.setattr(pipeline, "scrape", lambda *a, **k: [
        {"url": url, "text": PARENT, "likes": likes, "reposts": 10000}])
    run()
    assert len(drafting.calls) == (1 if likes == 3 else 0)
    assert len(reply_queue.ready()) == (1 if likes == 3 else 0)
