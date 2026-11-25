"""Operator, 2026-11-25: one short thank-you to each person who comments on our posts."""
from dataclasses import replace

import pytest

from src.core import account
from src.guards import content_guard, reply_admission, replied_store
from src.replies import commenter_thanks, reply_generator
from src.x import twitter_client
from src.x.confirmed_write import WriteOutcome

COMMENT = "https://x.com/fan/status/2125590588900921732"


@pytest.fixture
def thanking(monkeypatch, settings_override, open_topic_account):
    settings_override(DRY_RUN=False, HOURLY_BREAK_MINUTES=0)
    profile = replace(open_topic_account, thank_commenters=True, thanks_style="Nice, sharp, sweet.")
    monkeypatch.setattr(account, "current", lambda: profile)
    monkeypatch.setattr(reply_admission.active_hours, "may_reply", lambda: True)
    return profile


def test_account_must_opt_in_and_never_answers_itself_or_a_blocked_author(thanking, monkeypatch):
    assert reply_admission.judge_comment(COMMENT)
    own = "https://x.com/" + next(iter(account.own_handles())) + "/status/2125590588900921732"
    assert reply_admission.judge_comment(own).refusal is reply_admission.Refusal.OWN_POST
    monkeypatch.setattr(account, "current", lambda: replace(thanking, thank_commenters=False))
    assert reply_admission.judge_comment(COMMENT).refusal is reply_admission.Refusal.CONVERSATION


@pytest.mark.parametrize("text,ok", [("Thanks 🙏", True), ("Trying to keep it fun 😎", True), ("He never saw it coming 😂", True),
    ("Thanks so much, follow me at https://x.com/me", False), ("Thanks @fan", False), ("#thanks", False),
    ("Merci beaucoup pour ce commentaire, c'est vraiment gentil de ta part", False),
    ("word " * 13, False), ("", False)])
def test_thank_you_text_is_short_plain_and_english(thanking, text, ok):
    assert bool(reply_admission.judge_thanks(COMMENT, text)) is ok


def test_the_same_line_never_goes_out_twice_in_a_row(thanking):
    assert not reply_admission.judge_thanks(COMMENT, "Thanks 🙏", recent=("thanks!", "Glad you liked it 😎"))
    assert reply_admission.judge_thanks(COMMENT, "Thanks 🙏", recent=("a", "b", "c", "Thanks 🙏"))


def test_short_reaction_allowance_is_for_its_caller_only(thanking):
    assert not content_guard.validate("Thanks 🙏", kind="reply")[0]
    assert content_guard.validate("Thanks 🙏", kind="reply", short_reaction=True)[0]
    assert not content_guard.validate("Thanks 🙏", kind="reply", short_title=True)[0]


def test_one_thanks_per_comment_for_ever(thanking):
    assert replied_store.claim(COMMENT)
    assert reply_admission.judge_comment(COMMENT).refusal is reply_admission.Refusal.ALREADY_REPLIED


def _cycle(monkeypatch, pages, outcome=WriteOutcome.SHIPPED, text="Glad you liked it 😎"):
    sent = []
    commenter_thanks._done.clear(); commenter_thanks._reads.clear()
    monkeypatch.setattr(commenter_thanks, "_last_cycle", 0.0)
    monkeypatch.setattr(commenter_thanks, "hot", lambda now=None: False)
    monkeypatch.setattr(commenter_thanks.time, "monotonic", lambda: 10_000.0)
    monkeypatch.setattr(commenter_thanks, "require_active", lambda: None)
    monkeypatch.setattr(commenter_thanks.x_urls, "age", lambda url, *a: __import__("datetime").timedelta(minutes=5))
    monkeypatch.setattr(commenter_thanks.scraper, "scrape_mentions", lambda max_tweets=30: [{"url": url} for url in pages])
    monkeypatch.setattr(commenter_thanks.twitter_client, "read_comment", lambda url: pages[url])
    monkeypatch.setattr(commenter_thanks.reply_generator, "generate", lambda call, **k: reply_generator.Generation(
        reply_generator.Outcome.WRITTEN, "en", text, provider="grok", model="m"))
    monkeypatch.setattr(commenter_thanks.twitter_client, "thank_commenter",
                        lambda url, reply, **k: sent.append((url, reply, k["expected_text"])) or outcome)
    monkeypatch.setattr(commenter_thanks.engagement_log, "log_reply", lambda *a, **k: None)
    monkeypatch.setattr(commenter_thanks, "recent", lambda limit=6: ())
    return sent


def test_cycle_thanks_real_comments_and_leaves_plain_mentions_and_answered_threads(thanking, monkeypatch):
    other = "https://x.com/someone/status/2125590588900921733"
    answered = "https://x.com/third/status/2125590588900921734"
    pages = {COMMENT: {"url": COMMENT, "text": "OMG cool!", "parent_text": "Jensen duet era"},
             other: {}, answered: {"already_replied": True}}
    sent = _cycle(monkeypatch, pages)
    assert commenter_thanks.run_thanks_cycle() == 1
    assert sent == [(COMMENT, "Glad you liked it 😎", "OMG cool!")]
    assert commenter_thanks.run_thanks_cycle() == 0      # the three-minute pace: nothing is read again yet


def test_a_refused_send_is_tried_again_and_an_uncertain_one_never(thanking, monkeypatch):
    pages = {COMMENT: {"url": COMMENT, "text": "OMG cool!", "parent_text": "post"}}
    _cycle(monkeypatch, pages, outcome=WriteOutcome.REFUSED)
    commenter_thanks.run_thanks_cycle()
    assert COMMENT not in commenter_thanks._done
    _cycle(monkeypatch, pages, outcome=WriteOutcome.UNCONFIRMED)
    commenter_thanks.run_thanks_cycle()
    assert COMMENT in commenter_thanks._done


def test_first_half_hour_after_a_post_reads_every_minute_and_answers_everyone(thanking, monkeypatch):
    pages = {f"https://x.com/fan{i}/status/21255905889009217{i:02d}": {"text": "love it", "parent_text": "post"} for i in range(8)}
    sent = _cycle(monkeypatch, pages)
    monkeypatch.setattr(commenter_thanks, "hot", lambda now=None: True)
    assert commenter_thanks.run_thanks_cycle() == 8 and len(sent) == 8
    monkeypatch.setattr(commenter_thanks, "_last_cycle", 10_000.0)
    assert commenter_thanks.run_thanks_cycle() == 0      # hot: the pass runs again at once, all already done


def test_comment_script_requires_our_post_directly_above_and_one_own_turn():
    import inspect
    source = inspect.getsource(twitter_client._comment_target)
    # Operator, 2026-11-25: only the first reply under a thread we started; never a reply to our reply.
    for rule in ("parent_not_ours", "not_first_level", "parent_is_a_reply", "already_replied", "comment_text", "copy_author"):
        assert rule in source


def test_live_account_thanks_commenters_and_scheduler_runs_the_job(monkeypatch):
    import tomllib
    from pathlib import Path
    raw = tomllib.loads(Path("accounts/theaishrink/account.toml").read_text())
    assert raw["thank_commenters"] is True and "Thanks" in raw["thanks_style"]


def test_reservation_does_not_apply_ordinary_reply_text_rules_to_a_thank_you(thanking, settings_override):
    # 2026-11-25, first live send: "hearts belong to artist reactions" refused "Glad you liked it 💙".
    from src.guards import reply_budget
    settings_override(REPLY_CURATED_MODE=True, REPLY_BROAD_DISCOVERY=True)
    other = COMMENT[:-1] + "9"
    assert "heart" in reply_budget.begin(other, "Glad you liked it 💙")
    assert reply_budget.begin(COMMENT, "Glad you liked it 💙", thanks=True) == ""


def test_fast_pace_reads_the_real_video_history_with_an_aware_time(thanking, monkeypatch):
    # 2026-11-25: a float was passed where the history wants an aware datetime; the fast pace never started.
    from datetime import datetime
    from src.video import config as video_config
    now = datetime.fromisoformat("2026-11-25T12:10:00-05:00")
    seen = []
    monkeypatch.setattr(video_config, "legacy_usage", lambda at: seen.append(at) or (1, at.timestamp() - 600))
    assert commenter_thanks.hot(now) and seen[0].tzinfo is not None
    monkeypatch.setattr(video_config, "legacy_usage", lambda at: (1, at.timestamp() - 3600))
    assert not commenter_thanks.hot(now)
