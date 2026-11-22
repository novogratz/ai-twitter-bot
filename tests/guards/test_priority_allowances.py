from datetime import timedelta

import pytest

from src.core import account
from src.guards import action_guard as ag, active_hours, repost_store
from src.x import repost_page, safari, twitter_client as tc
from tests.helpers import clock, fresh

pytestmark = pytest.mark.usefixtures("promotion_account")


def test_watched_reposts_coexist_with_video_and_do_not_spend_original_budget(settings_override, memory_ledger, monkeypatch):
    settings_override(VIDEO_ENABLED=True)
    clock(monkeypatch, active_hours.now_local())
    for _ in range(12):
        ag.record(ag.POST)
    url = fresh("elonmusk")
    assert ag.can_post(ag.RETWEET, target=url)[0]
    assert not ag.can_post(ag.RETWEET, target=fresh("other"))[0]
    assert not ag.can_post(ag.POST)[0]
    assert repost_store.claim(url)
    assert repost_store.pending_today() == 0  # independent claim still exists permanently
    assert not ag.can_post(ag.RETWEET, target=fresh("elonmusk", n=1))[0]
    clock(monkeypatch, active_hours.now_local() + timedelta(seconds=60))
    assert ag.can_post(ag.RETWEET, target=fresh("elonmusk", n=1))[0]
    assert repost_store.contains(url)


def test_verified_watched_like_survives_background_cap_without_granting_other_targets(monkeypatch, settings_override, memory_ledger):
    settings_override(LIKE_BOT_DAILY_CAP=1)
    monkeypatch.setenv("DRY_RUN", "0")
    ag.record(ag.LIKE, fresh("other"))
    url, calls = fresh("elonmusk"), []
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(safari, "open_url", lambda *_: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(repost_page, "read", lambda *_: dict(url=url, text="The next Starship launch is coming soon.", language="en", state="ready"))
    def like(target):
        calls.append(tc._REPLY_LIKE_PARENT.get())
        assert tc._REPLY_LIKE_PARENT.get() == target
        return tc.LikeOutcome.LIKED
    monkeypatch.setattr(tc, "like_tweet", like)
    assert tc.like_priority_post(url) is tc.LikeOutcome.LIKED
    assert calls == [url] and not tc._REPLY_LIKE_PARENT.get()
    assert not ag.can_post(ag.LIKE)[0]


def test_unverified_watched_page_does_not_get_the_like_exception(monkeypatch, memory_ledger):
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(safari, "open_url", lambda *_: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(repost_page, "read", lambda *_: {})
    monkeypatch.setattr(tc, "like_tweet", lambda *_: pytest.fail("unverified parent liked"))
    assert tc.like_priority_post(fresh("elonmusk")) is tc.LikeOutcome.REFUSED
