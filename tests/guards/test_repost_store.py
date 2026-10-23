"""Watched-author exception, permanent claims and shared publication budgets."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from src.core import account
from src.core.state_errors import StateUnreadable
from src.editorial.slot_journal import MemoryJournal, STATE as EDITORIAL
from src.guards import action_guard as ag, repost_store as store
from tests.helpers import TORONTO, clock

URL = "https://x.com/elonmusk/status/2063500000000000101"
NEXT = "https://x.com/elonmusk/status/2063500000000000102"


@pytest.mark.parametrize("url", [
    "https://evilx.com/elonmusk/status/1", "https://x.com.evil/elonmusk/status/1",
    "http://x.com/elonmusk/status/1", "https://x.com@evil/elonmusk/status/1",
    "https://x.com/someone/status/1", "https://x.com/i/status/1",
    "https://x.com/elonmusk/status/1/photo/1", "",
])
def test_repost_requires_an_exact_allowed_url(url):
    assert store.allowed_url(url) == ""
    assert not ag.can_post(ag.RETWEET, target=url)[0]


def test_empty_watch_list_and_own_handles_cannot_be_reposted(monkeypatch):
    original = account.current()
    for profile in (replace(original, auto_engage_handles=()),
                    replace(original, auto_engage_handles=(original.handle.lower(),))):
        monkeypatch.setattr(account, "current", lambda: profile)
        assert not store.allowed_url(URL)
        assert not store.allowed_url(f"https://x.com/{profile.handle}/status/1")


def test_claim_is_atomic_and_permanent_across_url_spellings():
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: store.claim(URL), range(16)))
    assert sum(results) == 1
    assert not store.claim(URL.replace("x.com/elonmusk", "twitter.com/ElonMusk") + "?s=20")
    assert store.contains(URL) and store.pending_today() == 1
    store.remember(URL, "shipped")
    assert store.pending_today() == 0 and not store.claim(URL)


def test_only_pending_claim_can_be_released():
    assert store.claim(URL)
    store.release(URL)
    assert store.claim(URL)
    store.remember(URL, "observed")
    store.release(URL)
    assert store.contains(URL)


@pytest.mark.parametrize("raw", ['{', '[]', '{"1": {}}'])
def test_corrupt_repost_history_refuses_without_overwrite(tmp_path, raw):
    path = tmp_path / "reposted_tweets.json"
    path.write_text(raw)
    with pytest.raises(StateUnreadable):
        store.claim(URL)
    assert path.read_text() == raw


def test_reposts_and_originals_share_spacing_and_pending_budget(monkeypatch, memory_ledger, settings_override):
    now = datetime(2026, 10, 23, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    settings_override(POST_JITTER_SECONDS=0, MAX_ORIGINALS_PER_DAY=2)
    assert ag.can_post(ag.RETWEET, target=URL)[0]
    assert store.claim(URL)
    assert not ag.can_post(ag.POST)[0]
    assert not ag.can_post(ag.RETWEET, target=NEXT)[0]
    clock(monkeypatch, now + timedelta(minutes=20))
    assert ag.can_post(ag.POST)[0]
    ag.record(ag.POST)
    clock(monkeypatch, now + timedelta(minutes=40))
    assert not ag.can_post(ag.POST)[0]
    assert not ag.can_post(ag.RETWEET, target=NEXT)[0]
    store.release(URL)
    assert ag.can_post(ag.RETWEET, target=NEXT)[0]


def test_confirmed_repost_spaces_the_next_original(monkeypatch, memory_ledger, settings_override):
    now = datetime(2026, 10, 23, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    settings_override(POST_JITTER_SECONDS=0)
    ag.record(ag.RETWEET, URL)
    assert ag.seconds_until_allowed(ag.POST) == ag.seconds_until_allowed(ag.RETWEET) == 1200
    clock(monkeypatch, now + timedelta(minutes=20))
    assert ag.can_post(ag.POST)[0]


def test_pending_originals_also_reserve_repost_slots(monkeypatch, memory_ledger, settings_override):
    now = datetime(2026, 10, 23, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    settings_override(MAX_ORIGINALS_PER_DAY=1)
    journal = MemoryJournal()
    journal.roll_to(now.date())
    journal.reserve("10:00", "https://example.com", "A pending original", now - timedelta(hours=1))
    EDITORIAL.write(journal._data)
    assert not ag.can_post(ag.RETWEET, target=URL)[0]


def test_quotes_stay_disabled_even_for_watched_authors():
    assert not ag.can_post(ag.QUOTE, target=URL)[0]
