"""Every Reply needs its verified parent visibly liked before composition."""
import pytest

from src.core.state_errors import StateUnreadable
from src.guards import action_guard as ag, replied_store
from src.guards.active_hours import OutsideActiveHours
from src.x import safari, twitter_client as tc
from src.x.confirmed_write import WriteOutcome as W
from tests.helpers import numbered_url
from tests.x.test_likes import FakePage

URL = numbered_url(6100)
TEXT = "Batching is where inference margins are won or lost."


@pytest.fixture
def parent(monkeypatch, memory_ledger):
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(tc, "_activate_or_abort", lambda *a: True)
    monkeypatch.setattr(tc, "_open_or_abort", lambda *a: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    page = FakePage(page=URL, posts=[{"url": URL, "liked": False}])
    events = []
    def read(mode, target):
        events.append(mode)
        return page(mode, target)
    monkeypatch.setattr(tc, "_page_posts", read)
    monkeypatch.setattr(tc, "_reply_target", lambda url, click=False, **kw:
                        events.append("reply_button" if click else "verify_parent") or True)
    monkeypatch.setattr(tc, "_paste_or_abort", lambda *a: events.append("paste") or True)
    monkeypatch.setattr(tc, "_submit_or_abort", lambda *a, **kw: events.append("submit") or True)
    return page, events


@pytest.mark.parametrize("old_probability", [0.0, 0.3, 1.0])
def test_like_ships_before_reply_even_with_old_probability(parent, settings_override, memory_ledger, old_probability):
    settings_override(REPLY_LIKE_PARENT_PROB=old_probability)
    page, events = parent
    assert tc.reply_to_tweet(URL, TEXT) is W.SHIPPED
    assert events == ["verify_parent", "read", "press", "read", "read", "reply_button", "paste", "submit"]
    assert page.clicks == [URL]
    assert [r["action"] for r in memory_ledger.rows] == [ag.LIKE, ag.REPLY]


def test_existing_page_like_allows_reply_at_daily_like_cap(parent, settings_override, memory_ledger):
    settings_override(LIKE_BOT_DAILY_CAP=1)
    ag.record(ag.LIKE, numbered_url(6101))
    page, events = parent
    page.posts[0]["liked"] = True
    assert tc.reply_to_tweet(URL, TEXT) is W.SHIPPED
    assert not page.clicks and events.index("read") < events.index("reply_button")
    assert [r["action"] for r in memory_ledger.rows] == [ag.LIKE, ag.REPLY]


def test_like_cap_blocks_reply_and_releases_claim_for_later(parent, settings_override, memory_ledger):
    settings_override(LIKE_BOT_DAILY_CAP=1)
    ag.record(ag.LIKE, numbered_url(6101))
    page, events = parent
    assert tc.reply_to_tweet(URL, TEXT) is W.REFUSED
    assert not page.clicks and "reply_button" not in events
    assert URL not in replied_store.load_replied()
    settings_override(LIKE_BOT_DAILY_CAP=2)
    assert tc.reply_to_tweet(URL, TEXT) is W.SHIPPED
    assert [r["action"] for r in memory_ledger.rows] == [ag.LIKE, ag.LIKE, ag.REPLY]


def test_unconfirmed_like_blocks_reply_without_consuming_its_claim(parent, memory_ledger):
    page, events = parent
    page.click_sticks = False
    assert tc.reply_to_tweet(URL, TEXT) is W.REFUSED
    assert "reply_button" not in events and not memory_ledger.rows
    assert URL not in replied_store.load_replied()
    page.click_sticks = True
    assert tc.reply_to_tweet(URL, TEXT) is W.SHIPPED


def test_cached_like_alone_cannot_authorize_a_reply(parent, memory_ledger):
    tc._mark_liked(URL)
    page, events = parent
    assert tc.reply_to_tweet(URL, TEXT) is W.REFUSED
    assert not page.clicks and "reply_button" not in events and not memory_ledger.rows
    assert URL not in replied_store.load_replied()


@pytest.mark.parametrize("data", [{}, {"url": URL, "result": "failed"},
    {"url": numbered_url(6101), "result": "already_liked"},
    {"url": numbered_url(6100, "other"), "result": "already_liked"},
    {"url": URL.replace("x.com", "evilx.com"), "result": "already_liked"}])
def test_unreadable_or_wrong_like_state_blocks_reply(parent, monkeypatch, memory_ledger, data):
    monkeypatch.setattr(tc, "_page_posts", lambda *a: data)
    assert tc.reply_to_tweet(URL, TEXT) is W.REFUSED
    assert "reply_button" not in parent[1] and not memory_ledger.rows
    assert URL not in replied_store.load_replied()


@pytest.mark.parametrize("error", [StateUnreadable("bad ledger"), OutsideActiveHours("break"), RuntimeError("page failed")])
def test_like_errors_stop_reply_and_release_claim(parent, monkeypatch, memory_ledger, error):
    def fail(url):
        raise error
    monkeypatch.setattr(tc, "like_tweet", fail)
    with pytest.raises(type(error)):
        tc.reply_to_tweet(URL, TEXT)
    assert "reply_button" not in parent[1] and not memory_ledger.rows
    assert URL not in replied_store.load_replied()


@pytest.mark.parametrize("outcome", [tc.LikeOutcome.LIKED, tc.LikeOutcome.ALREADY_LIKED])
def test_like_outcome_alone_needs_a_final_page_confirmation(parent, monkeypatch, memory_ledger, outcome):
    monkeypatch.setattr(tc, "like_tweet", lambda url: outcome)
    assert tc.reply_to_tweet(URL, TEXT) is W.REFUSED
    assert "reply_button" not in parent[1] and not memory_ledger.rows


def test_target_disappearing_after_like_keeps_only_the_like_row(parent, monkeypatch, memory_ledger):
    page, events = parent
    real = tc._page_posts
    reads = 0
    def changed(mode, target):
        nonlocal reads
        reads += mode == "read"
        return {} if reads >= 3 else real(mode, target)
    monkeypatch.setattr(tc, "_page_posts", changed)
    assert tc.reply_to_tweet(URL, TEXT) is W.REFUSED
    assert "reply_button" not in events and page.clicks == [URL]
    assert [r["action"] for r in memory_ledger.rows] == [ag.LIKE]
    assert URL not in replied_store.load_replied()


def test_reply_dry_run_does_not_read_or_click_parent_like(parent, monkeypatch, memory_ledger):
    monkeypatch.setenv("DRY_RUN", "1")
    assert tc.reply_to_tweet(URL, TEXT) is W.DRY_RUN
    assert parent[1] == [] and not parent[0].clicks
    assert [r["action"] for r in memory_ledger.rows] == [ag.REPLY]
    assert memory_ledger.rows[0]["dry_run"]
