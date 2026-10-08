"""Discovery survives restarts and rejected posts remain in the permanent archive."""
import json
from datetime import timedelta

import pytest

from src.replies import reply_pool as pool, reply_pipeline as pipeline
from src.core.state_errors import StateUnreadable
from src.guards import active_hours
from tests.helpers import fresh, clock


def test_every_scraped_post_is_saved_before_filters(monkeypatch):
    posts = [{"url": fresh("ouraccount", n=1), "text": "our post"},
             {"url": fresh("other", n=2), "text": "comment", "is_reply": True},
             {"url": fresh("third", n=3), "text": "unrelated lunch"}]
    assert pipeline.scrape("FEED", "home", lambda: posts) == posts
    assert len(pool.read()) == 3
    with open(pool.ARCHIVE) as stream:
        archive = [json.loads(line) for line in stream]
    assert {event["post"]["text"] for event in archive} == {"our post", "comment", "unrelated lunch"}


def test_scan_collects_without_generating_or_sending(monkeypatch):
    url = fresh("someone")
    def forbidden(*a, **k):
        pytest.fail("a collector tried to draft or send")
    monkeypatch.setattr(pipeline.reply_generator, "generate", forbidden)
    monkeypatch.setattr(pipeline.twitter_client, "reply_to_tweet", forbidden)
    job = pipeline.Job("scan", "SCAN", reply_call=forbidden)
    assert pipeline.run(job, [pipeline.Candidate(url, "AI inference news", "FEED")], pipeline.Cycle()) == 0
    assert next(iter(pool.read().values()))["state"] == "queued"


def test_full_text_and_ids_are_preserved_and_deduplicated():
    url = fresh("someone")
    pool.observe([{"url": url, "text": "short", "full_text": "The complete AI post", "likes": 1}], "FEED")
    pool.observe([{"url": url + "?s=20", "text": "short", "full_text": "The complete AI post", "likes": 9}], "SEARCH")
    rows = pool.read()
    assert len(rows) == 1
    row = next(iter(rows.values()))
    assert row["text"] == "The complete AI post" and row["likes"] == 9
    assert row["sources"] == ["FEED", "SEARCH"]
    with open(pool.ARCHIVE) as stream:
        assert len(list(stream)) == 1


def test_comparison_wait_and_pool_expiry_preserve_archive(monkeypatch):
    now = active_hours.now_local()
    url = fresh("someone")
    pool.collect(pipeline.Job("scan", "SCAN", None), [pipeline.Candidate(url, "AI post", "FEED")])
    assert pool.contenders() == []
    assert len(pool.contenders(now + timedelta(seconds=61))) == 1
    clock(monkeypatch, now + timedelta(days=2))
    pool.observe([{"url": fresh("newauthor"), "text": "new post"}], "SEARCH")
    assert len(pool.read()) == 1
    with open(pool.ARCHIVE) as stream:
        assert any(json.loads(line).get("post", {}).get("text") == "AI post" for line in stream)


def test_corrupt_pool_is_never_overwritten():
    pool.POOL.write({"123": {"text": "broken"}})
    with pytest.raises(StateUnreadable):
        pool.observe([{"url": fresh("someone"), "text": "AI post"}], "FEED")
    assert pool.POOL.read() == {"123": {"text": "broken"}}


def test_conversation_candidates_are_saved_but_never_eligible():
    url = fresh("someone")
    pool.collect(pipeline.Job("conversation", "CONVERSATION", None, debate_turn=True),
                 [pipeline.Candidate(url, "a comment", "THREAD", context="our post")])
    row = next(iter(pool.read().values()))
    assert row["state"] == "rejected" and row["eligible"] is False
