from dataclasses import replace
from datetime import timedelta

import pytest

from src.core import account
from src.core.state_errors import StateUnreadable
from src.guards import action_guard, active_hours, quote_store as store
from tests.helpers import clock, fresh


@pytest.fixture
def enabled(monkeypatch, memory_ledger, settings_override):
    monkeypatch.setenv("DRY_RUN", "0")
    profile = replace(account.current(), priority_quotes_enabled=True)
    monkeypatch.setattr(account, "current", lambda: profile)
    now = active_hours.now_local()
    clock(monkeypatch, now)
    settings_override(PRIORITY_QUOTE_DAILY_CAP=2, PRIORITY_QUOTE_INTERVAL_MINUTES=240)
    return now


def approve(url):
    store.save_review(url, text="That is a useful new tool for independent artists.",
                      source_text="The new SI video model is available today.", impact=9, approved=True)


def test_review_claim_and_receipt_survive_restart_without_replaying(enabled):
    url = fresh("elonmusk")
    approve(url)
    assert store.claim(url)
    assert not store.claim(url)
    assert store.refusal(fresh("elonmusk", n=1)).startswith("uncertain")
    store.confirm(url, fresh(account.current().handle, minutes=0))
    assert not store.claim(url)
    assert "spacing" in store.refusal()


def test_caps_include_confirmed_quotes_even_if_ledger_write_was_lost(enabled, monkeypatch):
    for i in range(2):
        now = enabled + timedelta(hours=i * 5)
        clock(monkeypatch, now)
        url = fresh("elonmusk", n=i)
        approve(url)
        assert store.claim(url)
        store.confirm(url, fresh(account.current().handle, minutes=0, n=i))
    clock(monkeypatch, enabled + timedelta(hours=10))
    assert "cap" in store.refusal()


def test_no_unapproved_unknown_other_author_or_stale_quote(enabled, settings_override):
    settings_override(VIDEO_ENABLED=True)
    for url in ("", fresh("other"), fresh("elonmusk", minutes=1500)):
        assert not action_guard.can_post(action_guard.QUOTE, target=url)[0]
        assert not store.claim(url)
    assert not store.claim(fresh("elonmusk"))


def test_presubmit_release_preserves_approved_bytes(enabled):
    url = fresh("elonmusk")
    approve(url)
    before = store.entries()
    assert store.claim(url)
    store.release(url)
    assert store.entries() == before


@pytest.mark.parametrize("row", [{}, {"url": "bad", "state": "shipped"}])
def test_corrupt_history_refuses(enabled, row):
    store.STATE.write({"123": row})
    with pytest.raises(StateUnreadable):
        store.refusal()
