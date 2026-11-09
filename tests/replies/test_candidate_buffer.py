from datetime import timedelta
import time

import pytest

from src.replies import candidate_buffer as buffers, direct_reply, reply_pipeline as pipeline
from src.guards import replied_store
from src.x.confirmed_write import WriteOutcome
from tests.helpers import fresh
from tests.replies.fakes import EXHAUSTED


def candidate(n=0, *, minutes=1, **fields):
    return pipeline.Candidate(fresh("builder", minutes=minutes, n=n), f"SI model project {n}", "SEARCH-FRESH", **fields)


def job(pipelined=True):
    return pipeline.Job("buffer_test", "BUFFER", reply_call=direct_reply.reply_call, pipelined=pipelined)


def test_buffer_deduplicates_status_aliases_and_does_not_extend_ttl(monkeypatch, settings_override):
    settings_override(REPLY_CANDIDATE_BUFFER_TTL_SECONDS=60)
    now = [time.time()]
    monkeypatch.setattr(buffers.time, "time", lambda: now[0])
    buffer = buffers.Buffer()
    item = candidate()
    buffer.offer([item], max_age=timedelta(hours=1))
    expiry = buffer.pending()[0].expires_at
    now[0] += 30
    alias = pipeline.Candidate(item.url.replace("x.com/builder", "twitter.com/BUILDER") + "?s=20",
                               item.text, "SEARCH-HOT")
    buffer.offer([alias], max_age=timedelta(days=3))
    assert len(buffer.pending()) == 1 and buffer.pending()[0].expires_at == expiry
    assert replied_store.load_replied() == set()
    now[0] += 31
    assert buffer.pending() == []


def test_buffer_is_bounded_and_keeps_freshest_sources(settings_override):
    settings_override(REPLY_CANDIDATE_BUFFER_LIMIT=2)
    buffer = buffers.Buffer()
    old, middle, newest = candidate(1, minutes=20), candidate(2, minutes=10), candidate(3)
    buffer.offer([old, newest, middle], max_age=timedelta(hours=1))
    assert {c.url for c in buffer.pending()} == {middle.url, newest.url}
    settings_override(DIRECT_REPLY_MAX_AGE_MINUTES=5)
    assert [c.url for c in buffer.pending()] == [newest.url]


def test_buffer_rejects_nested_future_unknown_and_prepared_content():
    buffer = buffers.Buffer()
    items = [candidate(1, is_reply=True), candidate(2, context="Quoted as a conversation"),
             candidate(3, reply="An already-written draft."), candidate(4, minutes=-10),
             pipeline.Candidate("https://evil.test/status/1", "SI model", "TEST"),
             pipeline.Candidate(fresh("builder", n=6), "@someone SI model", "TEST")]
    buffer.offer(items, max_age=timedelta(hours=1))
    assert buffer.pending() == []


@pytest.mark.parametrize("pipelined", [False, True])
def test_budget_preserves_unused_sources_and_rechecks_permanent_history(llm, chokepoint, pipelined):
    buffer = buffers.Buffer()
    items = [candidate(n) for n in range(3)]
    buffer.offer(items, max_age=timedelta(hours=1))
    assert buffer.run(job(pipelined), pipeline.Cycle(), max_generations=1) == 1
    assert len(buffer.pending()) == 2
    replied_store.claim(items[1].url)
    assert buffer.run(job(pipelined), pipeline.Cycle(), max_generations=1) == 1
    assert chokepoint.sent == [items[0].url, items[2].url]
    assert len(llm.calls) == 2 and buffer.pending() == []


def test_quota_stop_keeps_unprocessed_sources_without_claiming(llm, chokepoint):
    buffer = buffers.Buffer()
    items = [candidate(n) for n in range(3)]
    buffer.offer(items, max_age=timedelta(hours=1))
    llm.default = EXHAUSTED
    assert buffer.run(job(), pipeline.Cycle(), max_generations=2) == 0
    assert len(buffer.pending()) == 3
    assert replied_store.load_replied() == set() and chokepoint.sent == []


def test_selected_turn_does_not_claim_other_sources_or_extend_selected_expiry(monkeypatch, llm, chokepoint):
    from dataclasses import replace

    now = [time.time()]
    monkeypatch.setattr(buffers.time, "time", lambda: now[0])
    buffer = buffers.Buffer()
    first, second = candidate(1), candidate(2)
    buffer.offer([first, second], max_age=timedelta(hours=1))
    expires = buffer.pending()[0].expires_at
    now[0] += 10
    alias = first.url.replace("x.com/builder", "twitter.com/BUILDER") + "?s=20"
    buffer.offer([replace(first, url=alias)], max_age=timedelta(days=3), preferred_urls=[alias])
    assert next(c.expires_at for c in buffer.pending() if c.url == first.url) == expires
    assert buffer.run(job(), pipeline.Cycle(), only_urls=[], max_generations=1) == 0
    assert buffer.run(job(), pipeline.Cycle(), only_urls=[alias], max_generations=1) == 1
    assert chokepoint.sent == [first.url]
    assert [c.url for c in buffer.pending()] == [second.url]
    now[0] = expires + 1
    assert buffer.run(job(), pipeline.Cycle(), only_urls=[second.url], max_generations=1) == 0


def test_source_expiry_is_checked_after_generation_and_after_spacing(monkeypatch, llm, chokepoint):
    now = [time.time()]
    monkeypatch.setattr(buffers.time, "time", lambda: now[0])
    for when in ("generation", "spacing"):
        buffer = buffers.Buffer()
        item = candidate(1 if when == "generation" else 2)
        buffer.offer([item], max_age=timedelta(hours=1))
        if when == "generation":
            def draft(_):
                now[0] += 2000
                return "This SI model needs broader evaluation 🙂"
            llm.default = draft
        else:
            llm.default = "This SI model needs broader evaluation 🙂"
            monkeypatch.setattr(pipeline, "_wait_out_reply_spacing", lambda _: now.__setitem__(0, now[0] + 2000))
        assert buffer.run(job(False), pipeline.Cycle(), max_generations=1) == 0
    assert chokepoint.sent == [] and replied_store.load_replied() == set()


def test_uncertain_send_keeps_the_durable_claim_after_buffer_removal(llm, chokepoint):
    item, buffer = candidate(), buffers.Buffer()
    buffer.offer([item], max_age=timedelta(hours=1))
    def uncertain(url):
        replied_store.claim(url)
        return WriteOutcome.UNCONFIRMED
    chokepoint.answer = uncertain
    assert buffer.run(job(), pipeline.Cycle(), max_generations=1) == 0
    buffer.offer([item], max_age=timedelta(hours=1))
    assert buffer.run(job(), pipeline.Cycle(), max_generations=1) == 0
    assert len(chokepoint.calls) == 1 and item.url in replied_store.load_replied()


def test_new_like_observation_changes_priority_without_extending_source_ttl(llm, chokepoint):
    from dataclasses import replace
    buffer = buffers.Buffer()
    low, popular, unknown = candidate(1, likes=2), candidate(2, likes=3), candidate(3)
    buffer.offer([low, popular, unknown], max_age=timedelta(hours=1))
    assert [c.url for c in buffer.pending()] == [popular.url, low.url, unknown.url]
    expiry = next(c.expires_at for c in buffer.pending() if c.url == low.url)
    buffer.offer([replace(low, likes=4)], max_age=timedelta(days=3))
    assert buffer.pending()[0].url == low.url
    assert buffer.pending()[0].expires_at == expiry
    assert buffer.run(job(), pipeline.Cycle(), max_generations=3) == 3
    assert chokepoint.sent == [low.url, popular.url, unknown.url]


@pytest.mark.parametrize("pipelined", [False, True])
def test_buffer_reaches_different_authors_before_second_posts_within_each_like_tier(llm, chokepoint, pipelined):
    from dataclasses import replace

    items = [replace(candidate(n, likes=likes), url=fresh(author, n=n))
             for n, (author, likes) in enumerate([
                 ("first", 3), ("FIRST", 20), ("second", 3),
                 ("second", 2), ("second", None), ("third", None)])]
    buffer = buffers.Buffer()
    buffer.offer(items, max_age=timedelta(hours=1))
    assert [c.url for c in buffer.pending()] == [items[n].url.lower() for n in (0, 2, 1, 3, 5, 4)]

    # A limited cycle spends its first two drafts on two authors. Lower-like
    # and unknown-count posts stay available after every preferred candidate.
    assert buffer.run(job(pipelined), pipeline.Cycle(), max_generations=2) == 2
    assert chokepoint.sent == [items[0].url, items[2].url]
    assert buffer.run(job(pipelined), pipeline.Cycle(), max_generations=4) == 4
    assert chokepoint.sent == [items[n].url.lower() for n in (0, 2, 1, 3, 5, 4)]
    assert buffer.pending() == []


def test_author_diversity_is_opt_in_so_watched_job_order_is_unchanged():
    from dataclasses import replace

    items = [candidate(1, likes=3), candidate(2, likes=9),
             replace(candidate(3, likes=3), url=fresh("another", n=3))]
    assert pipeline.prioritize(items) == items
    assert pipeline.prioritize(items, diversify_authors=True) == [items[0], items[2], items[1]]


@pytest.mark.parametrize("pipelined", [False, True])
def test_ordinary_priority_survives_pipeline_sort_and_rotates_authors_before_second_posts(
        monkeypatch, settings_override, llm, chokepoint, pipelined):
    from dataclasses import replace
    from src.core import account

    loaded = account.current()
    monkeypatch.setattr(account, "current", lambda: replace(loaded, network=replace(
        loaded.network, big_ai_hype=("PriorityOne", "prioritytwo"))))
    settings_override(REPLY_PRIORITIZE_LARGE_ACCOUNTS=True, REPLY_PREFERRED_MIN_LIKES=3)
    items = [replace(candidate(n, likes=likes, views=views), url=fresh(author, n=n))
             for n, (author, likes, views) in enumerate([
                 ("small", 300, 1_000_000), ("priorityone", 0, 10_000),
                 ("priorityone", 3, 900), ("priorityone", 3, 1000),
                 ("prioritytwo", 3, 800), ("unknown", 3, None), ("zero", 3, 0)])]
    buffer = buffers.Buffer()
    buffer.offer(items, max_age=timedelta(hours=1))
    ordered = buffer.pending()
    assert [c.url for c in ordered] == [items[n].url for n in (3, 4, 2, 1, 0, 6, 5)]
    assert pipeline.prioritize(ordered, ordinary=True, diversify_authors=True) == ordered
    assert buffer.run(job(pipelined), pipeline.Cycle(), max_generations=2) == 2
    assert chokepoint.sent == [items[3].url, items[4].url]
    assert buffer.run(job(pipelined), pipeline.Cycle(), max_generations=5) == 5
    assert chokepoint.sent == [items[n].url for n in (3, 4, 2, 1, 0, 6, 5)]
    # The same configured author and view counters never reorder watched jobs.
    assert pipeline.prioritize(items) == [items[n] for n in (0, 2, 3, 4, 5, 6, 1)]


def test_view_rediscovery_refreshes_ranking_without_erasing_observations_or_extending_ttl():
    from dataclasses import replace

    buffer = buffers.Buffer()
    first, second = candidate(1, likes=3, views=10), candidate(2, likes=3, views=100)
    buffer.offer([first, second], max_age=timedelta(hours=1))
    assert [c.url for c in buffer.pending()] == [second.url, first.url]
    expiry = next(c.expires_at for c in buffer.pending() if c.url == first.url)
    buffer.offer([replace(first, views=200)], max_age=timedelta(days=3))
    assert buffer.pending()[0].url == first.url
    assert buffer.pending()[0].views == 200 and buffer.pending()[0].expires_at == expiry
    for missing in (None, True, -1, "99999"):
        buffer.offer([replace(first, likes=None, views=missing)], max_age=timedelta(days=3))
        assert buffer.pending()[0].views == 200 and buffer.pending()[0].likes == 3
        assert buffer.pending()[0].expires_at == expiry


@pytest.mark.parametrize("views", [None, 999])
def test_rediscovery_tightens_a_priority_sources_horizon_even_without_new_counters(monkeypatch, views):
    from dataclasses import replace

    now = [time.time()]
    monkeypatch.setattr(buffers.time, "time", lambda: now[0])
    buffer = buffers.Buffer()
    item = candidate(minutes=55, likes=3, views=100)
    buffer.offer([item], max_age=timedelta(hours=24))
    expiry = buffer.pending()[0].expires_at
    buffer.offer([replace(item, likes=None, views=views)], max_age=timedelta(hours=1))
    tighter = buffer.pending()[0]
    assert tighter.expires_at < expiry
    assert tighter.views == (100 if views is None else views)
    assert tighter.likes == 3
    now[0] += 6 * 60
    assert buffer.pending() == []


@pytest.mark.parametrize("enabled", [False, True])
def test_full_buffer_retains_older_priority_source_only_when_enabled(monkeypatch, settings_override, enabled):
    from dataclasses import replace
    from src.core import account

    loaded = account.current()
    monkeypatch.setattr(account, "current", lambda: replace(loaded, network=replace(
        loaded.network, big_ai_hype=("Major",))))
    settings_override(REPLY_CANDIDATE_BUFFER_LIMIT=2, REPLY_PRIORITIZE_LARGE_ACCOUNTS=enabled)
    now = [time.time()]
    monkeypatch.setattr(buffers.time, "time", lambda: now[0])
    buffer = buffers.Buffer()
    ordinary, newest = candidate(1, minutes=10), candidate(2, minutes=1)
    major = replace(candidate(3, minutes=12 * 60), url=fresh("major", minutes=12 * 60, n=3))
    buffer.offer([ordinary, newest], max_age=timedelta(hours=24))
    buffer.offer([major], max_age=timedelta(hours=24))
    assert {item.url for item in buffer.pending()} == {
        newest.url, major.url if enabled else ordinary.url}
    assert replied_store.load_replied() == set()
    now[0] += 31 * 60
    assert buffer.pending() == []  # Priority never extends the source's TTL.
