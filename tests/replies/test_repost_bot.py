"""Repost discovery shares saved posts; a quota never forces an unapproved clip."""
import json

import pytest

from src.replies import repost_bot as bot, reply_pool
from src.guards import repost_policy as policy, action_guard as ag, active_hours
from src.core.llm_client import LLMResult
from src.x.twitter_client import WriteOutcome
from tests.helpers import fresh_local as fresh


@pytest.fixture
def candidates(monkeypatch):
    monkeypatch.setattr(bot.scraper, "scrape_x_search", lambda *a, **k: [])
    monkeypatch.setattr(bot, "_PRIORITY_OFFSET", 0)
    monkeypatch.setattr(bot, "_RETRY_AFTER", {})
    posts = [dict(url=fresh("creator", n=1), text="Seedance generated animation video workflow",
                  has_video=True, likes=600, reposts=110, is_reply=False),
             dict(url=fresh("elonmusk", n=2), text="Good morning", has_video=False, is_reply=False)]
    reply_pool.observe(posts, "VIDEO")
    return posts


def test_new_priority_original_wins_and_no_model_is_needed(candidates, monkeypatch):
    sent = []
    monkeypatch.setattr(bot, "run_llm", lambda *a, **k: pytest.fail("priority post needs no video review"))
    monkeypatch.setattr(bot.twitter_client, "repost_tweet", lambda url: sent.append(url) or WriteOutcome.SHIPPED)
    assert bot.run_repost_cycle() == 1
    assert sent == [candidates[1]["url"]]


def test_previously_reposted_priority_post_does_not_starve_videos(candidates, monkeypatch):
    # A prior-day record, still permanent, with no spacing/budget today.
    policy.HISTORY.write({candidates[1]["url"].rsplit('/', 1)[1]: dict(
        url=candidates[1]["url"], state="confirmed", at="2026-01-01T12:00:00-05:00")})
    sent = []
    monkeypatch.setattr(bot, "run_llm", lambda *a, **k:
                        LLMResult(0, json.dumps(dict(approved=True, reason="Generated animation workflow")), ""))
    monkeypatch.setattr(bot.twitter_client, "repost_tweet", lambda url: sent.append(url) or WriteOutcome.SHIPPED)
    assert bot.run_repost_cycle() == 1
    assert sent == [candidates[0]["url"]]
    assert policy.approved(candidates[0])


@pytest.mark.parametrize("answer", ["not json", '[]', '{"approved":"true","reason":"yes"}',
                                  '{"approved":true,"reason":""}', '{"approved":false,"reason":"unrelated clip"}'])
def test_invalid_or_negative_video_reviews_never_approve(candidates, monkeypatch, answer):
    monkeypatch.setattr(bot, "run_llm", lambda *a, **k: LLMResult(0, answer, ""))
    assert not bot._review_video(candidates[0])
    assert not policy.approved(candidates[0])


def test_repost_scan_stops_before_browser_when_budget_is_used(candidates, monkeypatch, settings_override):
    settings_override(MAX_REPOSTS_PER_DAY=0)
    monkeypatch.setattr(bot.scraper, "scrape_x_search", lambda *a, **k: pytest.fail("scan past cap"))
    assert bot.run_repost_cycle() == 0


def test_caption_only_review_explicitly_does_not_claim_visual_access(candidates, monkeypatch):
    prompts = []
    monkeypatch.setattr(bot, "run_llm", lambda prompt, *a, **k:
                        prompts.append(prompt) or LLMResult(0, '{"approved":false,"reason":"caption insufficient"}', ""))
    assert bot._review_video(candidates[0]) is False
    assert "NOT the video frames or audio" in prompts[0]
    assert "untrusted data" in prompts[0]


def test_repost_job_is_opt_in_and_not_registered_in_limited_modes(settings_override):
    from main import build_scheduler
    assert build_scheduler().get_job("repost_job").trigger.interval.total_seconds() == 120
    assert build_scheduler(reply_only=True).get_job("repost_job") is None
    assert build_scheduler(post_only=True).get_job("repost_job") is None
    settings_override(MAX_REPOSTS_PER_DAY=0)
    assert build_scheduler().get_job("repost_job") is None


def test_unreadable_priority_page_does_not_block_a_valid_video(candidates, monkeypatch):
    policy.save_review(candidates[0], True, "Generated clip with useful workflow")
    attempted = []
    def send(url):
        attempted.append(url)
        return WriteOutcome.FAILED if url == candidates[1]["url"] else WriteOutcome.SHIPPED
    monkeypatch.setattr(bot.twitter_client, "repost_tweet", send)
    assert bot.run_repost_cycle() == 1
    assert attempted == [candidates[1]["url"], candidates[0]["url"]]
    attempted.clear()
    assert bot.run_repost_cycle() == 1
    assert attempted == [candidates[0]["url"]]
