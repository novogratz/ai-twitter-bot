from datetime import timedelta

import pytest

from src.core import account
from src.guards.reply_admission import Refusal
from src.replies import candidate_buffer, reply_pipeline, reply_source
from src.x import twitter_client as tc
from tests.helpers import fresh


@pytest.mark.parametrize("likes,allowed", [(None, False), (0, False), (2, False), (3, True), (30, True), (True, False)])
@pytest.mark.parametrize("handle", ["newartist", "elonmusk"])
def test_three_like_rule_includes_watched_authors_before_generation(settings_override, likes, allowed, handle):
    settings_override(REPLY_MIN_LIKES=3)
    candidate = reply_pipeline.Candidate(fresh(handle), "My new SI short film", "FEED", likes=likes)
    job = reply_pipeline.Job("floor", "FLOOR", reply_call=lambda author: None)
    verdict = reply_pipeline._parent_verdict(job, candidate)
    assert bool(verdict) is allowed
    if not allowed:
        assert verdict.refusal is Refusal.ENGAGEMENT


@pytest.mark.parametrize("likes,expected", [(None, False), (2, False), (3, True), ("3", False)])
def test_final_live_parent_counter_must_be_numeric_and_belong_to_target(monkeypatch, settings_override, likes, expected):
    settings_override(REPLY_MIN_LIKES=3)
    url = fresh("newartist")
    monkeypatch.setattr(tc, "_page_posts", lambda *a: dict(url=url, likes=likes))
    assert tc._reply_engagement_ok(url) is expected
    monkeypatch.setattr(tc, "_page_posts", lambda *a: dict(url=fresh("other"), likes=1000))
    assert not tc._reply_engagement_ok(url)


def test_low_like_sources_do_not_fill_buffer_and_can_qualify_on_rediscovery(settings_override):
    settings_override(REPLY_MIN_LIKES=3)
    url = fresh("newartist")
    buf = candidate_buffer.Buffer()
    for likes in (None, 2):
        buf.offer([reply_pipeline.Candidate(url, "My SI artwork", "FEED", likes=likes)], max_age=timedelta(hours=1))
        assert buf.pending() == []
    buf.offer([reply_pipeline.Candidate(url, "My SI artwork", "FEED", likes=3)], max_age=timedelta(hours=1))
    assert [c.url for c in buf.pending()] == [url]


def test_all_topic_exception_is_exact_author_only_and_never_for_follows():
    assert account.engagement_allowed("A new Starship launch", url=fresh("elonmusk"))
    for url in (fresh("someone"), fresh("elonmusk_fake"), "https://evilx.com/elonmusk/status/123"):
        assert not account.engagement_allowed("A new Starship launch", url=url)
    assert not account.engagement_allowed("SpaceX fan", profile=True, url=fresh("elonmusk"))


def test_new_creator_and_general_search_topics_exist():
    searches = account.current().searches
    creators = " ".join(searches.creators).lower()
    assert all(term in creators for term in ("short film", "movie", "animation", "comfyui", "music video"))
    general = " ".join(searches.latest).lower()
    assert all(term in general for term in ("education", "accessibility", "local model", "safety", "agents"))
