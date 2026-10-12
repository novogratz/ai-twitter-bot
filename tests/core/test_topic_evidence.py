"""Saved handles need fresh topic evidence before they can steer discovery."""
from datetime import timedelta

import pytest

from src.core import topic_evidence as evidence
from src.guards.active_hours import now_local
from src.core.state_errors import StateUnreadable
from tests.helpers import fresh_local


def row(author="modelbuilder", text="SI model evaluation needs repeatable tests.", minutes=1, **changes):
    url = fresh_local(author, minutes=minutes)
    stamp = now_local().isoformat()
    return dict(url=url, text=text, state="ready", sources=["TOPIC"], first_seen=stamp,
                last_seen=stamp, reviewed_at=stamp, angle="Evaluate reliability", score=95,
                eligible=True, on_topic=True, **changes)


def save(value):
    evidence.POOL.write({value["url"].rsplit("/", 1)[1]: value})


def test_fresh_semantic_topic_evidence_reaches_engage_and_optional_search():
    from src.account import engage_bot
    from src.replies.reply_agent import _load_discovered_handles
    save(row())
    assert evidence.approved_authors() == ["modelbuilder"]
    assert "modelbuilder" in engage_bot._build_pool()
    assert "modelbuilder" in _load_discovered_handles(limit=100)


@pytest.mark.parametrize("changes", [
    {"on_topic": False}, {"on_topic": None}, {"eligible": False}, {"is_reply": True},
    {"state": "observed"}, {"text": "SI trading bots for Bitcoin"},
    {"text": "SI-powered Bittensor staking"}, {"text": "My lunch was great"},
    {"minutes": 25 * 60}, {"author": "TheBTCTherapist"},
])
def test_old_unreviewed_or_excluded_candidates_never_become_discovery_evidence(changes):
    changes = dict(changes)
    value = row(author=changes.pop("author", "modelbuilder"), minutes=changes.pop("minutes", 1))
    value.update(changes)
    if value.get("on_topic") is None:
        value.pop("on_topic")  # Old records have no explicit topic verdict.
    save(value)
    assert evidence.approved_authors() == []


def test_legacy_saved_handles_alone_cannot_repopulate_engage():
    from src.core.dynamic_strategy import DYNAMIC_ACCOUNTS, DISCOVERED_ACCOUNTS
    from src.account import account_curator, engage_bot
    DYNAMIC_ACCOUNTS.write({"en": ["oldshill"], "fr": ["oldtrader"]})
    DISCOVERED_ACCOUNTS.write([{"handle": "oldshill"}])
    account_curator.TRACKED.write({"tracked": [{"handle": "oldshill"}]})
    assert "oldshill" not in engage_bot._build_pool()
    assert "oldtrader" not in engage_bot._build_pool()


def test_corrupt_guarded_candidates_stop_discovery_without_replacing_them():
    from pathlib import Path
    path = Path(evidence.POOL.path)
    path.write_text("broken JSON")
    with pytest.raises(StateUnreadable):
        evidence.approved_authors()
    assert path.read_text() == "broken JSON"
