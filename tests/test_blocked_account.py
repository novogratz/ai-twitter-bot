"""A Blocked account is refused at the follow chokepoint, whoever calls it
(issue #188), with the one match Reply admission and likes use.

Each follow job and the seeding script run for real on a handle holding a
blocklist token; `follow_account` is wrapped, never replaced, so the test
sees the chokepoint's own outcome.
"""
import dataclasses
import importlib.util
import json
import time
from pathlib import Path

import pytest

from src.core import account, config
from src.guards import follow_policy, reply_admission
from src.x import safari
from src.x import twitter_client as tc

HANDLE = "La_Pique_Off"
SEED_SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "seed_fr_influencers.py"


def _followback(monkeypatch, follow, tmp_path):
    """The scrape drops a Blocked account; with that filter off, the
    chokepoint must refuse it all the same."""
    from src.account import followback_bot as fb
    monkeypatch.setattr(fb, "is_blocked_account", lambda handle: False)
    page = json.dumps({"path": f"/{config.BOT_HANDLE}/followers", "handles": [HANDLE]})
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: page)
    monkeypatch.setattr(fb, "_scroll_page", lambda: None)
    monkeypatch.setattr(fb, "close_front_tab", lambda: None)
    monkeypatch.setattr(fb, "follow_account", follow)
    fb.run_followback_cycle()


def _follow_engagers(monkeypatch, follow, tmp_path):
    from src.account import follow_engagers_bot as fe
    monkeypatch.setattr(follow_policy, "engagers", lambda: [HANDLE])
    monkeypatch.setattr(tc, "follow_account", follow)
    fe.run_follow_engagers_cycle()


def _engage(monkeypatch, follow, tmp_path):
    """The pool drops a Blocked account; the chokepoint must refuse it all
    the same when one gets through."""
    from src.account import engage_bot as eb
    from src.core import evolution_store
    monkeypatch.setattr(eb, "_build_pool", lambda: [HANDLE])
    monkeypatch.setattr(evolution_store, "filter_and_weight", lambda pool: pool)
    monkeypatch.setattr(eb, "_profile_visit_allowed", lambda *_: False)
    monkeypatch.setattr(eb, "follow_account", follow)
    eb.run_engage_cycle()


def _seed_script(monkeypatch, follow, tmp_path):
    spec = importlib.util.spec_from_file_location("seed_fr_influencers", SEED_SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "SEED_HANDLES", [HANDLE])
    monkeypatch.setattr(script, "DYNAMIC_FILE", str(tmp_path / "dynamic_accounts.json"))
    monkeypatch.setattr(script, "follow_account", follow)
    script.main()


@pytest.mark.parametrize("dry_run", ["0", "1"])
@pytest.mark.parametrize("caller", [_followback, _follow_engagers, _engage, _seed_script])
def test_every_follow_caller_meets_the_blocked_account_refusal(monkeypatch, tmp_path, memory_ledger,
                                                               settings_override, caller, dry_run):
    monkeypatch.setenv("DRY_RUN", dry_run)
    settings_override(ENABLE_FOLLOW_ENGAGERS=True)
    monkeypatch.setattr(config, "BLOCKLIST", {"la pique"})
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    # A Seed account, so that engage and the seeding script ask to follow it.
    (tmp_path / "whitelist.json").write_text(json.dumps({"tiers": {"tier1": [HANDLE]}}))
    opened = []
    monkeypatch.setattr(safari, "open_url", opened.append)
    asked = []
    real_follow = tc.follow_account

    def follow(handle):
        outcome = real_follow(handle)
        asked.append((handle, outcome))
        return outcome

    caller(monkeypatch, follow, tmp_path)

    assert asked == [(HANDLE, tc.FollowOutcome.BLOCKED)]
    assert memory_ledger.rows == []
    assert f"https://x.com/{HANDLE}" not in opened
    assert HANDLE not in follow_policy.followed()


def test_reply_admission_likes_and_follows_share_one_blocklist_match(monkeypatch, memory_ledger):
    """#188: the follow policy and the job filters copied no match of their
    own: whatever `is_blocked_account` says, every one of them says."""
    from src.account import account_curator, engage_bot, followback_bot
    from src.replies import feed_sweeper_bot, notify_bot

    for module in (account_curator, engage_bot, feed_sweeper_bot, followback_bot, notify_bot):
        assert module.is_blocked_account is reply_admission.is_blocked_account, module.__name__
    monkeypatch.setattr(config, "BLOCKLIST", set())
    monkeypatch.setattr(reply_admission, "is_blocked_account", lambda handle: handle.lower() == "anyone")
    monkeypatch.setattr(tc, "_page_posts", lambda *a: pytest.fail("read the page"))

    assert reply_admission.judge_parent("https://x.com/anyone/status/2063500000000000201").refusal \
        is reply_admission.Refusal.BLOCKED_ACCOUNT
    assert tc.like_tweet("https://x.com/anyone/status/2063500000000000202") is tc.LikeOutcome.BLOCKED
    assert follow_policy.judge("anyone").refusal is follow_policy.Refusal.BLOCKED_ACCOUNT


# --- Blocked accounts an Account adds (#204) ----------------------------------------


def _account_blocking(monkeypatch, *tokens):
    """The loaded Account, its network.blocked_accounts set to `tokens`."""
    loaded = account.current()
    network = dataclasses.replace(loaded.network, blocked_accounts=tokens)
    monkeypatch.setattr(account, "current", lambda: dataclasses.replace(loaded, network=network))


def test_a_blocked_account_the_account_adds_is_refused_a_follow_and_a_reply(monkeypatch, memory_ledger):
    monkeypatch.setenv("DRY_RUN", "0")
    opened = []
    monkeypatch.setattr(safari, "open_url", opened.append)
    target = "https://x.com/Some_Troll_Bot/status/2063500000000000201"
    assert not reply_admission.is_blocked_account("Some_Troll_Bot")
    assert reply_admission.judge_parent(target).refusal is not reply_admission.Refusal.BLOCKED_ACCOUNT

    _account_blocking(monkeypatch, "some troll")

    assert tc.follow_account("Some_Troll_Bot") is tc.FollowOutcome.BLOCKED
    assert reply_admission.judge_parent(target).refusal is reply_admission.Refusal.BLOCKED_ACCOUNT
    assert memory_ledger.rows == [] and opened == []
    # The engine's own tokens hold beside the Account's.
    assert all(reply_admission.is_blocked_account(token) for token in config.BLOCKLIST)


def test_an_account_cannot_unblock_one_of_the_engine_blocked_accounts(monkeypatch, memory_ledger):
    """No key removes a token from config.BLOCKLIST (an unknown key stops the
    start, tests/core/test_account.py): an Account with no Blocked account
    of its own still meets every one of the engine's."""
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setattr(safari, "open_url", lambda *_: pytest.fail("opened a Blocked account's page"))
    _account_blocking(monkeypatch)
    assert "pgm_pm" in config.BLOCKLIST
    for token in config.BLOCKLIST:
        assert reply_admission.is_blocked_account(token), token
    assert tc.follow_account("pgm_pm") is tc.FollowOutcome.BLOCKED
    assert reply_admission.judge_parent("https://x.com/pgm_pm/status/2063500000000000201").refusal \
        is reply_admission.Refusal.BLOCKED_ACCOUNT
    assert memory_ledger.rows == []
