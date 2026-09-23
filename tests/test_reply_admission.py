"""Reply admission (issue #100), tested through its interface: no Safari,
no model. conftest points the Replied store and the ledger at tmp_path and
fixes the clock at noon Toronto."""
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.guards import (
    action_guard,
    active_hours,
    content_guard,
    replied_store,
)
from src.core import config, humanizer
from src.x import x_urls
from src.guards.reply_admission import Refusal, judge_parent, judge_reply
from src.core.state_errors import StateUnreadable

TEXT = "Batching is where inference margins are won or lost."


def url(author, n=2063500000000000200):
    return f"https://x.com/{author}/status/{n}"


# --- x_urls -----------------------------------------------------------------

def test_author_comes_from_the_url_handle():
    assert x_urls.author("https://x.com/SomeOne/status/1?s=20") == "someone"
    assert x_urls.author("https://x.com/i/web/status/1") == ""
    assert x_urls.author("https://x.com/someone") == ""
    assert x_urls.author("") == ""


def test_status_id_and_snowflake_age():
    posted = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    sid = (int(posted.timestamp() * 1000) - x_urls._TWITTER_EPOCH_MS) << 22
    link = url("someone", sid)
    assert x_urls.status_id(link) == str(sid)
    assert x_urls.age(link, now=posted + timedelta(minutes=5)) == timedelta(minutes=5)
    assert x_urls.age("https://x.com/someone") is None


def test_reply_like_tweet_is_a_nested_reply_or_someone_elses_post():
    assert x_urls.is_reply_like_tweet({"url": url("someone"), "text": "@a hi"})
    assert x_urls.is_reply_like_tweet({"url": url("someone"), "text": "hi", "is_reply": True})
    assert not x_urls.is_reply_like_tweet({"url": url("someone"), "text": "hi"})
    own = {"url": url("SomeOne"), "text": "hi", "author": "someone"}
    assert not x_urls.is_reply_like_tweet(own, expected_author="@someone")
    assert x_urls.is_reply_like_tweet(own, expected_author="other")
    assert x_urls.is_reply_like_tweet({**own, "author": "Some One"}, expected_author="someone")
    assert not x_urls.is_reply_like_tweet({**own, "author": "unknown"}, expected_author="someone")


# --- rules on the post ------------------------------------------------------

@pytest.mark.parametrize("handle,token", [
    ("pgm_pm", "pgm_pm"),
    ("PGM_PM", "pgm_pm"),
    ("la_pique_off", "la pique"),
    ("LaPique", "la-pique"),
])
def test_blocked_account_matches_normalised_tokens(monkeypatch, handle, token):
    monkeypatch.setattr(config, "BLOCKLIST", {token})
    verdict = judge_parent(url(handle))
    assert verdict.refusal is Refusal.BLOCKED_ACCOUNT
    assert verdict.refusal.definitive


def test_unrelated_handle_is_admitted(monkeypatch):
    monkeypatch.setattr(config, "BLOCKLIST", {"la pique", "pgm_pm"})
    verdict = judge_parent(url("karpathy"))
    assert verdict and verdict.author == "karpathy"


def test_own_post_and_author_less_url_are_definitive():
    own = judge_parent(url(config.BOT_HANDLE.upper()))
    anonymous = judge_parent("https://x.com/i/web/status/2063500000000000201")
    assert own.refusal is Refusal.OWN_POST and own.refusal.definitive
    assert anonymous.refusal is Refusal.NO_AUTHOR and anonymous.refusal.definitive


def test_already_replied_on_status_id_whatever_the_url_author():
    replied_store.save_replied([url("someone")])
    verdict = judge_parent(url("misattributed"))
    assert verdict.refusal is Refusal.ALREADY_REPLIED and verdict.refusal.definitive


def test_definitive_rules_win_over_overnight(monkeypatch):
    monkeypatch.setattr(active_hours, "now_local",
                        lambda: datetime(2026, 9, 23, 23, 0, tzinfo=ZoneInfo(config.BOT_TIMEZONE)))
    monkeypatch.setattr(config, "BLOCKLIST", {"pgm_pm"})
    assert judge_parent(url("pgm_pm")).refusal is Refusal.BLOCKED_ACCOUNT
    overnight = judge_parent(url("someone"))
    assert overnight.refusal is Refusal.OVERNIGHT and not overnight.refusal.definitive


def test_stop_request_refuses_as_overnight(monkeypatch):
    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(active_hours, "_STOP", stop)
    assert judge_parent(url("someone")).refusal is Refusal.OVERNIGHT


def test_debate_turn_cap_is_temporary_and_only_for_turns(monkeypatch):
    monkeypatch.setenv("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "1")
    action_guard.record(action_guard.DEBATE_TURN, target="challenger")
    capped = judge_parent(url("challenger"), debate_turn=True)
    assert capped.refusal is Refusal.DEBATE_TURN_CAP and not capped.refusal.definitive
    assert judge_parent(url("challenger")), "plain Replies stay uncapped"


def test_unreadable_store_raises_instead_of_admitting():
    with open(config.REPLIED_FILE, "w") as f:
        f.write("[")
    with pytest.raises(StateUnreadable):
        judge_parent(url("someone"))


# --- spacing and text -------------------------------------------------------

def test_spacing_waits_for_the_reply_not_the_parent(monkeypatch):
    """A Reply that just shipped must not refuse every candidate before
    generation: only judge_reply applies the spacing."""
    monkeypatch.setattr(action_guard, "can_post", lambda action: (False, "too soon"))
    assert judge_parent(url("someone"))
    verdict = judge_reply(url("someone"), TEXT)
    assert verdict.refusal is Refusal.SPACING and not verdict.refusal.definitive


def test_admitted_text_is_the_validated_text(monkeypatch):
    monkeypatch.setenv("HUMAN_TYPO_HANDLES", "typofriend")
    monkeypatch.setattr(humanizer, "casualize", lambda text: text)
    monkeypatch.setattr(humanizer, "inject_human_typo", lambda text: text + " (typo)")
    validated = []
    real_validate = content_guard.validate
    monkeypatch.setattr(content_guard, "validate",
                        lambda text, kind="post": validated.append(text) or real_validate(text, kind=kind))

    verdict = judge_reply(url("typofriend"), "Targets are easy — conviction is the hard part of the trade.")
    assert verdict
    assert verdict.text == validated[-1]
    assert verdict.text.endswith("(typo)") and "—" not in verdict.text


def test_over_length_draft_is_trimmed_on_a_sentence(monkeypatch):
    monkeypatch.setattr(humanizer, "casualize", lambda text: text)
    draft = "Batching decides the margin. " * 12
    verdict = judge_reply(url("someone"), draft)
    assert verdict and len(verdict.text) <= 278 and verdict.text.endswith(".")


def test_refused_text_leaves_the_post_replayable(monkeypatch):
    monkeypatch.setenv("FR_FORCED_REPLY_HANDLES", "graphseo")
    monkeypatch.setattr(humanizer, "casualize", lambda text: text)
    english = judge_reply(url("Graphseo"), "The market just told you what your conviction is worth this week.")
    assert english.refusal is Refusal.TEXT and not english.refusal.definitive
    assert judge_parent(url("Graphseo")), "nothing was written: the post stays fresh"
    assert judge_reply(url("Graphseo"), "Le marché vient de te dire ce que vaut ta conviction cette semaine.")


def test_judges_write_nothing(monkeypatch):
    monkeypatch.setattr(humanizer, "casualize", lambda text: text)
    assert judge_reply(url("someone"), TEXT, debate_turn=True)
    assert url("someone") not in replied_store.load_replied()
    assert action_guard.debate_turns_today("someone") == 0
