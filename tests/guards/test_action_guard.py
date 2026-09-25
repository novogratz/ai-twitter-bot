"""src/guards/action_guard: the daily budget, follow policy, write spacing.

The policy asks an in-memory ledger (the `memory_ledger` fixture); the file
adapter has its own tests in test_ledger.py."""
import json
from datetime import datetime, timedelta

import pytest

from src.core import config
from src.core.state_store import StateFile
from src.guards import action_guard as ag
from src.guards.ledger import MemoryLedger
from tests.helpers import TORONTO, stop_requested, clock


# --- daily budget and caps ----------------------------------------------------


def test_toronto_day_budget_ignores_dry_runs_and_uses_all_profile_actions(monkeypatch):
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    rows = [{"action": ag.POST, "ts": "2026-09-20T03:59:00+00:00"},
            {"action": ag.POST, "ts": "2026-09-20T04:00:00+00:00", "dry_run": True}]
    rows += [{"action": action, "ts": "2026-09-20T06:00:00"}
             for action in [ag.POST] * 5 + [ag.QUOTE, ag.RETWEET]]
    ledger = MemoryLedger(rows)
    monkeypatch.setattr(ag, "LEDGER", ledger)
    assert ledger.count(ag.POST, now.date()) == 5
    assert ag.profile_count_today() == 7
    assert ag.can_post(ag.POST)[0]
    assert ledger.last_write(ag.POST) == now - timedelta(hours=6)
    ag.record(ag.POST)
    assert ag.profile_count_today() == 8
    assert not ag.can_post(ag.POST, urgent=True, high_value=True)[0]
    assert ag.can_post(ag.REPLY)[0]


def test_replies_uncapped_but_still_paced(monkeypatch, memory_ledger):
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    for n in range(500):
        memory_ledger.append(ag.REPLY, f"https://x.com/a/status/{n}", False,
                             now - timedelta(hours=6, seconds=n))
    assert ag.can_post(ag.REPLY)[0]
    ag.record(ag.REPLY, "https://x.com/a/status/500")
    assert not ag.can_post(ag.REPLY, urgent=True)[0]


def test_mega_viral_quote_cannot_bypass_editorial_policy(memory_ledger):
    for urgent in (False, True):
        assert not ag.can_post(ag.QUOTE, high_value=True, urgent=urgent)[0]


def test_urgent_quote_obeys_editorial_policy(memory_ledger):
    assert not ag.can_post(ag.QUOTE, urgent=True)[0]


def test_can_post_refuses_after_stop(monkeypatch):
    from src.guards import action_guard

    assert action_guard.can_post(action_guard.REPLY)[0] is True
    stop_requested(monkeypatch)

    ok, why = action_guard.can_post(action_guard.REPLY)
    assert not ok and "stop" in why


# --- 2026-06-07 agent spec: follow policy (Part 1 hard constraints) ---------


@pytest.fixture()
def follow_env(monkeypatch, tmp_path, memory_ledger):
    """Isolated ledger + whitelist + counts for action_guard follow tests."""
    from src.guards import action_guard as ag
    from src.core import config

    (tmp_path / "whitelist.json").write_text(json.dumps({"tiers": {
        "tier1": ["TheBTCTherapist"],
        "tier2": ["morganhousel"],
        "tier3": ["karpathy"],
        "tier4": ["saylor", "balajis"],
    }}))
    # Spec pacing defaults, but zeroed spacing unless a test re-enables it.
    monkeypatch.setattr(config, "FOLLOW_WHITELIST_ONLY", True)
    monkeypatch.setattr(config, "MAX_FOLLOWS_PER_DAY", 20)
    monkeypatch.setattr(config, "MIN_SECONDS_BETWEEN_FOLLOWS", 0)
    monkeypatch.setattr(config, "FOLLOW_SPACING_JITTER_SECONDS", 0)
    monkeypatch.setattr(config, "FOLLOW_ENFORCE_RATIO", False)
    monkeypatch.setattr(config, "FOLLOW_TOTAL_CAP", 300)
    monkeypatch.setattr(config, "FOLLOW_LOW_PHASE_CEILING", 150)
    monkeypatch.setattr(config, "FOLLOW_LOW_PHASE_FOLLOWERS", 300)
    # These tests pin the LEGACY spec policy; growth mode (2026-06-11) has
    # its own dedicated test and must not leak in from the live .env.
    monkeypatch.setattr(config, "FOLLOW_GROWTH_MODE", False)
    return ag


def _counts(monkeypatch, tmp_path, followers, following):
    """The account's counts as the follower tracker and the following
    counter leave them on disk."""
    monkeypatch.delenv("FOLLOWING_COUNT_OVERRIDE", raising=False)
    (tmp_path / "follower_history.json").write_text(json.dumps([{"count": followers}]))
    (tmp_path / "following_count.json").write_text(json.dumps({"count": following}))


def test_whitelist_loads_tier4(follow_env):
    ag = follow_env
    wl = ag.load_whitelist()
    assert "saylor" in wl["tier4"]
    assert "saylor" in wl["all"]
    assert ag.is_whitelisted("balajis")


def test_follow_blocked_at_low_phase_ceiling(follow_env, monkeypatch, tmp_path):
    """While followers are low (<300), total following must stay under ~150."""
    ag = follow_env
    _counts(monkeypatch, tmp_path, 100, 150)
    ok, why = ag.can_follow("karpathy")
    assert not ok and "ceiling" in why


def test_follow_allowed_under_low_phase_ceiling(follow_env, monkeypatch, tmp_path):
    ag = follow_env
    _counts(monkeypatch, tmp_path, 100, 149)
    ok, why = ag.can_follow("karpathy")
    assert ok, why


def test_follow_never_exceeds_hard_300_cap(follow_env, monkeypatch, tmp_path):
    """Even with a big follower count, total following is hard-capped at 300."""
    ag = follow_env
    _counts(monkeypatch, tmp_path, 10000, 300)
    ok, why = ag.can_follow("saylor")
    assert not ok and "ceiling" in why
    _counts(monkeypatch, tmp_path, 10000, 299)
    ok, why = ag.can_follow("saylor")
    assert ok, why


def test_follow_keeps_following_below_followers_mid_phase(follow_env, monkeypatch, tmp_path):
    """Once followers exceed 300, following must stay <= followers."""
    ag = follow_env
    _counts(monkeypatch, tmp_path, 220, 200)
    # followers=220 is still < FOLLOW_LOW_PHASE_FOLLOWERS → 150 ceiling rules
    ok, why = ag.can_follow("morganhousel")
    assert not ok and "ceiling" in why
    _counts(monkeypatch, tmp_path, 320, 280)
    ok, why = ag.can_follow("morganhousel")
    assert ok, why  # 280+1 <= min(300, 320)


@pytest.mark.parametrize("name", ["followed_accounts.json", "following_count.json"])
def test_an_unreadable_following_count_refuses_every_follow(follow_env, monkeypatch, tmp_path, name):
    """#171: with the following count unknown, can_follow skipped the
    ceiling. The count comes from following_count.json, else from the
    followed list: either one unreadable now refuses the follow, and the
    file waits for the Operator."""
    ag = follow_env
    monkeypatch.delenv("FOLLOWING_COUNT_OVERRIDE", raising=False)
    (tmp_path / "follower_history.json").write_text(json.dumps([{"count": 100}]))
    path = tmp_path / name
    path.write_text('{"count": 1')

    ok, why = ag.can_follow("karpathy")

    assert not ok and "following ceiling unreadable" in why and name in why
    assert path.read_text() == '{"count": 1'


def test_an_unreadable_follower_history_leaves_the_lowest_ceiling(follow_env, monkeypatch, tmp_path):
    """follower_history.json is disposable: unreadable, it reads as no
    sample, and the ceiling falls to its low-phase value."""
    ag = follow_env
    _counts(monkeypatch, tmp_path, 10000, 150)
    (tmp_path / "follower_history.json").write_text('[{"count": 1')
    ok, why = ag.can_follow("karpathy")
    assert not ok and "(150 >= 150)" in why


@pytest.mark.parametrize("history", ['[{"count": 1', "[]"])
def test_the_ratio_brake_refuses_while_the_follower_count_is_unknown(follow_env, monkeypatch,
                                                                    tmp_path, history):
    """#171: the ratio brake skipped itself when follower_history.json
    held no sample, so losing the disposable file admitted follows the
    brake would refuse."""
    ag = follow_env
    monkeypatch.setattr(config, "FOLLOW_ENFORCE_RATIO", True)
    _counts(monkeypatch, tmp_path, 100, 10)
    assert ag.can_follow("karpathy") == (True, "")

    (tmp_path / "follower_history.json").write_text(history)

    assert ag.can_follow("karpathy") == (
        False, "follower count unknown: ratio brake cannot be checked")


def test_a_follow_decision_reads_each_count_file_once(follow_env, monkeypatch, tmp_path):
    ag = follow_env
    monkeypatch.setattr(config, "FOLLOW_ENFORCE_RATIO", True)
    _counts(monkeypatch, tmp_path, 100, 10)
    reads = []
    real_read = StateFile.read
    monkeypatch.setattr(StateFile, "read", lambda self: reads.append(self.name) or real_read(self))

    assert ag.can_follow("karpathy") == (True, "")

    assert sorted(reads) == ["follower_history.json", "following_count.json", "whitelist.json"]


@pytest.mark.parametrize("whitelist_only", [True, False])
def test_an_unreadable_whitelist_refuses_every_follow(follow_env, monkeypatch, tmp_path,
                                                      whitelist_only):
    """#171: an unreadable whitelist.json read as empty. Guarded now, it
    refuses the follow (the follow_account quality gate reads it too), and
    the file waits for the Operator."""
    ag = follow_env
    monkeypatch.setattr(config, "FOLLOW_WHITELIST_ONLY", whitelist_only)
    _counts(monkeypatch, tmp_path, 100, 10)
    path = tmp_path / "whitelist.json"
    path.write_text('{"tiers": {"tier1": ["karp')

    ok, why = ag.can_follow("karpathy", reciprocal=True)
    assert not ok and "whitelist unreadable" in why
    assert path.read_text() == '{"tiers": {"tier1": ["karp'


def test_adjust_following_keeps_the_baseline_and_never_overwrites_an_unreadable_count(
        monkeypatch, tmp_path):
    monkeypatch.setenv("DRY_RUN", "0")
    path = tmp_path / "following_count.json"
    path.write_text(json.dumps({"count": 10, "baseline": 4200}))
    ag.adjust_following(+1)
    doc = json.loads(path.read_text())
    assert (doc["count"], doc["baseline"]) == (11, 4200) and "updated" in doc

    path.write_text('{"count": 1')
    ag.adjust_following(+1)
    assert path.read_text() == '{"count": 1'


def test_follow_spacing_blocks_burst(follow_env, monkeypatch, tmp_path):
    """Never burst-follow: a follow within the 10-min gap is refused."""
    from src.core import config
    ag = follow_env
    monkeypatch.setattr(config, "MIN_SECONDS_BETWEEN_FOLLOWS", 600)
    _counts(monkeypatch, tmp_path, 100, 10)
    ag.record(ag.FOLLOW, target="TheBTCTherapist")
    ok, why = ag.can_follow("morganhousel")
    assert not ok and "too soon" in why


def test_follow_rejects_non_whitelisted(follow_env, monkeypatch, tmp_path):
    ag = follow_env
    _counts(monkeypatch, tmp_path, 100, 10)
    ok, why = ag.can_follow("randomspamaccount")
    assert not ok and "whitelist" in why


def _noon(monkeypatch):
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    return now


def test_anti_churn_counts_any_follow_or_unfollow_within_the_cooldown(follow_env, monkeypatch,
                                                                     memory_ledger, tmp_path):
    ag = follow_env
    now = _noon(monkeypatch)
    _counts(monkeypatch, tmp_path, 100, 10)
    cooldown = timedelta(days=config.CHURN_COOLDOWN_DAYS)
    memory_ledger.append(ag.FOLLOW, "karpathy", True, now - cooldown + timedelta(minutes=1))
    memory_ledger.append(ag.UNFOLLOW, "morganhousel", False, now - cooldown)
    memory_ledger.append(ag.LIKE, "saylor", False, now)

    ok, why = ag.can_follow("KarPathy")
    assert not ok and "anti-churn" in why, "a dry-run follow still touches"
    assert ag.can_follow("morganhousel") == (True, ""), "the cooldown ends on its last second"
    assert ag.can_follow("saylor") == (True, ""), "a like is no touch"


def test_follow_cap_counts_todays_shipped_rows(follow_env, monkeypatch, memory_ledger, tmp_path):
    ag = follow_env
    now = _noon(monkeypatch)
    _counts(monkeypatch, tmp_path, 100, 10)
    monkeypatch.setattr(config, "FOLLOW_WHITELIST_ONLY", False)
    monkeypatch.setattr(config, "MAX_FOLLOWS_PER_DAY", 2)
    memory_ledger.append(ag.FOLLOW, "yesterday", False, now - timedelta(days=1))
    memory_ledger.append(ag.FOLLOW, "dry", True, now)
    memory_ledger.append(ag.FOLLOW, "today", False, now - timedelta(hours=1))
    assert ag.can_follow("stranger") == (True, "")

    ag.record(ag.FOLLOW, "another")

    assert ag.can_follow("stranger") == (False, "daily follow cap reached (2)")


def test_debate_turn_cap_counts_todays_shipped_turns_per_author(monkeypatch, memory_ledger):
    now = _noon(monkeypatch)
    monkeypatch.setenv("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "2")
    memory_ledger.append(ag.DEBATE_TURN, "challenger", False, now - timedelta(days=1))
    memory_ledger.append(ag.DEBATE_TURN, "challenger", True, now)
    memory_ledger.append(ag.DEBATE_TURN, "other", False, now)
    ag.record(ag.DEBATE_TURN, "@Challenger")
    assert ag.can_debate_turn("challenger") == (True, "")

    ag.record(ag.DEBATE_TURN, "challenger")

    assert ag.can_debate_turn("@Challenger") == (False, "debate turn cap reached for @@Challenger (2/day)")
    assert ag.can_debate_turn("other") == (True, "")
    assert ag.can_debate_turn(" @ ") == (False, "debate turn without an author handle")
    assert ag.debate_turn_authors() == ["challenger", "other"]


def test_follow_growth_mode_unties_ceiling_from_followers(follow_env, monkeypatch, tmp_path):
    """2026-06-11 operator: "go back on following people and following back".
    Growth mode must untie the following ceiling from the followers count
    (following>followers mid-purge would block every follow), while
    FOLLOW_TOTAL_CAP stays the hard stop and legacy mode keeps the old
    followers-tied invariant."""
    ag = follow_env
    monkeypatch.setattr(config, "FOLLOW_TOTAL_CAP", 3000)

    monkeypatch.setattr(config, "FOLLOW_GROWTH_MODE", True)
    _counts(monkeypatch, tmp_path, 1423, 2999)  # followers, following
    assert ag.can_follow("karpathy") == (True, ""), \
        "growth mode: ceiling is FOLLOW_TOTAL_CAP, not the followers count"
    _counts(monkeypatch, tmp_path, 1423, 3000)
    ok, why = ag.can_follow("karpathy")
    assert not ok and "(3000 >= 3000)" in why

    monkeypatch.setattr(config, "FOLLOW_GROWTH_MODE", False)
    _counts(monkeypatch, tmp_path, 1423, 1422)
    assert ag.can_follow("karpathy") == (True, "")
    _counts(monkeypatch, tmp_path, 1423, 1423)
    ok, why = ag.can_follow("karpathy")
    assert not ok and "(1423 >= 1423)" in why, "legacy mode keeps following <= followers"


def test_reciprocal_followback_bypasses_whitelist(monkeypatch, memory_ledger):
    """Self-improve #3 (2026-06-24): followback was dead — whitelist-only
    blocked following people who engage with us. reciprocal=True bypasses ONLY
    the whitelist gate (when FOLLOWBACK_BYPASS_WHITELIST), never the other
    gates. Pin: a non-whitelisted handle is whitelist-blocked normally but
    NOT for a reciprocal follow-back."""
    from src.guards import action_guard
    from src.core import config
    monkeypatch.setattr(config, "FOLLOW_WHITELIST_ONLY", True)
    monkeypatch.setattr(config, "FOLLOWBACK_BYPASS_WHITELIST", True)
    monkeypatch.setattr(action_guard, "is_whitelisted", lambda h, **k: False)
    _, why_norm = action_guard.can_follow("randomstranger999")
    assert "not on whitelist" in why_norm
    _, why_recip = action_guard.can_follow("randomstranger999", reciprocal=True)
    assert "not on whitelist" not in why_recip
    # kill switch: bypass off => reciprocal blocked again
    monkeypatch.setattr(config, "FOLLOWBACK_BYPASS_WHITELIST", False)
    _, why_off = action_guard.can_follow("randomstranger999", reciprocal=True)
    assert "not on whitelist" in why_off


# --- Write spacing, drawn once per write (#131) ------------------------------
# The clock stands still after a write, so seconds_until_allowed is then the
# whole gap that write drew.


def _ledger_clock(monkeypatch):
    """A Toronto noon clock shared by the ledger and the Waking hours check,
    over an empty in-memory ledger."""
    from src.guards import active_hours

    now = [datetime(2026, 9, 21, 12, tzinfo=TORONTO)]
    monkeypatch.setattr(active_hours, "now_local", lambda: now[0])
    monkeypatch.setattr(ag, "now_local", lambda: now[0])
    monkeypatch.setattr(ag, "LEDGER", MemoryLedger())
    return now


def test_reply_gap_is_drawn_once_per_reply(monkeypatch):
    now = _ledger_clock(monkeypatch)
    ag.record(ag.REPLY, "https://x.com/a/status/1")
    gap = ag.seconds_until_allowed(ag.REPLY)
    low = config.MIN_SECONDS_BETWEEN_REPLIES
    assert low <= gap <= low + config.REPLY_JITTER_SECONDS
    assert {ag.seconds_until_allowed(ag.REPLY) for _ in range(50)} == {gap}, \
        "every caller sees one gap"

    ag.record(ag.REPLY, "https://x.com/a/status/2", dry_run=True)
    assert ag.seconds_until_allowed(ag.REPLY) == gap, "a dry-run row draws nothing"

    now[0] += timedelta(seconds=30)
    ag.record(ag.REPLY, "https://x.com/a/status/3")
    assert ag.seconds_until_allowed(ag.REPLY) != gap, "a new Reply draws a new gap"


def test_the_gap_is_seeded_on_the_stamp_of_the_last_write(monkeypatch):
    import random
    now = _ledger_clock(monkeypatch)
    ag.record(ag.REPLY, "https://x.com/a/status/1")
    draw = random.Random(f"reply:{now[0].isoformat()}").uniform(0, config.REPLY_JITTER_SECONDS)
    assert ag.seconds_until_allowed(ag.REPLY) == config.MIN_SECONDS_BETWEEN_REPLIES + draw


def test_reply_gap_keeps_its_jitter_across_replies(monkeypatch):
    now = _ledger_clock(monkeypatch)
    gaps = []
    for n in range(40):
        now[0] += timedelta(seconds=17)
        ag.record(ag.REPLY, f"https://x.com/a/status/{n}")
        gaps.append(ag.seconds_until_allowed(ag.REPLY))
    low, jitter = config.MIN_SECONDS_BETWEEN_REPLIES, config.REPLY_JITTER_SECONDS
    assert all(low <= g <= low + jitter for g in gaps)
    assert max(gaps) - min(gaps) > jitter / 2, "the jitter still spreads the gaps"


def test_wait_never_exceeds_one_gap_after_a_future_ledger_row(monkeypatch):
    """A Reply stamped an hour ahead (clock set back) would otherwise make
    the pipeline wait an hour; the chokepoint alone keeps refusing it."""
    now = _ledger_clock(monkeypatch)
    now[0] += timedelta(hours=1)
    ag.record(ag.REPLY, "https://x.com/a/status/1")
    gap = ag.seconds_until_allowed(ag.REPLY)
    now[0] -= timedelta(hours=1)
    assert ag.seconds_until_allowed(ag.REPLY) == gap
    assert ag.can_post(ag.REPLY)[0] is False


def test_can_post_reply_admits_exactly_when_the_wait_reaches_zero(monkeypatch):
    now = _ledger_clock(monkeypatch)
    assert ag.seconds_until_allowed(ag.REPLY) == 0, "an empty ledger waits for nothing"
    ag.record(ag.REPLY, "https://x.com/a/status/1")
    wait = ag.seconds_until_allowed(ag.REPLY)
    assert wait >= config.MIN_SECONDS_BETWEEN_REPLIES

    now[0] += timedelta(seconds=wait - 0.01)
    assert 0 < ag.seconds_until_allowed(ag.REPLY) <= 0.011
    verdicts = {ag.can_post(ag.REPLY) for _ in range(50)}
    assert verdicts == {(False, f"too soon since last reply (need ~{int(wait)}s gap)")}, \
        "retrying cannot fish for a smaller draw"

    now[0] += timedelta(seconds=0.02)
    assert ag.seconds_until_allowed(ag.REPLY) == 0
    assert ag.can_post(ag.REPLY) == (True, "")


def test_original_gap_is_drawn_once_per_original(monkeypatch):
    now = _ledger_clock(monkeypatch)
    monkeypatch.setattr(config, "POST_JITTER_SECONDS", 600)
    ag.record(ag.POST, "original")
    gap = ag.seconds_until_allowed(ag.POST)
    assert config.MIN_SECONDS_BETWEEN_POSTS <= gap <= config.MIN_SECONDS_BETWEEN_POSTS + 600

    now[0] += timedelta(seconds=gap - 1)
    assert {ag.can_post(ag.POST) for _ in range(50)} == \
        {(False, f"too soon since last post (need ~{int(gap)}s gap)")}
    now[0] += timedelta(seconds=2)
    assert ag.seconds_until_allowed(ag.POST) == 0
    assert ag.can_post(ag.POST) == (True, "")


def test_follow_gap_is_drawn_once_per_follow(monkeypatch, tmp_path):
    """follow_engagers pre-checks can_follow and follow_account judges it
    again: both must see one gap, or each cycle retries for a small draw."""
    now = _ledger_clock(monkeypatch)
    monkeypatch.setattr(config, "MIN_SECONDS_BETWEEN_FOLLOWS", 600)
    monkeypatch.setattr(config, "FOLLOW_SPACING_JITTER_SECONDS", 300)
    monkeypatch.setattr(config, "FOLLOW_WHITELIST_ONLY", False)
    monkeypatch.setattr(config, "FOLLOW_GROWTH_MODE", False)
    monkeypatch.setattr(config, "FOLLOW_ENFORCE_RATIO", False)
    _counts(monkeypatch, tmp_path, 100, 10)
    ag.record(ag.FOLLOW, "fan1")
    gap = ag.seconds_until_allowed(ag.FOLLOW)
    assert 600 <= gap <= 900

    ag.record(ag.FOLLOW, "fan2", dry_run=True)
    ag.record(ag.UNFOLLOW, "fan3")
    assert ag.seconds_until_allowed(ag.FOLLOW) == gap, "only shipped follows draw a gap"

    now[0] += timedelta(seconds=gap - 1)
    assert {ag.can_follow("fan4") for _ in range(50)} == \
        {(False, f"too soon since last follow (need ~{int(gap)}s gap)")}, \
        "retrying cannot fish for a smaller draw"
    now[0] += timedelta(seconds=2)
    assert ag.seconds_until_allowed(ag.FOLLOW) == 0
    assert ag.can_follow("fan4") == (True, "")
