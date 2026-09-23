"""src/guards/action_guard: the daily budget, follow policy, write spacing."""
import json
from datetime import datetime

import pytest

from src.core import config
from src.guards import action_guard as ag
from tests.helpers import TORONTO, stop_requested, clock


# --- daily budget and caps ----------------------------------------------------


def test_toronto_day_budget_ignores_dry_runs_and_uses_all_profile_actions(monkeypatch, tmp_path):
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    rows = [{"action": ag.POST, "ts": "2026-09-20T03:59:00+00:00"},
            {"action": ag.POST, "ts": "2026-09-20T04:00:00+00:00", "dry_run": True}]
    rows += [{"action": action, "ts": "2026-09-20T06:00:00"}
             for action in [ag.POST] * 5 + [ag.QUOTE, ag.RETWEET]]
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(rows))
    monkeypatch.setattr(config, "ACTION_LEDGER_FILE", str(path))
    assert ag.count_today(ag.POST) == 5
    assert ag.profile_count_today() == 7
    assert ag.can_post(ag.POST)[0]
    assert ag.seconds_since_last(ag.POST) == 6 * 3600
    ag.record(ag.POST)
    assert ag.profile_count_today() == 8
    assert not ag.can_post(ag.POST, urgent=True, high_value=True)[0]
    assert ag.can_post(ag.REPLY)[0]


def test_replies_uncapped_but_still_paced(monkeypatch):
    monkeypatch.setattr(ag, "count_today", lambda action: 1_000_000)
    monkeypatch.setattr(ag, "spacing_ok", lambda *a: True)
    assert ag.can_post(ag.REPLY)[0]
    monkeypatch.setattr(ag, "spacing_ok", lambda *a: False)
    assert not ag.can_post(ag.REPLY, urgent=True)[0]


def test_corrupt_ledger_cannot_grant_extra_posts(monkeypatch, tmp_path):
    ledger = tmp_path / "broken.json"
    ledger.write_text("{broken")
    monkeypatch.setattr(config, "ACTION_LEDGER_FILE", str(ledger))
    with pytest.raises(RuntimeError, match="ledger unreadable"):
        ag.can_post(ag.POST)


@pytest.mark.usefixtures("isolate_dedup")
def test_mega_viral_quote_cannot_bypass_editorial_policy(monkeypatch):
    from src.guards import action_guard as ag
    monkeypatch.setattr(ag, "spacing_ok", lambda *a: True)
    for urgent in (False, True):
        assert not ag.can_post(ag.QUOTE, high_value=True, urgent=urgent)[0]


@pytest.mark.usefixtures("isolate_dedup")
def test_urgent_quote_obeys_editorial_policy(monkeypatch):
    from src.guards import action_guard as ag
    monkeypatch.setattr(ag, "count_today", lambda a: 0)
    assert not ag.can_post(ag.QUOTE, urgent=True)[0]


def test_can_post_refuses_after_stop(monkeypatch):
    from src.guards import action_guard

    assert action_guard.can_post(action_guard.REPLY)[0] is True
    stop_requested(monkeypatch)

    ok, why = action_guard.can_post(action_guard.REPLY)
    assert not ok and "stop" in why


# --- 2026-06-07 agent spec: follow policy (Part 1 hard constraints) ---------


@pytest.fixture()
def follow_env(monkeypatch, tmp_path):
    """Isolated ledger + whitelist + counts for action_guard follow tests."""
    from src.guards import action_guard as ag
    from src.core import config

    monkeypatch.setattr(config, "ACTION_LEDGER_FILE", str(tmp_path / "ledger.json"))
    wl = tmp_path / "whitelist.json"
    wl.write_text(json.dumps({"tiers": {
        "tier1": ["TheBTCTherapist"],
        "tier2": ["morganhousel"],
        "tier3": ["karpathy"],
        "tier4": ["saylor", "balajis"],
    }}))
    monkeypatch.setattr(config, "WHITELIST_FILE", str(wl))
    ag._WL_CACHE = {}
    ag._WL_MTIME = 0.0
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
    yield ag
    ag._WL_CACHE = {}
    ag._WL_MTIME = 0.0


@pytest.mark.usefixtures("isolate_dedup")
def test_whitelist_loads_tier4(follow_env):
    ag = follow_env
    wl = ag.load_whitelist()
    assert "saylor" in wl["tier4"]
    assert "saylor" in wl["all"]
    assert ag.is_whitelisted("balajis")


@pytest.mark.usefixtures("isolate_dedup")
def test_follow_blocked_at_low_phase_ceiling(follow_env, monkeypatch):
    """While followers are low (<300), total following must stay under ~150."""
    ag = follow_env
    monkeypatch.setattr(ag, "current_counts", lambda: (100, 150))
    ok, why = ag.can_follow("karpathy")
    assert not ok and "ceiling" in why


@pytest.mark.usefixtures("isolate_dedup")
def test_follow_allowed_under_low_phase_ceiling(follow_env, monkeypatch):
    ag = follow_env
    monkeypatch.setattr(ag, "current_counts", lambda: (100, 149))
    ok, why = ag.can_follow("karpathy")
    assert ok, why


@pytest.mark.usefixtures("isolate_dedup")
def test_follow_never_exceeds_hard_300_cap(follow_env, monkeypatch):
    """Even with a big follower count, total following is hard-capped at 300."""
    ag = follow_env
    monkeypatch.setattr(ag, "current_counts", lambda: (10000, 300))
    ok, why = ag.can_follow("saylor")
    assert not ok and "ceiling" in why
    monkeypatch.setattr(ag, "current_counts", lambda: (10000, 299))
    ok, why = ag.can_follow("saylor")
    assert ok, why


@pytest.mark.usefixtures("isolate_dedup")
def test_follow_keeps_following_below_followers_mid_phase(follow_env, monkeypatch):
    """Once followers exceed 300, following must stay <= followers."""
    ag = follow_env
    monkeypatch.setattr(ag, "current_counts", lambda: (220, 200))
    # followers=220 is still < FOLLOW_LOW_PHASE_FOLLOWERS → 150 ceiling rules
    ok, why = ag.can_follow("morganhousel")
    assert not ok and "ceiling" in why
    monkeypatch.setattr(ag, "current_counts", lambda: (320, 280))
    ok, why = ag.can_follow("morganhousel")
    assert ok, why  # 280+1 <= min(300, 320)


@pytest.mark.usefixtures("isolate_dedup")
def test_follow_spacing_blocks_burst(follow_env, monkeypatch):
    """Never burst-follow: a follow within the 10-min gap is refused."""
    from src.core import config
    ag = follow_env
    monkeypatch.setattr(config, "MIN_SECONDS_BETWEEN_FOLLOWS", 600)
    monkeypatch.setattr(ag, "current_counts", lambda: (100, 10))
    ag.record(ag.FOLLOW, target="TheBTCTherapist")
    ok, why = ag.can_follow("morganhousel")
    assert not ok and "too soon" in why


@pytest.mark.usefixtures("isolate_dedup")
def test_follow_rejects_non_whitelisted(follow_env, monkeypatch):
    ag = follow_env
    monkeypatch.setattr(ag, "current_counts", lambda: (100, 10))
    ok, why = ag.can_follow("randomspamaccount")
    assert not ok and "whitelist" in why


@pytest.mark.usefixtures("isolate_dedup")
def test_unfollow_protects_all_whitelist_tiers(follow_env):
    """No churn on seeds: tier3/tier4 are protected from unfollow too."""
    ag = follow_env
    for handle in ("TheBTCTherapist", "morganhousel", "karpathy", "saylor"):
        ok, why = ag.can_unfollow(handle)
        assert not ok and "protected" in why, (handle, why)


@pytest.mark.usefixtures("isolate_dedup")
def test_follow_growth_mode_unties_ceiling_from_followers(monkeypatch):
    """2026-06-11 operator: "go back on following people and following back".
    Growth mode must untie the following ceiling from the followers count
    (following>followers mid-purge would block every follow), while
    FOLLOW_TOTAL_CAP stays the hard stop and legacy mode keeps the old
    followers-tied invariant."""
    from src.guards import action_guard
    from src.core import config

    monkeypatch.setattr(action_guard, "current_counts",
                        lambda: (1423, 2485))  # followers, following
    monkeypatch.setattr(config, "FOLLOW_TOTAL_CAP", 3000)

    monkeypatch.setattr(config, "FOLLOW_GROWTH_MODE", True)
    assert action_guard.following_ceiling() == 3000, \
        "growth mode: ceiling is FOLLOW_TOTAL_CAP, not the followers count"

    monkeypatch.setattr(config, "FOLLOW_GROWTH_MODE", False)
    assert action_guard.following_ceiling() == 1423, \
        "legacy mode keeps following <= followers"


@pytest.mark.usefixtures("isolate_dedup")
def test_reciprocal_followback_bypasses_whitelist(monkeypatch):
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


def _ledger_clock(monkeypatch):
    """A Toronto noon clock shared by the ledger and the Waking hours check."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.guards import action_guard, active_hours

    now = [datetime(2026, 9, 21, 12, tzinfo=ZoneInfo("America/Toronto"))]
    monkeypatch.setattr(active_hours, "now_local", lambda: now[0])
    monkeypatch.setattr(action_guard, "now_local", lambda: now[0])
    return now


def test_reply_gap_is_drawn_once_per_reply(monkeypatch):
    from datetime import timedelta
    from src.core import config
    from src.guards import action_guard as ag

    now = _ledger_clock(monkeypatch)
    ag.record(ag.REPLY, "https://x.com/a/status/1")
    gap = ag.spacing_gap(ag.REPLY)
    low = config.MIN_SECONDS_BETWEEN_REPLIES
    assert low <= gap <= low + config.REPLY_JITTER_SECONDS
    assert {ag.spacing_gap(ag.REPLY) for _ in range(50)} == {gap}, "every caller sees one gap"

    ag.record(ag.REPLY, "https://x.com/a/status/2", dry_run=True)
    assert ag.spacing_gap(ag.REPLY) == gap, "a dry-run row draws nothing"

    now[0] += timedelta(seconds=30)
    ag.record(ag.REPLY, "https://x.com/a/status/3")
    assert ag.spacing_gap(ag.REPLY) != gap, "a new Reply draws a new gap"


def test_reply_gap_keeps_its_jitter_across_replies(monkeypatch):
    from datetime import timedelta
    from src.core import config
    from src.guards import action_guard as ag

    now = _ledger_clock(monkeypatch)
    gaps = []
    for n in range(40):
        now[0] += timedelta(seconds=17)
        ag.record(ag.REPLY, f"https://x.com/a/status/{n}")
        gaps.append(ag.spacing_gap(ag.REPLY))
    low, jitter = config.MIN_SECONDS_BETWEEN_REPLIES, config.REPLY_JITTER_SECONDS
    assert all(low <= g <= low + jitter for g in gaps)
    assert max(gaps) - min(gaps) > jitter / 2, "the jitter still spreads the gaps"


def test_wait_never_exceeds_one_gap_after_a_future_ledger_row(monkeypatch):
    """A Reply stamped an hour ahead (clock set back) would otherwise make
    the pipeline wait an hour; the chokepoint alone keeps refusing it."""
    from datetime import timedelta
    from src.guards import action_guard as ag

    now = _ledger_clock(monkeypatch)
    now[0] += timedelta(hours=1)
    ag.record(ag.REPLY, "https://x.com/a/status/1")
    now[0] -= timedelta(hours=1)
    assert ag.seconds_until_allowed(ag.REPLY) == ag.spacing_gap(ag.REPLY)
    assert ag.can_post(ag.REPLY)[0] is False


def test_can_post_reply_admits_exactly_when_the_wait_reaches_zero(monkeypatch):
    from datetime import timedelta
    from src.guards import action_guard as ag

    now = _ledger_clock(monkeypatch)
    assert ag.seconds_until_allowed(ag.REPLY) == 0, "an empty ledger waits for nothing"
    ag.record(ag.REPLY, "https://x.com/a/status/1")
    wait = ag.seconds_until_allowed(ag.REPLY)
    assert wait == ag.spacing_gap(ag.REPLY)

    now[0] += timedelta(seconds=wait - 0.01)
    assert 0 < ag.seconds_until_allowed(ag.REPLY) <= 0.011
    verdicts = {ag.can_post(ag.REPLY) for _ in range(50)}
    assert verdicts == {(False, f"too soon since last reply (need ~{int(wait)}s gap)")}, \
        "retrying cannot fish for a smaller draw"

    now[0] += timedelta(seconds=0.02)
    assert ag.seconds_until_allowed(ag.REPLY) == 0
    assert ag.can_post(ag.REPLY) == (True, "")


def test_original_gap_is_drawn_once_per_original(monkeypatch):
    from datetime import timedelta
    from src.core import config
    from src.guards import action_guard as ag

    now = _ledger_clock(monkeypatch)
    monkeypatch.setattr(config, "POST_JITTER_SECONDS", 600)
    ag.record(ag.POST, "original")
    gap = ag.spacing_gap(ag.POST)
    assert config.MIN_SECONDS_BETWEEN_POSTS <= gap <= config.MIN_SECONDS_BETWEEN_POSTS + 600
    assert ag.seconds_until_allowed(ag.POST) == gap

    now[0] += timedelta(seconds=gap - 1)
    assert {ag.can_post(ag.POST) for _ in range(50)} == \
        {(False, f"too soon since last post (need ~{int(gap)}s gap)")}
    now[0] += timedelta(seconds=2)
    assert ag.seconds_until_allowed(ag.POST) == 0
    assert ag.can_post(ag.POST) == (True, "")


def test_follow_gap_is_drawn_once_per_follow(monkeypatch):
    """follow_engagers pre-checks can_follow and follow_account judges it
    again: both must see one gap, or each cycle retries for a small draw."""
    from datetime import timedelta
    from src.core import config
    from src.guards import action_guard as ag

    now = _ledger_clock(monkeypatch)
    monkeypatch.setattr(config, "MIN_SECONDS_BETWEEN_FOLLOWS", 600)
    monkeypatch.setattr(config, "FOLLOW_SPACING_JITTER_SECONDS", 300)
    monkeypatch.setattr(config, "FOLLOW_WHITELIST_ONLY", False)
    monkeypatch.setattr(config, "FOLLOW_GROWTH_MODE", False)
    monkeypatch.setattr(config, "FOLLOW_ENFORCE_RATIO", False)
    monkeypatch.setattr(ag, "current_counts", lambda: (100, 10))
    ag.record(ag.FOLLOW, "fan1")
    gap = ag.spacing_gap(ag.FOLLOW)
    assert 600 <= gap <= 900
    assert ag.seconds_until_allowed(ag.FOLLOW) == gap

    ag.record(ag.FOLLOW, "fan2", dry_run=True)
    ag.record(ag.UNFOLLOW, "fan3")
    assert ag.spacing_gap(ag.FOLLOW) == gap, "only shipped follows draw a gap"

    now[0] += timedelta(seconds=gap - 1)
    assert {ag.can_follow("fan4") for _ in range(50)} == \
        {(False, f"too soon since last follow (need ~{int(gap)}s gap)")}, \
        "retrying cannot fish for a smaller draw"
    now[0] += timedelta(seconds=2)
    assert ag.seconds_until_allowed(ag.FOLLOW) == 0
    assert ag.can_follow("fan4") == (True, "")
