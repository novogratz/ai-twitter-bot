"""Permanent repost dedup, bounded budgets and video/priority admission."""
from dataclasses import replace
from datetime import timedelta

import pytest

from src.core import account, settings
from src.core.state_errors import StateUnreadable
from src.guards import action_guard as ag, active_hours, repost_policy as policy
from src.replies import reply_pool
from tests.helpers import fresh_local as fresh, clock


def video(**overrides):
    return dict(url=fresh("creator"), text="Seedance video: generated clay animation workflow",
                has_video=True, is_reply=False, likes=600, reposts=100, **overrides)


def test_repost_cap_cannot_exceed_fifty(settings_override):
    settings_override(MAX_REPOSTS_PER_DAY=5000, MIN_SECONDS_BETWEEN_REPOSTS=0)
    assert settings.get("MAX_REPOSTS_PER_DAY") == 50
    assert settings.get("MIN_SECONDS_BETWEEN_REPOSTS") == 600


def test_pending_and_confirmed_reposts_share_the_hard_cap(monkeypatch, memory_ledger):
    now = active_hours.now_local()
    for n in range(49):
        memory_ledger.append(ag.RETWEET, fresh("old", n=n), False, now - timedelta(hours=1))
    assert ag.can_post(ag.RETWEET)[0]
    url = fresh("new", n=60)
    policy.remember(url, "pending")
    assert policy.pending_count() == 1
    assert not ag.can_post(ag.RETWEET)[0]
    ag.record(ag.RETWEET, url)
    assert policy.pending_count() == 0  # crash between ledger and confirmation
    policy.remember(url, "confirmed")
    assert not ag.can_post(ag.RETWEET)[0]
    clock(monkeypatch, now + timedelta(days=1))
    assert ag.can_post(ag.RETWEET)[0]
    assert policy.known(url.replace('/new/', '/renamed/') + '?s=20')


def test_ambiguous_reposts_keep_spacing_and_permanent_dedup(monkeypatch):
    url = fresh("creator")
    policy.remember(url, "pending")
    assert not ag.can_post(ag.RETWEET)[0]
    clock(monkeypatch, active_hours.now_local() + timedelta(minutes=11))
    assert ag.can_post(ag.RETWEET)[0]
    assert policy.known(url)
    clock(monkeypatch, active_hours.now_local() + timedelta(days=365))
    assert policy.known(url)


@pytest.mark.parametrize("row", [{}, {"state": "pending", "url": 3, "at": "bad"},
                                  {"state": "confirmed", "url": "https://x.com/a/status/123", "at": "2026-10-12T10:00:00"}])
def test_corrupt_history_blocks_and_is_never_overwritten(row):
    policy.HISTORY.write({"123": row})
    with pytest.raises(StateUnreadable):
        policy.remember(fresh("creator"), "pending")
    assert policy.HISTORY.read() == {"123": row}


def test_priority_exception_never_overrides_crypto_own_blocked_or_threads():
    post = dict(url=fresh("elonmusk"), text="Good morning", has_video=False, is_reply=False)
    assert policy.refusal(post) == ""
    assert policy.refusal({**post, "text": "Bitcoin adoption"}) == "excluded topic"
    assert policy.refusal({**post, "quoted_text": "crypto launch"}) == "excluded topic"
    assert policy.refusal({**post, "is_reply": True})
    assert policy.refusal({**post, "url": fresh("thesimaximalist")})
    assert policy.refusal({**post, "url": fresh("TheBTCTherapist")})
    assert policy.refusal({**post, "url": fresh("other")})


def test_priority_topic_exception_is_account_owned(monkeypatch):
    current = account.current()
    monkeypatch.setattr(account, "current", lambda: replace(current, reposts=replace(current.reposts, allow_off_topic_priority=False)))
    assert policy.refusal(dict(url=fresh("elonmusk"), text="Good morning", is_reply=False))
    assert not policy.refusal(dict(url=fresh("elonmusk"), text="Grok video generation", is_reply=False))


@pytest.mark.parametrize("changes", [
    {"has_video": False}, {"text": "Look at my holiday video"}, {"text": "AI video Bitcoin presale"},
    {"is_reply": True}, {"likes": 0, "reposts": 0, "views": 1000000},
    {"url": "https://x.com/creator/status/1"},
])
def test_popularity_and_keywords_never_bypass_video_admission(changes):
    assert policy.refusal({**video(), **changes}, require_review=False)


def test_fresh_risers_and_large_hits_both_qualify():
    post = video()
    assert policy.is_rising_video(post)
    assert policy.is_rising_video({**post, "url": fresh("smallcreator", minutes=5), "likes": 80, "reposts": 0})
    assert not policy.is_rising_video({**post, "url": fresh("oldcreator", minutes=180), "likes": 80, "reposts": 0})


def test_video_approval_is_bound_to_caption_and_expires(monkeypatch):
    post = video()
    reply_pool.observe([post], "VIDEO")
    assert policy.refusal(post)
    policy.save_review(post, True, "Generated animation with a useful workflow")
    assert policy.refusal(post) == ""
    assert policy.refusal({**post, "text": post["text"] + " new claim"})
    clock(monkeypatch, active_hours.now_local() + timedelta(hours=1))
    assert policy.refusal(post)


def test_fifty_reposts_do_not_consume_original_or_reply_allowance(memory_ledger):
    for n in range(50):
        memory_ledger.append(ag.RETWEET, fresh("creator", n=n), False, active_hours.now_local() - timedelta(hours=1))
    assert not ag.can_post(ag.RETWEET)[0]
    assert ag.profile_count_today() == 0
    assert ag.can_post(ag.POST)[0] and ag.can_post(ag.REPLY)[0]


def test_corrupt_video_approval_stops_selection_without_replacing_state():
    post = video()
    reply_pool.observe([post], "VIDEO")
    rows = reply_pool.read()
    next(iter(rows.values()))["repost_review"] = dict(approved="true", text=post["text"], reason="", at="bad")
    reply_pool.POOL.write(rows)
    with pytest.raises(StateUnreadable):
        policy.refusal(post)
    assert reply_pool.POOL.read() == rows
