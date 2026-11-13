from datetime import timedelta
from types import SimpleNamespace
import json

import pytest

from src.core.llm_client import LLMStatus
from src.guards import action_guard as ag, active_hours, meme_repost_store as store, repost_store
from src.x import twitter_client as tc, repost_page, safari, x_urls
from tests.helpers import clock, fresh


@pytest.fixture
def meme(monkeypatch, settings_override, memory_ledger):
    settings_override(MEME_REPOST_ENABLED=True, VIDEO_ENABLED=True)
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(store, "_candidates", {})
    clock(monkeypatch, active_hours.now_local())
    return dict(url=fresh("comedian"), text="My AI agent spent all night automating a task I could have done in two minutes.",
                language="en", likes=1000, views=200000, state="ready")


@pytest.mark.parametrize("changes", [dict(likes=499), dict(likes=True), dict(views=99999), dict(views=None),
                                    dict(views="200000"), dict(is_reply=True), dict(text="Crypto trading giveaway AI"),
                                    dict(text="My coffee is cold"), dict(url="https://elsewhere.test/comedian/status/123")])
def test_meme_counts_topic_and_exact_original_are_required(meme, changes):
    assert store.qualifies(meme)
    assert not store.qualifies({**meme, **changes})


def test_meme_budget_dedup_and_uncertain_claim_survive_rereads(meme, monkeypatch):
    url = meme["url"]
    store.review(url, meme["text"], True, "self-contained humor", humor_score=9)
    assert ag.can_post(ag.MEME_REPOST, target=url)[0]
    assert not ag.can_post(ag.MEME_REPOST)[0]
    assert not ag.can_post(ag.RETWEET, target=url)[0]
    assert repost_store.claim(url, kind="meme")
    assert not ag.can_post(ag.MEME_REPOST, target=url)[0]
    second = fresh("comedian", n=1)
    store.review(second, meme["text"], True, "another joke", humor_score=9)
    assert "uncertain" in store.refusal(second)
    repost_store.remember(url, "shipped", kind="meme")
    assert "spacing" in store.refusal(second)
    clock(monkeypatch, active_hours.now_local() + timedelta(hours=4))
    assert ag.can_post(ag.MEME_REPOST, target=second)[0]
    assert repost_store.claim(second, kind="meme")
    repost_store.remember(second, "shipped", kind="meme")
    assert "cap" in store.refusal()
    assert repost_store.contains(url) and repost_store.contains(second)


@pytest.mark.parametrize("lost", [False, True])
def test_meme_write_checks_review_and_preserves_ambiguous_submission(meme, monkeypatch, memory_ledger, lost):
    store.review(meme["url"], meme["text"], True, "funny", humor_score=9)
    monkeypatch.setattr(safari, "open_url", lambda *_: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    modes = []
    def page(url, mode="read"):
        modes.append(mode)
        if mode == "meme_open": return {**meme, "state": "menu_opened"}
        if mode == "meme_confirm": return {} if lost else {**meme, "state": "submitted"}
        return {**meme, "state": "reposted" if "meme_confirm" in modes else "ready"}
    monkeypatch.setattr(repost_page, "read", page)
    result = tc.repost_meme(meme["url"])
    assert result is (tc.WriteOutcome.UNCONFIRMED if lost else tc.WriteOutcome.SHIPPED)
    assert modes.count("meme_confirm") == 1
    assert repost_store.entries()[x_urls.status_id(meme["url"])]["status"] == ("pending" if lost else "shipped")
    assert len(memory_ledger.rows) == (0 if lost else 1)
    assert tc.repost_meme(meme["url"]) is tc.WriteOutcome.REFUSED


@pytest.mark.parametrize("changed", [dict(text="My AI agent now writes all my production code."),
                                    dict(likes=None), dict(views=99999)])
def test_meme_source_and_counts_rechecked_before_confirmation(meme, monkeypatch, changed):
    store.review(meme["url"], meme["text"], True, "funny", humor_score=9)
    monkeypatch.setattr(safari, "open_url", lambda *_: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    modes = []
    def page(url, mode="read"):
        modes.append(mode)
        if mode == "meme_open":
            return {**meme, "state": "menu_opened"}
        assert mode != "meme_confirm", "changed/unverified source must never be submitted"
        return {**meme, **(changed if "meme_open" in modes else {})}
    monkeypatch.setattr(repost_page, "read", page)
    assert tc.repost_meme(meme["url"]) is tc.WriteOutcome.REFUSED
    assert "meme_open" in modes and not repost_store.contains(meme["url"])


@pytest.mark.parametrize("score,self_contained,writes", [(8, True, 0), (9, False, 0), (9, True, 1)])
def test_meme_review_cannot_approve_on_popularity_or_unseen_media(meme, monkeypatch, score, self_contained, writes):
    from src.account import meme_repost_bot as job
    store.offer([meme])
    monkeypatch.setattr(tc, "read_meme_post", lambda _: meme)
    monkeypatch.setattr(job, "run_llm", lambda *a, **k: SimpleNamespace(status=LLMStatus.ANSWERED, stdout=json.dumps(
        dict(approved=True, ai_related=True, self_contained=self_contained, safe_to_amplify=True,
             humor_score=score, reason="humor review"))))
    sent=[]
    monkeypatch.setattr(tc, "repost_meme", lambda url: sent.append(url))
    job.run_meme_repost_cycle()
    assert len(sent) == writes
