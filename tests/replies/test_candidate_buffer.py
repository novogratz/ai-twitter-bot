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
