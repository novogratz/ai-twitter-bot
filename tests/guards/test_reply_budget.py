"""Submission ceilings survive unknown sends, separate workers and restarts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.core.state_errors import StateUnreadable
from src.core.state_store import GUARDED, StateFile
from src.guards import action_guard as guard, reply_budget, reply_focus
from tests.helpers import TORONTO, clock, numbered_url
from src.x import x_urls

NOW = datetime(2026, 11, 18, 12, tzinfo=TORONTO)


def fresh_url(author="someone", seconds=0, now=NOW):
    millis = int((now - timedelta(seconds=seconds)).timestamp() * 1000)
    return f"https://x.com/{author}/status/{(millis - x_urls._TWITTER_EPOCH_MS) << 22}"


@pytest.mark.parametrize("cap", [40, 100])
def test_last_daily_slot_is_atomic_and_confirmation_is_not_double_counted(monkeypatch, memory_ledger, settings_override, cap):
    clock(monkeypatch, NOW)
    settings_override(MAX_REPLIES_PER_DAY=cap, REPLY_JITTER_SECONDS=0)
    for n in range(cap - 1):
        memory_ledger.append(guard.REPLY, numbered_url(n), False, NOW - timedelta(hours=2))
    urls = [numbered_url(1000), numbered_url(1001)]
    with ThreadPoolExecutor(2) as pool:
        refusals = list(pool.map(reply_budget.begin, urls))
    assert refusals.count("") == 1
    assert reply_budget.used_today() == cap
    winner = urls[refusals.index("")]
    guard.record(guard.REPLY, winner)
    reply_budget.confirmed(winner)
    assert reply_budget.used_today() == cap
    assert not guard.can_post(guard.REPLY)[0]


def test_uncertain_send_survives_restart_and_keeps_spacing(monkeypatch, memory_ledger, settings_override):
    clock(monkeypatch, NOW)
    settings_override(MIN_SECONDS_BETWEEN_REPLIES=1440, REPLY_JITTER_SECONDS=0)
    assert reply_budget.begin(numbered_url(20)) == ""
    monkeypatch.setattr(reply_budget, "STATE", StateFile("reply_submissions.json", {}, GUARDED))
    assert guard.count_today(guard.REPLY) == 0
    assert reply_budget.used_today() == 1
    clock(monkeypatch, NOW + timedelta(seconds=1439))
    assert not guard.can_post(guard.REPLY)[0]
    clock(monkeypatch, NOW + timedelta(seconds=1440))
    assert guard.can_post(guard.REPLY)[0]
    assert reply_budget.begin(numbered_url(20)) == "Reply already submitted"


def test_ten_minute_spacing_cannot_burst_or_cross_bedtime_to_fill_cap(monkeypatch, memory_ledger, settings_override):
    settings_override(MAX_REPLIES_PER_DAY=100, MIN_SECONDS_BETWEEN_REPLIES=600, REPLY_JITTER_SECONDS=0)
    start = NOW.replace(hour=7)
    clock(monkeypatch, start - timedelta(seconds=1))
    assert not guard.can_post(guard.REPLY)[0]
    for n in range(96):
        at = start + timedelta(seconds=n * 600)
        clock(monkeypatch, at)
        url = numbered_url(10000 + n)
        assert reply_budget.begin(url) == ""
        guard.record(guard.REPLY, url)
        reply_budget.confirmed(url)
        clock(monkeypatch, at + timedelta(seconds=599))
        assert not guard.can_post(guard.REPLY)[0]
    assert at.hour == 22 and at.minute == 50
    assert reply_budget.used_today() == 96
    clock(monkeypatch, start.replace(hour=23))
    assert not guard.can_post(guard.REPLY)[0]


def test_toronto_day_changes_budget_but_never_releases_parent(monkeypatch, memory_ledger):
    clock(monkeypatch, NOW)
    assert reply_budget.begin(numbered_url(30)) == ""
    clock(monkeypatch, NOW + timedelta(days=1))
    assert reply_budget.used_today() == 0
    assert reply_budget.begin(numbered_url(30)) == "Reply already submitted"


def test_future_stamp_and_corrupt_state_fail_closed(monkeypatch, memory_ledger):
    clock(monkeypatch, NOW)
    assert reply_budget.begin(numbered_url(31)) == ""
    clock(monkeypatch, NOW - timedelta(days=1))
    assert reply_budget.used_today() == 1
    assert not guard.can_post(guard.REPLY)[0]
    Path(reply_budget.STATE.path).write_text('{"bad": {}}')
    with pytest.raises(StateUnreadable):
        guard.can_post(guard.REPLY)
    assert Path(reply_budget.STATE.path).read_text() == '{"bad": {}}'


def test_watched_author_cap_includes_legacy_receipts_and_unknown_sends(monkeypatch, memory_ledger, settings_override):
    clock(monkeypatch, NOW)
    settings_override(REPLY_WATCHED_DAILY_CAP=2)
    memory_ledger.append(guard.REPLY, numbered_url(40, "elonmusk"), False, NOW-timedelta(hours=2))
    assert reply_budget.begin(numbered_url(41, "elonmusk")) == ""
    assert "@elonmusk" in reply_budget.refusal(numbered_url(42, "elonmusk"))
    assert reply_budget.refusal(numbered_url(43, "another")) == ""


@pytest.mark.parametrize("author,seconds,allowed", [
    ("someone", 30, True), ("someone", 1800, True), ("someone", 1801, False),
    ("elonmusk", 20, True), ("elonmusk", 60, True), ("elonmusk", 300, True),
    ("elonmusk", 301, False), ("someone", -1, False),
])
def test_freshness_boundaries_rechecked_at_submission(monkeypatch, memory_ledger, settings_override, author, seconds, allowed):
    clock(monkeypatch, NOW)
    settings_override(REPLY_MAX_AGE_SECONDS=1800, REPLY_WATCHED_MAX_AGE_SECONDS=300)
    url = fresh_url(author, seconds)
    assert (reply_budget.begin(url) == "") is allowed
    assert bool(reply_budget.entries()) is allowed


def test_watched_likes_and_reposts_require_the_exact_confirmed_reply(monkeypatch, memory_ledger, settings_override):
    clock(monkeypatch, NOW)
    settings_override(WATCH_ENGAGEMENT_REQUIRES_REPLY=True)
    url = numbered_url(60, "elonmusk")
    assert not guard.can_post(guard.LIKE, target=url)[0]
    assert "confirmed Reply" in guard.can_post(guard.RETWEET, target=url)[1]
    assert guard.can_post(guard.LIKE, target=url, reply_parent=True)[0]
    assert reply_budget.begin(url) == ""
    assert not guard.can_post(guard.LIKE, target=url)[0], "an uncertain send is not a confirmed Reply"
    guard.record(guard.REPLY, url)
    assert guard.can_post(guard.LIKE, target=url)[0]
    assert not guard.can_post(guard.LIKE, target=numbered_url(61, "elonmusk"))[0]


@pytest.mark.parametrize("text,allowed", [
    ("Claude is here! Absolutely incredible, what a launch!", False),
    ("Made this in Grok Imagine, hope you like it!", False),
    ("Like and repost for my inference benchmark results", False),
    ("Why does batching improve inference throughput but hurt latency?", True),
    ("Our LLM retrieval fails when the relevant document uses different terminology.", True),
])
def test_selective_sources(settings_override, text, allowed):
    settings_override(REPLY_DISCUSSIONS_ONLY=True)
    assert (reply_focus.parent_refusal(text) == "") is allowed


def test_generic_praise_is_refused_but_specific_help_remains_eligible(settings_override):
    settings_override(REPLY_DISCUSSIONS_ONLY=True)
    assert reply_focus.draft_refusal("Oh, I love this ❤️")
    assert reply_focus.draft_refusal("Great point!")
    assert not reply_focus.draft_refusal("A held-out split would catch that leakage before the benchmark.")


def test_unfamiliar_author_precedes_familiar_high_view_account(monkeypatch, memory_ledger, settings_override):
    from src.replies.reply_pipeline import Candidate, prioritize
    clock(monkeypatch, NOW)
    settings_override(REPLY_PREFER_NEW_AUTHORS=True, REPLY_PRIORITIZE_LARGE_ACCOUNTS=False)
    guard.record(guard.REPLY, numbered_url(80, "familiar"))
    familiar = Candidate(numbered_url(81, "familiar"), "LLM inference comparison", "SEARCH", likes=1000, views=100000)
    new = Candidate(numbered_url(82, "newbuilder"), "LLM inference comparison", "SEARCH", likes=0)
    assert prioritize([familiar, new], ordinary=True, diversify_authors=True) == [new, familiar]
