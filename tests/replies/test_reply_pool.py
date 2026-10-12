"""Discovery survives restarts and rejected posts remain in the permanent archive."""
import json
from datetime import timedelta

import pytest

from src.replies import reply_pool as pool, reply_pipeline as pipeline
from src.core.state_errors import StateUnreadable
from src.guards import active_hours
from tests.helpers import fresh_local as fresh, clock


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


@pytest.mark.parametrize("job_name", ["early_bird", "mega_watch"])
@pytest.mark.parametrize("minutes", [20, 180, 23 * 60])
def test_profile_scans_keep_older_posts_eligible_in_the_shared_pool(monkeypatch, job_name, minutes):
    from src.replies import early_bird_bot, mega_watch_bot
    from src.x import x_urls
    module = {"early_bird": early_bird_bot, "mega_watch": mega_watch_bot}[job_name]
    now = active_hours.now_local()
    real_age = x_urls.age
    monkeypatch.setattr(x_urls, "age", lambda url, at=None: real_age(url, at or now))
    url = fresh("modelbuilder", minutes=minutes)
    candidates = module._fresh_candidates("modelbuilder", [{"url": url, "text": "SI model evaluation"}])
    assert [candidate.url for candidate in candidates] == [url]
    assert pipeline.run(module.JOB, candidates, pipeline.Cycle()) == 0
    assert [row["url"] for row in pool.contenders(now + timedelta(seconds=61))] == [url]


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


@pytest.mark.parametrize("source", ["FEED", "SEARCH", "VIP/Graphseo", "EARLYBIRD", "MEGA"])
def test_every_source_saves_but_rejects_unrelated_posts(source):
    url = fresh("someone")
    pool.collect(pipeline.Job("scan", "SCAN", None),
                 [pipeline.Candidate(url, "My lunch with @OpenAI https://ai.example.org", source)])
    row = next(iter(pool.read().values()))
    assert row["state"] == "rejected" and row["eligible"] is False
    with open(pool.ARCHIVE) as stream:
        events = [json.loads(line) for line in stream]
    assert [event["kind"] for event in events] == ["discovered", "decision"]


@pytest.mark.parametrize("text", ["My unrelated lunch", "AI trading Bitcoin", "Grok crypto prediction"])
def test_saved_eligibility_never_bypasses_current_topic_filter(monkeypatch, text):
    url = fresh("someone")
    pool.collect(pipeline.Job("scan", "SCAN", None), [pipeline.Candidate(url, "AI post", "FEED")])
    records = pool.read()
    next(iter(records.values()))["text"] = text
    pool.POOL.write(records)
    clock(monkeypatch, active_hours.now_local() + timedelta(seconds=61))
    assert pool.contenders() == []


def test_negative_topic_verdict_cannot_be_overridden_by_a_high_score(monkeypatch):
    url = fresh("someone")
    pool.collect(pipeline.Job("scan", "SCAN", None), [pipeline.Candidate(url, "Claude's birthday", "VIP")])
    clock(monkeypatch, active_hours.now_local() + timedelta(seconds=61))
    batch = pool.contenders()
    pool.decide(batch, [dict(id=batch[0]["id"], on_topic=False, score=100,
                             reason="Person's birthday, unrelated to AI", angle="Birthday joke")])
    row = pool.read()[batch[0]["id"]]
    assert row["state"] == "rejected" and row["score"] == 0
    assert not pool.contenders()


@pytest.mark.parametrize("state", ["processing", "shipped", "closed", "skipped"])
def test_collection_preserves_final_or_ambiguous_outcomes(state):
    url = fresh("someone")
    job = pipeline.Job("scan", "SCAN", None)
    candidate = pipeline.Candidate(url, "AI post", "FEED")
    pool.collect(job, [candidate])
    key = next(iter(pool.read()))
    pool.mark(key, state)
    pool.observe([dict(url=url, text="Unrelated edited post")], "FEED")
    pool.collect(job, [candidate])
    assert pool.read()[key]["state"] == state
