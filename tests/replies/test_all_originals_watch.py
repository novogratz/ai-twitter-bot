"""Independent watched actions do not borrow or weaken Reply approval."""
from dataclasses import replace
from datetime import timedelta

import pytest

from src.core import account
from src.guards import action_guard, active_hours, reply_budget, reply_selection, repost_store, watch_curation
from src.replies import curated_reposts, priority_watch, reply_pipeline
from src.x import repost_page, safari, twitter_client, x_urls
from tests.helpers import clock
from tests.replies.test_selective_watch import NOW, TEXT, approve, fast, page, url, verdict


@pytest.fixture(autouse=True)
def all_originals(fast, monkeypatch, settings_override):
    profile = replace(account.current(), auto_engage_all_topics=True, watched_reposts_independent=True)
    monkeypatch.setattr(account, "current", lambda: profile)
    settings_override(MAX_REPLIES_PER_DAY=1400, MIN_SECONDS_BETWEEN_REPLIES=8,
                      CURATED_WATCH_REPLIES_PER_DAY=1400, CURATED_WATCH_REPOSTS_PER_DAY=1400,
                      CURATED_WATCH_REPLY_MIN_SECONDS=8, CURATED_WATCH_REPOST_MIN_SECONDS=60,
                      PRIORITY_REPOST_MIN_SECONDS=60)
    priority_watch.STATE.write({"elonmusk": (NOW - timedelta(days=1)).isoformat()})


def browser(monkeypatch):
    opened, closed = [], []
    monkeypatch.setattr(twitter_client.time, "sleep", lambda *_: None)
    monkeypatch.setattr(twitter_client, "_open_or_abort", lambda target, *a: opened.append(target) or True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: closed.append(True))
    return opened, closed


def test_new_all_topic_originals_keep_actions_after_the_reply_window(monkeypatch):
    recent = page(parent=url(age=20), text="The weather is lovely today.")
    older = page(parent=url(age=120), text="An election debate starts tonight.")
    pre_enable = page(parent=url(age=700), text="A previous post.")
    boundary = NOW - timedelta(minutes=10)
    candidates = priority_watch._candidates("elonmusk", [recent, older, pre_enable,
        dict(page(parent=url("other")), text=TEXT), dict(page(parent=url(n=3)), is_reply=True)], boundary)
    assert [row.url for row in candidates] == [recent["url"], older["url"]]
    priority_watch.observe([recent, older])
    assert set(priority_watch._pending) == {recent["url"], older["url"]}
    writes = []
    monkeypatch.setattr(priority_watch, "discovered", lambda: candidates)
    monkeypatch.setattr(twitter_client, "like_priority_post", lambda target:
                        writes.append(("like", target)) or twitter_client.LikeOutcome.LIKED)
    monkeypatch.setattr(twitter_client, "repost_tweet", lambda target:
                        writes.append(("repost", target)) or twitter_client.WriteOutcome.SHIPPED)
    monkeypatch.setattr(reply_pipeline, "run", lambda *a, **k: pytest.fail("unapproved Reply dispatched"))
    priority_watch.run_priority_actions_cycle()
    priority_watch.run_priority_reply_cycle()
    assert writes == [(action, row.url) for row in candidates for action in ("like", "repost")]
    assert not watch_curation._reviews


def test_all_topic_action_permission_never_approves_political_or_expired_replies():
    political = approve(page(text="Grok has changed the election debate."))
    expired = approve(page(parent=url(age=61)))
    for source in (political, expired):
        assert watch_curation.independent_actions(source["url"])
        assert watch_curation.actions_fresh(source["url"])
        assert not watch_curation.selected(source["url"])
    assert not account.watched_topic_allowed(political["text"], url=political["url"])
    assert not watch_curation.independent_actions(url("other"))
    assert not watch_curation.actions_fresh(url(age=24 * 3600 + 1))


def test_verified_watched_like_needs_no_model_review_and_stays_idempotent(monkeypatch, settings_override):
    source = page(parent=url(age=120), text="The sunset looks lovely tonight.")
    opened, closed = browser(monkeypatch)
    settings_override(LIKE_BOT_DAILY_CAP=1)
    action_guard.record(action_guard.LIKE, url("other"))
    monkeypatch.setattr(repost_page, "read", lambda *a: source)
    presses = []

    def parent(mode, target):
        if mode == "press":
            presses.append(target)
        result = "clicked" if mode == "press" else "already_liked" if presses else "ready"
        return dict(source, result=result)

    monkeypatch.setattr(twitter_client, "_page_posts", parent)
    assert twitter_client.like_priority_post(source["url"]) is twitter_client.LikeOutcome.LIKED
    assert twitter_client.like_priority_post(source["url"]) is twitter_client.LikeOutcome.ALREADY_LIKED
    assert presses == [x_urls.status_id(source["url"])]
    assert opened == [source["url"]] and closed == [True]
    assert not watch_curation._reviews


def test_watched_like_refuses_a_different_exact_source(monkeypatch):
    requested = url(age=120)
    browser(monkeypatch)
    monkeypatch.setattr(repost_page, "read", lambda *a: page(parent=url("other")))
    monkeypatch.setattr(twitter_client, "like_tweet", lambda *a: pytest.fail("liked a different source"))
    assert twitter_client.like_priority_post(requested) is twitter_client.LikeOutcome.REFUSED


@pytest.mark.parametrize("uncertain", [False, True])
def test_unreviewed_repost_retains_confirmed_and_uncertain_claims(monkeypatch, uncertain):
    source = page(parent=url(age=120), text="The sunset looks lovely tonight.")
    opened, closed = browser(monkeypatch)
    submitted = []

    def read(target, mode):
        assert target == source["url"]
        if mode == "meme_open":
            return dict(source, state="menu_opened")
        if mode == "meme_confirm":
            submitted.append(True)
            return {} if uncertain else dict(source, state="submitted")
        return dict(source, state="reposted" if submitted else "ready")

    monkeypatch.setattr(repost_page, "read", read)
    expected = twitter_client.WriteOutcome.UNCONFIRMED if uncertain else twitter_client.WriteOutcome.SHIPPED
    assert twitter_client.repost_tweet(source["url"]) is expected
    assert repost_store.contains(source["url"])
    assert repost_store.entries()[x_urls.status_id(source["url"])]["status"] == ("pending" if uncertain else "shipped")
    assert twitter_client.repost_tweet(source["url"]) is twitter_client.WriteOutcome.REFUSED
    assert opened == [source["url"]] and closed == [True] and submitted == [True]


@pytest.mark.parametrize("change", [{"text": "The sky is clear tonight."}, {"media_id": "changed"}])
def test_independent_repost_still_requires_unchanged_source_before_confirm(monkeypatch, change):
    source = page(parent=url(age=120), text="The sunset looks lovely tonight.")
    browser(monkeypatch)
    reads = []

    def read(target, mode):
        assert mode != "meme_confirm", "confirmed a changed source"
        if mode == "meme_open":
            return dict(source, state="menu_opened")
        reads.append(True)
        return dict(source, **change) if len(reads) > 1 else source

    monkeypatch.setattr(repost_page, "read", read)
    assert twitter_client.repost_tweet(source["url"]) is twitter_client.WriteOutcome.REFUSED
    assert not repost_store.contains(source["url"])


@pytest.mark.parametrize("repost_cap", [0, 1400])
def test_repost_completion_or_capacity_does_not_suppress_fresh_reply_review(monkeypatch, settings_override, repost_cap):
    settings_override(CURATED_WATCH_REPOSTS_PER_DAY=repost_cap)
    source = page()
    repost_store.remember(source["url"], "observed")
    assert watch_curation.refusal(source["url"])
    candidate = reply_pipeline.Candidate(source["url"], source["text"], "WATCH", likes=12)
    monkeypatch.setattr(priority_watch, "discovered", lambda: [candidate])
    monkeypatch.setattr(twitter_client, "read_priority_post", lambda target: source)
    monkeypatch.setattr(curated_reposts, "_fast_review", lambda value: (verdict(), "test", "test-model"))
    monkeypatch.setattr(twitter_client, "repost_tweet", lambda *a: pytest.fail("selector reposted a claimed source"))
    curated_reposts.run_cycle()
    assert watch_curation.selected(source["url"])["reply"] == "Nice upgrade"


def test_watched_reply_capacity_uses_shared_settings_and_counts_pending(settings_override):
    records = {x_urls.status_id(url(n=i)): dict(target=url(n=i), status="pending",
        submitted_at=(NOW - timedelta(seconds=30 + i)).isoformat()) for i in range(4)}
    reply_budget.STATE.write(records)
    assert reply_budget.refusal(url(n=8)) == ""  # fourth earlier Reply is no six-hour hold
    settings_override(CURATED_WATCH_REPLIES_PER_DAY=4)
    assert "watched-author Reply daily cap" in reply_budget.refusal(url(n=8))
    settings_override(CURATED_WATCH_REPLIES_PER_DAY=1400)
    records[x_urls.status_id(url(n=5))] = dict(target=url(n=5), status="pending",
        submitted_at=(NOW - timedelta(seconds=7)).isoformat())
    reply_budget.STATE.write(records)
    assert "8-second" in reply_budget.refusal(url(n=8))
    settings_override(MAX_REPLIES_PER_DAY=5)
    assert "5/5" in reply_budget.refusal(url(n=8))


def test_watched_repost_capacity_and_sixty_second_gap_include_uncertain_claims(settings_override):
    records = {x_urls.status_id(url(age=120, n=i)): dict(url=url(age=120, n=i), status="pending",
        ts=(NOW - timedelta(seconds=61 + i)).isoformat(), independent=True) for i in range(4)}
    repost_store.STATE.write(records)
    target = url(age=120, n=8)
    assert not watch_curation.refusal(target)
    assert repost_store.claim(target)
    assert "60-second" in watch_curation.refusal(url(n=9))
    assert not repost_store.claim(url(n=9))
    settings_override(CURATED_WATCH_REPOSTS_PER_DAY=5)
    assert "cap" in watch_curation.refusal(url(n=9))
    assert len(repost_store.entries()) == 5


def test_watched_action_queue_keeps_first_enable_boundary_after_reply_expiry(monkeypatch):
    parent = url(age=120)
    boundary = x_urls.posted_at(parent) + timedelta(seconds=1)
    assert priority_watch._candidates("elonmusk", [page(parent=parent)], boundary) == []
    clock(monkeypatch, NOW + timedelta(hours=25))
    assert not watch_curation.actions_fresh(parent)
