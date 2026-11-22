"""Restricted Replies authorize only their own confirmed parent like."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from src.guards import action_guard as ag, replied_store, reply_budget, reply_parent_like, reply_selection, review_store
from src.x import confirmed_write, reply_metrics, safari, twitter_client as tc
from src.x.confirmed_write import WriteOutcome
from tests.helpers import numbered_url
from tests.x.test_likes import FakePage
from tests.x.test_reply_target import invited_source, mock_page


DRAFT = "The model needs a smaller batch for this GPU."


@pytest.fixture(params=[False, True], ids=["invited", "broad"])
def required_parent(request, monkeypatch, settings_override, memory_ledger):
    settings_override(REPLY_INVITED_ONLY=True, REPLY_CURATED_MODE=request.param,
                      REPLY_BROAD_DISCOVERY=request.param, REPLY_REQUIRE_PARENT_LIKE=True,
                      LIKE_BOT_DAILY_CAP=0, MIN_SECONDS_BETWEEN_REPLIES=8)
    url, source = invited_source()
    reply_selection.remember(url, source, "technical", {})
    route = [url]
    articles = [{"url": url, "text": source}]
    reply_clicks = mock_page(monkeypatch, articles, lambda: route[0])
    page = FakePage(page=url, posts=[{"url": url, "liked": False}])
    events = []
    def read(mode, target):
        result = page(mode, target)
        events.append((mode, result.get("result")))
        return {**result, "text": source, "likes": 50}
    monkeypatch.setattr(tc, "_page_posts", read)
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(tc.time, "sleep", lambda *a: None)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(tc, "_activate_or_abort", lambda *a, **k: True)
    monkeypatch.setattr(tc, "_open_or_abort", lambda *a, **k: True)
    def paste(*args):
        events.append(("paste", None))
        route[0] = "https://x.com/compose/post"
        articles.insert(0, {"url": url, "text": source, "dialog": True, "noTime": True})
        return True
    monkeypatch.setattr(tc, "_paste_or_abort", paste)
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **k: events.append(("submit", None)) or True)
    monkeypatch.setattr(reply_metrics, "capture", lambda *a, **k: numbered_url(899, "thesimaximalist"))
    return SimpleNamespace(url=url, source=source, page=page, events=events,
                           articles=articles, reply_clicks=reply_clicks, ledger=memory_ledger)


def send(parent, draft=DRAFT):
    return tc.reply_to_tweet(parent.url, draft, expected_text=parent.source)


def assert_no_reply(parent):
    assert not parent.reply_clicks
    assert ("submit", None) not in parent.events
    assert not replied_store.load_replied() and reply_budget.entries() == {}


def test_required_like_is_confirmed_before_reply_despite_zero_unrelated_like_budget(required_parent, monkeypatch):
    parent = required_parent
    real_target = tc._reply_target
    def target(url, *, click=False, **kwargs):
        if click:
            assert parent.page.posts[0]["liked"]
            assert ("read", "already_liked") in parent.events
        return real_target(url, click=click, **kwargs)
    monkeypatch.setattr(tc, "_reply_target", target)
    assert send(parent) is WriteOutcome.SHIPPED
    assert parent.page.clicks == [parent.url] and parent.reply_clicks == [parent.url]
    assert [r["action"] for r in parent.ledger.rows] == [ag.LIKE, ag.REPLY]
    assert reply_parent_like.expected_source(parent.url) is None
    assert tc.like_tweet(parent.url) is tc.LikeOutcome.REFUSED


def test_observed_existing_like_needs_no_toggle_or_new_like_row(required_parent):
    parent = required_parent
    parent.page.posts[0]["liked"] = True
    assert send(parent) is WriteOutcome.SHIPPED
    assert not parent.page.clicks
    assert [r["action"] for r in parent.ledger.rows] == [ag.REPLY]


@pytest.mark.parametrize("outcome", [tc.LikeOutcome.REFUSED, tc.LikeOutcome.FAILED,
                                    tc.LikeOutcome.UNCONFIRMED, tc.LikeOutcome.DRY_RUN])
def test_unconfirmed_or_refused_required_like_cannot_open_reply(required_parent, monkeypatch, outcome):
    parent = required_parent
    monkeypatch.setattr(tc, "like_tweet", lambda url: outcome)
    assert send(parent) is WriteOutcome.REFUSED
    assert_no_reply(parent)
    assert not parent.page.clicks and parent.ledger.rows == []
    assert reply_parent_like.expected_source(parent.url) is None


def test_real_uncertain_like_click_never_reaches_reply_composer(required_parent):
    parent = required_parent
    parent.page.click_sticks = False
    assert send(parent) is WriteOutcome.REFUSED
    assert parent.page.clicks == [parent.url]
    assert_no_reply(parent)
    assert parent.ledger.rows == []


def test_cached_like_cannot_replace_observed_state(required_parent):
    parent = required_parent
    tc._mark_liked(parent.url)
    assert send(parent) is WriteOutcome.REFUSED
    assert_no_reply(parent)
    assert not parent.page.clicks and parent.ledger.rows == []


def test_parent_authority_does_not_authorize_other_targets_workers_or_write_types(required_parent, monkeypatch):
    parent = required_parent
    other = numbered_url(898, "other")
    real = tc._ensure_parent_liked
    def ensure(url):
        assert reply_parent_like.allowed(url)
        assert not ag.can_post(ag.LIKE, target=other, reply_parent=True)[0]
        assert tc.like_tweet(other) is tc.LikeOutcome.REFUSED
        assert not ag.can_post(ag.RETWEET, target=url)[0]
        assert confirmed_write.run("REPOST", WriteOutcome, would=lambda: "repost",
            rows=lambda: [(ag.RETWEET, url)], steps=lambda: pytest.fail("ordinary repost authorized"),
            before_lock=(confirmed_write.DRY_RUN_EXIT,)) is WriteOutcome.REFUSED
        with ThreadPoolExecutor(1) as pool:
            assert pool.submit(tc.like_tweet, url).result(timeout=2) is tc.LikeOutcome.REFUSED
        return real(url)
    monkeypatch.setattr(tc, "_ensure_parent_liked", ensure)
    assert send(parent) is WriteOutcome.SHIPPED
    assert not ag.can_post(ag.LIKE, target=parent.url, reply_parent=True)[0]
    assert not reply_parent_like.allowed(parent.url)


def test_source_change_before_required_like_refuses_without_clicking(required_parent, monkeypatch):
    parent = required_parent
    real = tc._ensure_parent_liked
    def ensure(url):
        parent.articles[0]["text"] = parent.source + " Changed after the original check."
        return real(url)
    monkeypatch.setattr(tc, "_ensure_parent_liked", ensure)
    assert send(parent) is WriteOutcome.REFUSED
    assert_no_reply(parent)
    assert not parent.page.clicks and parent.ledger.rows == []


def test_required_like_uses_verified_full_source_not_truncated_like_card(required_parent, monkeypatch):
    parent = required_parent
    real = tc._page_posts
    def truncated(mode, target):
        return {**real(mode, target), "text": "Can you help with this?"}
    monkeypatch.setattr(tc, "_page_posts", truncated)
    assert send(parent) is WriteOutcome.SHIPPED
    assert parent.page.clicks == [parent.url]
    assert [r["action"] for r in parent.ledger.rows] == [ag.LIKE, ag.REPLY]


def test_opt_out_arriving_before_like_revokes_the_required_scope(required_parent, monkeypatch):
    parent = required_parent
    real = tc._ensure_parent_liked
    def ensure(url):
        review_store.record_opt_out("builder", "Do not contact me")
        return real(url)
    monkeypatch.setattr(tc, "_ensure_parent_liked", ensure)
    assert send(parent) is WriteOutcome.REFUSED
    assert_no_reply(parent)
    assert not parent.page.clicks and parent.ledger.rows == []


def test_refused_draft_never_likes_a_parent(required_parent):
    parent = required_parent
    assert send(parent, "Great post") is WriteOutcome.REFUSED
    assert_no_reply(parent)
    assert not parent.page.clicks and parent.ledger.rows == []


def test_parent_scope_is_released_after_like_error(required_parent, monkeypatch):
    parent = required_parent
    def fail(*args):
        raise RuntimeError("Like read failed")
    monkeypatch.setattr(tc, "like_tweet", fail)
    with pytest.raises(RuntimeError, match="Like read failed"):
        send(parent)
    assert_no_reply(parent)
    assert not parent.page.clicks and parent.ledger.rows == []
    assert reply_parent_like.expected_source(parent.url) is None
    assert not tc._REPLY_LIKE_PARENT.get()


def test_disabled_feature_preserves_invited_transport_without_parent_like(required_parent, settings_override, monkeypatch):
    parent = required_parent
    settings_override(REPLY_REQUIRE_PARENT_LIKE=False)
    monkeypatch.setattr(tc, "_ensure_parent_liked", lambda *a: pytest.fail("disabled feature liked parent"))
    assert send(parent) is WriteOutcome.SHIPPED
    assert not parent.page.clicks
    assert [r["action"] for r in parent.ledger.rows] == [ag.REPLY]
