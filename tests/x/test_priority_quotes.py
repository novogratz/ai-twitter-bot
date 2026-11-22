from datetime import timedelta

import pytest

from src.core import account
from src.guards import active_hours, quote_store
from src.x import quote_page, repost_page, safari, twitter_client as tc
from src.x.confirmed_write import WriteOutcome as W
from tests.helpers import clock, fresh

pytestmark = pytest.mark.usefixtures("promotion_account")


@pytest.fixture
def browser(monkeypatch, memory_ledger):
    monkeypatch.setenv("DRY_RUN", "0")
    clock(monkeypatch, active_hours.now_local())
    url = fresh("elonmusk")
    source = "The new SI video model is available today."
    quote_store.save_review(url, text="That is a useful new tool for independent artists.",
                            source_text=source, impact=9, approved=True)
    state = dict(url=url, source=source, submit={"ready": True}, prepares=[], clicks=[],
                 receipt=fresh(account.current().handle, minutes=0))
    monkeypatch.setattr(tc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(safari, "open_url", lambda *_: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(repost_page, "read", lambda *a, **k: dict(url=url, text=state["source"], language="en", state="ready"))
    monkeypatch.setattr(quote_page, "prepare", lambda *a: state["prepares"].append(a) or True)
    monkeypatch.setattr(quote_page, "composer", lambda *a: state["clicks"].append(a) or state["submit"])
    monkeypatch.setattr(quote_page, "receipt", lambda *a: state["receipt"])
    return state


def test_quote_requires_exact_receipt_and_cannot_repeat(browser, memory_ledger):
    assert tc.quote_priority_post(browser["url"]) is W.SHIPPED
    assert tc.quote_priority_post(browser["url"]) is W.REFUSED
    assert len(browser["clicks"]) == len(memory_ledger.rows) == 1
    assert quote_store.entries()[browser["url"].split('/')[-1]]["state"] == "shipped"


@pytest.mark.parametrize("failure", ["source_changed", "receipt_missing", "lost_submit", "proven_no_click"])
def test_quote_failure_keeps_only_possibly_submitted_claims(browser, failure, memory_ledger):
    if failure == "source_changed":
        browser["source"] = "An entirely different update about SI."
    elif failure == "receipt_missing":
        browser["receipt"] = ""
    elif failure == "lost_submit":
        browser["submit"] = {}
    else:
        browser["submit"] = {"ready": False}
    assert not tc.quote_priority_post(browser["url"])
    row = quote_store.entries()[browser["url"].split('/')[-1]]
    assert row["state"] == ("pending" if failure in {"receipt_missing", "lost_submit"} else "approved")
    assert not memory_ledger.rows
    if failure == "source_changed":
        assert not browser["prepares"] and not browser["clicks"]


def test_dry_quote_creates_no_live_claim_or_browser_write(browser, monkeypatch, memory_ledger):
    monkeypatch.setenv("DRY_RUN", "1")
    assert tc.quote_priority_post(browser["url"]) is W.DRY_RUN
    assert not browser["clicks"]
    assert memory_ledger.rows[0]["dry_run"]
