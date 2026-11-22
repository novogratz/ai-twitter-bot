from datetime import timedelta

import pytest

from src.core import account
from src.guards import active_hours, self_repost_store as store
from src.x import repost_page, safari, twitter_client as tc, x_urls
from src.x.confirmed_write import WriteOutcome as W
from tests.helpers import clock, fresh

pytestmark = pytest.mark.usefixtures("promotion_account")


@pytest.fixture
def browser(monkeypatch, memory_ledger):
    monkeypatch.setenv("DRY_RUN", "0")
    now = active_hours.now_local()
    clock(monkeypatch, now)
    store.activate()
    sid = (int(now.timestamp() * 1000) - x_urls._TWITTER_EPOCH_MS) << 22
    url = f"https://x.com/{account.current().handle}/status/{sid}"
    store.observe(url, 50001)
    state = dict(url=url, views=50001, reposted=False, modes=[], lost=False, stick=True)
    clock(monkeypatch, now + timedelta(hours=1, seconds=1))
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(safari, "open_url", lambda *_: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)

    def page(url, mode):
        state["modes"].append(mode)
        result = dict(url=url, text="My original SI video", state="reposted" if state["reposted"] else "ready", views=state["views"])
        if mode in {"self_open", "self_undo_open"}:
            result["state"] = "menu_opened"
        elif mode == "self_undo_confirm":
            state["reposted"] = False
            result["state"] = "undo_submitted"
        elif mode == "self_confirm":
            state["reposted"] = state["stick"]
            if state["lost"]:
                return {}
            result["state"] = "submitted"
        return result

    monkeypatch.setattr(repost_page, "read", page)
    return state


def test_one_hour_timer_and_half_hour_cadence_survive_rereads(browser, monkeypatch, memory_ledger):
    row = store.read()["posts"][x_urls.status_id(browser["url"])]
    clock(monkeypatch, active_hours.now_local() - timedelta(seconds=2))
    assert not store.due(row, row["first_due"] - .001)
    assert store.due(row, row["first_due"])
    assert tc.repost_own_post(browser["url"]) is W.REFUSED
    assert not browser["modes"]
    clock(monkeypatch, active_hours.now_local() + timedelta(seconds=2))
    assert tc.repost_own_post(browser["url"]) is W.SHIPPED
    assert tc.repost_own_post(browser["url"]) is W.REFUSED
    clock(monkeypatch, active_hours.now_local() + timedelta(minutes=30))
    assert tc.repost_own_post(browser["url"]) is W.SHIPPED
    assert browser["modes"].count("self_undo_confirm") == 1
    assert browser["modes"].count("self_confirm") == 2
    assert len(memory_ledger.rows) == 2


@pytest.mark.parametrize("views", [None, 0, 49999, 50000, "50001", True])
def test_refresh_requires_strictly_above_50k_fresh_numeric_views(browser, monkeypatch, views):
    assert tc.repost_own_post(browser["url"]) is W.SHIPPED
    clock(monkeypatch, active_hours.now_local() + timedelta(minutes=30))
    browser["views"] = views
    assert tc.repost_own_post(browser["url"]) is W.REFUSED
    assert "self_undo_confirm" not in browser["modes"]


def test_lost_send_reconciles_visible_repost_without_another_click(browser, monkeypatch, memory_ledger):
    browser["lost"] = True
    assert tc.repost_own_post(browser["url"]) is W.UNCONFIRMED
    assert not memory_ledger.rows
    assert store.read()["posts"][x_urls.status_id(browser["url"])]["phase"] == "repost_pending"
    clock(monkeypatch, active_hours.now_local() + timedelta(minutes=5))
    assert tc.repost_own_post(browser["url"]) is W.SHIPPED
    assert browser["modes"].count("self_confirm") == 1
    assert len(memory_ledger.rows) == 1


def test_ambiguous_missing_repost_holds_across_ticks(browser, monkeypatch):
    browser.update(lost=True, stick=False)
    assert tc.repost_own_post(browser["url"]) is W.UNCONFIRMED
    clock(monkeypatch, active_hours.now_local() + timedelta(minutes=30))
    assert tc.repost_own_post(browser["url"]) is W.UNCONFIRMED
    assert browser["modes"].count("self_confirm") == 1


def test_other_author_never_enters_own_schedule(browser):
    other = fresh("other", minutes=0)
    store.observe(other, 900000)
    assert x_urls.status_id(other) not in store.read()["posts"]
    assert tc.repost_own_post(other) is W.REFUSED


def test_initial_already_reposted_marks_satisfied_without_undo(browser, memory_ledger):
    browser["reposted"] = True
    assert tc.repost_own_post(browser["url"]) is W.REFUSED
    assert browser["modes"] == ["self_read"]
    assert not memory_ledger.rows


def test_interrupted_undo_finishes_same_operation_without_undoing_twice(browser, monkeypatch):
    assert tc.repost_own_post(browser["url"]) is W.SHIPPED
    clock(monkeypatch, active_hours.now_local() + timedelta(minutes=30))
    original = repost_page.read
    def lose_undo(url, mode):
        result = original(url, mode)
        return {} if mode == "self_undo_confirm" else result
    monkeypatch.setattr(repost_page, "read", lose_undo)
    assert tc.repost_own_post(browser["url"]) is W.UNCONFIRMED
    assert store.read()["posts"][x_urls.status_id(browser["url"])]["phase"] == "undo_pending"
    clock(monkeypatch, active_hours.now_local() + timedelta(minutes=5))
    assert tc.repost_own_post(browser["url"]) is W.SHIPPED
    assert browser["modes"].count("self_undo_confirm") == 1
    assert browser["modes"].count("self_confirm") == 2


def test_sleep_defers_without_changing_timer_or_touching_browser(browser, monkeypatch):
    prior = store.read()
    monkeypatch.setattr(active_hours, "may_act", lambda: False)
    assert tc.repost_own_post(browser["url"]) is W.REFUSED
    assert store.read() == prior and not browser["modes"]
