"""src/guards/follow_policy: the follow rules, their named refusals, the
quality gate and the followed accounts (#172).

The policy asks an in-memory ledger (the `memory_ledger` fixture) through
action_guard."""
import json
from datetime import datetime, timedelta

import pytest

from src.core import config
from src.core.state_errors import StateUnreadable
from src.core.state_store import StateFile
from src.guards import action_guard as ag
from src.guards import follow_policy as fp
from src.guards.follow_policy import ADMITTED, Refusal, Verdict
from src.guards.ledger import MemoryLedger
from tests.helpers import TORONTO, clock


# --- 2026-06-07 agent spec: follow policy (Part 1 hard constraints) ---------


@pytest.fixture()
def follow_env(monkeypatch, tmp_path, memory_ledger):
    """Isolated ledger + whitelist + counts for the follow policy tests."""
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
    return fp


def _counts(monkeypatch, tmp_path, followers, following):
    """The account's counts as the follower tracker and the following
    counter leave them on disk."""
    monkeypatch.delenv("FOLLOWING_COUNT_OVERRIDE", raising=False)
    (tmp_path / "follower_history.json").write_text(json.dumps([{"count": followers}]))
    (tmp_path / "following_count.json").write_text(json.dumps({"count": following}))


def test_whitelist_loads_tier4(follow_env):
    wl = fp.load_whitelist()
    assert "saylor" in wl["tier4"]
    assert "saylor" in wl["all"]
    assert fp.is_whitelisted("balajis")


@pytest.mark.parametrize("handle", ["", "aisha mansion", "caborashedzaborashedles", "josé",
                                    "a/b", "@karpathy", None])
def test_an_invalid_handle_is_a_policy_refusal(follow_env, monkeypatch, tmp_path, handle):
    """The one handle check: X handles are [A-Za-z0-9_]{1,15}."""
    _counts(monkeypatch, tmp_path, 100, 10)
    verdict = fp.judge(handle)
    assert verdict.refusal is Refusal.POLICY and "invalid handle" in verdict.reason


def test_follow_blocked_at_low_phase_ceiling(follow_env, monkeypatch, tmp_path):
    """While followers are low (<300), total following must stay under ~150."""
    _counts(monkeypatch, tmp_path, 100, 150)
    verdict = fp.judge("karpathy")
    assert verdict.refusal is Refusal.CAP_REACHED and "ceiling" in verdict.reason


def test_follow_allowed_under_low_phase_ceiling(follow_env, monkeypatch, tmp_path):
    _counts(monkeypatch, tmp_path, 100, 149)
    assert fp.judge("karpathy") == ADMITTED


def test_follow_never_exceeds_hard_300_cap(follow_env, monkeypatch, tmp_path):
    """Even with a big follower count, total following is hard-capped at 300."""
    _counts(monkeypatch, tmp_path, 10000, 300)
    verdict = fp.judge("saylor")
    assert verdict.refusal is Refusal.CAP_REACHED and "ceiling" in verdict.reason
    _counts(monkeypatch, tmp_path, 10000, 299)
    assert fp.judge("saylor") == ADMITTED


def test_follow_keeps_following_below_followers_mid_phase(follow_env, monkeypatch, tmp_path):
    """Once followers exceed 300, following must stay <= followers."""
    _counts(monkeypatch, tmp_path, 220, 200)
    # followers=220 is still < FOLLOW_LOW_PHASE_FOLLOWERS → 150 ceiling rules
    verdict = fp.judge("morganhousel")
    assert verdict.refusal is Refusal.CAP_REACHED and "ceiling" in verdict.reason
    _counts(monkeypatch, tmp_path, 320, 280)
    assert fp.judge("morganhousel") == ADMITTED  # 280+1 <= min(300, 320)


@pytest.mark.parametrize("name", ["followed_accounts.json", "following_count.json"])
def test_an_unreadable_following_count_refuses_every_follow(follow_env, monkeypatch, tmp_path, name):
    """#171: with the following count unknown, the policy skipped the
    ceiling. The count comes from following_count.json, else from the
    followed list: either one unreadable now refuses the follow as a ceiling
    reached, and the file waits for the Operator."""
    monkeypatch.delenv("FOLLOWING_COUNT_OVERRIDE", raising=False)
    (tmp_path / "follower_history.json").write_text(json.dumps([{"count": 100}]))
    path = tmp_path / name
    path.write_text('{"count": 1')

    verdict = fp.judge("karpathy")

    assert verdict.refusal is Refusal.CAP_REACHED
    assert "following ceiling unreadable" in verdict.reason and name in verdict.reason
    assert path.read_text() == '{"count": 1'


def test_an_unreadable_follower_history_leaves_the_lowest_ceiling(follow_env, monkeypatch, tmp_path):
    """follower_history.json is disposable: unreadable, it reads as no
    sample, and the ceiling falls to its low-phase value."""
    _counts(monkeypatch, tmp_path, 10000, 150)
    (tmp_path / "follower_history.json").write_text('[{"count": 1')
    verdict = fp.judge("karpathy")
    assert verdict.refusal is Refusal.CAP_REACHED and "(150 >= 150)" in verdict.reason


@pytest.mark.parametrize("history", ['[{"count": 1', "[]"])
def test_the_ratio_brake_refuses_while_the_follower_count_is_unknown(follow_env, monkeypatch,
                                                                    tmp_path, history):
    """#171: the ratio brake skipped itself when follower_history.json
    held no sample, so losing the disposable file admitted follows the
    brake would refuse."""
    monkeypatch.setattr(config, "FOLLOW_ENFORCE_RATIO", True)
    _counts(monkeypatch, tmp_path, 100, 10)
    assert fp.judge("karpathy") == ADMITTED

    (tmp_path / "follower_history.json").write_text(history)

    assert fp.judge("karpathy") == Verdict(
        Refusal.CAP_REACHED, "follower count unknown: ratio brake cannot be checked")


def test_a_follow_decision_reads_each_follow_file_once(follow_env, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FOLLOW_ENFORCE_RATIO", True)
    _counts(monkeypatch, tmp_path, 100, 10)
    reads = []
    real_read = StateFile.read
    monkeypatch.setattr(StateFile, "read", lambda self: reads.append(self.name) or real_read(self))

    assert fp.judge("karpathy") == ADMITTED

    assert sorted(reads) == ["follow_quality_rejects.json", "follower_history.json",
                             "following_count.json", "whitelist.json"]


@pytest.mark.parametrize("whitelist_only", [True, False])
def test_an_unreadable_whitelist_stops_every_follow(follow_env, monkeypatch, tmp_path,
                                                    whitelist_only):
    """#171: an unreadable whitelist.json read as empty. #172: a refusal let
    follow_engagers mark each Engager tried, so judge raises instead, and
    the file waits for the Operator."""
    monkeypatch.setattr(config, "FOLLOW_WHITELIST_ONLY", whitelist_only)
    _counts(monkeypatch, tmp_path, 100, 10)
    path = tmp_path / "whitelist.json"
    path.write_text('{"tiers": {"tier1": ["karp')

    with pytest.raises(StateUnreadable, match="whitelist.json"):
        fp.judge("karpathy", reciprocal=True)
    assert path.read_text() == '{"tiers": {"tier1": ["karp'


def test_the_quality_gate_refuses_on_a_whitelist_unreadable_on_the_open_profile(
        follow_env, tmp_path):
    """On the open profile the gate refuses instead of raising, so
    follow_account still closes its tab."""
    (tmp_path / "whitelist.json").write_text('{"tiers": {"tier1": ["karp')
    verdict = fp.judge_profile("karpathy", lambda: pytest.fail("profile read"))
    assert verdict.refusal is Refusal.POLICY and "whitelist unreadable" in verdict.reason


@pytest.mark.parametrize("handle, valid", [("karpathy", True), ("a_1", True), ("x" * 15, True),
                                           ("x" * 16, False), ("@karpathy", False), ("", False),
                                           (None, False)])
def test_valid_handle_is_the_policy_handle_check(handle, valid):
    assert fp.valid_handle(handle) is valid


def test_adjust_following_keeps_the_baseline_and_never_overwrites_an_unreadable_count(
        monkeypatch, tmp_path):
    monkeypatch.setenv("DRY_RUN", "0")
    path = tmp_path / "following_count.json"
    path.write_text(json.dumps({"count": 10, "baseline": 4200}))
    fp.adjust_following(+1)
    doc = json.loads(path.read_text())
    assert (doc["count"], doc["baseline"]) == (11, 4200) and "updated" in doc

    path.write_text('{"count": 1')
    fp.adjust_following(+1)
    assert path.read_text() == '{"count": 1'


def test_follow_spacing_blocks_burst(follow_env, monkeypatch, tmp_path):
    """Never burst-follow: a follow within the 10-min gap is refused."""
    monkeypatch.setattr(config, "MIN_SECONDS_BETWEEN_FOLLOWS", 600)
    _counts(monkeypatch, tmp_path, 100, 10)
    ag.record(ag.FOLLOW, target="TheBTCTherapist")
    verdict = fp.judge("morganhousel")
    assert verdict.refusal is Refusal.TOO_SOON and "too soon" in verdict.reason


def test_follow_rejects_non_whitelisted(follow_env, monkeypatch, tmp_path):
    _counts(monkeypatch, tmp_path, 100, 10)
    verdict = fp.judge("randomspam")
    assert verdict.refusal is Refusal.POLICY and "whitelist" in verdict.reason


def _noon(monkeypatch):
    now = datetime(2026, 9, 20, 12, tzinfo=TORONTO)
    clock(monkeypatch, now)
    return now


def test_anti_churn_counts_any_follow_or_unfollow_within_the_cooldown(follow_env, monkeypatch,
                                                                     memory_ledger, tmp_path):
    now = _noon(monkeypatch)
    _counts(monkeypatch, tmp_path, 100, 10)
    cooldown = timedelta(days=config.CHURN_COOLDOWN_DAYS)
    memory_ledger.append(ag.FOLLOW, "karpathy", True, now - cooldown + timedelta(minutes=1))
    memory_ledger.append(ag.UNFOLLOW, "morganhousel", False, now - cooldown)
    memory_ledger.append(ag.LIKE, "saylor", False, now)

    verdict = fp.judge("KarPathy")
    assert verdict.refusal is Refusal.POLICY and "anti-churn" in verdict.reason, \
        "a dry-run follow still touches"
    assert fp.judge("morganhousel") == ADMITTED, "the cooldown ends on its last second"
    assert fp.judge("saylor") == ADMITTED, "a like is no touch"


def test_follow_cap_counts_todays_shipped_rows(follow_env, monkeypatch, memory_ledger, tmp_path):
    now = _noon(monkeypatch)
    _counts(monkeypatch, tmp_path, 100, 10)
    monkeypatch.setattr(config, "FOLLOW_WHITELIST_ONLY", False)
    monkeypatch.setattr(config, "MAX_FOLLOWS_PER_DAY", 2)
    memory_ledger.append(ag.FOLLOW, "yesterday", False, now - timedelta(days=1))
    memory_ledger.append(ag.FOLLOW, "dry", True, now)
    memory_ledger.append(ag.FOLLOW, "today", False, now - timedelta(hours=1))
    assert fp.judge("stranger") == ADMITTED

    ag.record(ag.FOLLOW, "another")

    assert fp.judge("stranger") == Verdict(Refusal.CAP_REACHED, "daily follow cap reached (2)")


def test_follow_growth_mode_unties_ceiling_from_followers(follow_env, monkeypatch, tmp_path):
    """2026-06-11 operator: "go back on following people and following back".
    Growth mode must untie the following ceiling from the followers count
    (following>followers mid-purge would block every follow), while
    FOLLOW_TOTAL_CAP stays the hard stop and legacy mode keeps the old
    followers-tied invariant."""
    monkeypatch.setattr(config, "FOLLOW_TOTAL_CAP", 3000)

    monkeypatch.setattr(config, "FOLLOW_GROWTH_MODE", True)
    _counts(monkeypatch, tmp_path, 1423, 2999)  # followers, following
    assert fp.judge("karpathy") == ADMITTED, \
        "growth mode: ceiling is FOLLOW_TOTAL_CAP, not the followers count"
    _counts(monkeypatch, tmp_path, 1423, 3000)
    verdict = fp.judge("karpathy")
    assert verdict.refusal is Refusal.CAP_REACHED and "(3000 >= 3000)" in verdict.reason

    monkeypatch.setattr(config, "FOLLOW_GROWTH_MODE", False)
    _counts(monkeypatch, tmp_path, 1423, 1422)
    assert fp.judge("karpathy") == ADMITTED
    _counts(monkeypatch, tmp_path, 1423, 1423)
    verdict = fp.judge("karpathy")
    assert verdict.refusal is Refusal.CAP_REACHED and "(1423 >= 1423)" in verdict.reason, \
        "legacy mode keeps following <= followers"


def test_reciprocal_followback_bypasses_whitelist(monkeypatch, memory_ledger):
    """Self-improve #3 (2026-06-24): followback was dead — whitelist-only
    blocked following people who engage with us. reciprocal=True bypasses ONLY
    the whitelist gate (when FOLLOWBACK_BYPASS_WHITELIST), never the other
    gates. Pin: a non-whitelisted handle is whitelist-blocked normally but
    NOT for a reciprocal follow-back."""
    monkeypatch.setattr(config, "FOLLOW_WHITELIST_ONLY", True)
    monkeypatch.setattr(config, "FOLLOWBACK_BYPASS_WHITELIST", True)
    monkeypatch.setattr(fp, "is_whitelisted", lambda h, **k: False)
    assert "not on whitelist" in fp.judge("randomstranger9").reason
    assert "not on whitelist" not in fp.judge("randomstranger9", reciprocal=True).reason
    # kill switch: bypass off => reciprocal blocked again
    monkeypatch.setattr(config, "FOLLOWBACK_BYPASS_WHITELIST", False)
    assert "not on whitelist" in fp.judge("randomstranger9", reciprocal=True).reason


def test_follow_gap_is_drawn_once_per_follow(monkeypatch, tmp_path):
    """A job retrying a follow the spacing refused must meet the same gap
    each cycle, or it would retry for a small draw."""
    from src.guards import active_hours

    now = [datetime(2026, 9, 21, 12, tzinfo=TORONTO)]
    monkeypatch.setattr(active_hours, "now_local", lambda: now[0])
    monkeypatch.setattr(ag, "now_local", lambda: now[0])
    monkeypatch.setattr(ag, "LEDGER", MemoryLedger())
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
    assert {fp.judge("fan4") for _ in range(50)} == \
        {Verdict(Refusal.TOO_SOON, f"too soon since last follow (need ~{int(gap)}s gap)")}, \
        "retrying cannot fish for a smaller draw"
    now[0] += timedelta(seconds=2)
    assert ag.seconds_until_allowed(ag.FOLLOW) == 0
    assert fp.judge("fan4") == ADMITTED


# --- the quality gate -----------------------------------------------------------


def test_follow_quality_gate_blocks_small_and_offniche(monkeypatch):
    """2026-06-12 operator: "the accounts you follow are trash, very small
    ... not related to AI or investment or crypto". The follow chokepoint
    must refuse small or off-niche profiles (whitelist seeds exempt), and
    must not follow blind when the followers count is unreadable."""
    assert fp._parse_follower_count("12.3K") == 12300
    assert fp._parse_follower_count("1,423") == 1423
    assert fp._parse_follower_count("2.1M") == 2_100_000
    assert fp._parse_follower_count("") == -1

    monkeypatch.setenv("FOLLOW_MIN_FOLLOWERS", "2000")
    monkeypatch.setenv("FOLLOW_REQUIRE_NICHE", "1")

    ok, why = fp._quality_decision(150, "AI trader", "x", whitelisted=False)
    assert not ok and "too small" in why
    ok, why = fp._quality_decision(50_000, "dog photos and recipes", "x", whitelisted=False)
    assert not ok and "off-niche" in why
    ok, why = fp._quality_decision(-1, "AI investor", "x", whitelisted=False)
    assert not ok and "unreadable" in why
    ok, _ = fp._quality_decision(50_000, "Macro investor, AI & crypto", "x", whitelisted=False)
    assert ok
    # Whitelisted seeds bypass (e.g. Graphseo's SEO bio is off-niche by
    # design — operator-pinned accounts are never gated).
    ok, _ = fp._quality_decision(10, "SEO expert", "x", whitelisted=True)
    assert ok


def test_follow_gate_english_only(monkeypatch):
    """Operator 2026-07-19: 'follow US / english accounts not foreigner
    langage follows' — the quality gate (rides EVERY follow path via the
    follow_account chokepoint) must reject non-Latin-script and foreign-
    language bios."""
    monkeypatch.setenv("FOLLOW_REQUIRE_ENGLISH", "1")
    monkeypatch.setenv("FOLLOW_REQUIRE_NICHE", "1")
    monkeypatch.setenv("FOLLOW_MIN_FOLLOWERS", "2000")

    ok, _ = fp._quality_decision(
        50000, "AI investor. Building agents, GPUs and datacenter plays.",
        "Jane Doe", False)
    assert ok, "big EN on-niche account must pass"
    ok, why = fp._quality_decision(
        50000, "AIと暗号資産の最新情報を毎日配信します。株式投資も。", "田中太郎", False)
    assert not ok and "non-English" in why, "Japanese bio must be rejected"
    ok, why = fp._quality_decision(
        50000, "Analyse crypto et IA pour les investisseurs. Avec vous dans les marchés.",
        "Jean Dupont", False)
    assert not ok and "non-English" in why, "French bio must be rejected"
    # Whitelisted seeds stay exempt (Graphseo's FR bio is by design)
    ok, _ = fp._quality_decision(500, "SEO et croissance pour les startups", "Julien", True)
    assert ok, "whitelisted seed must bypass the language gate"


def test_an_unreadable_quality_reject_cache_reads_empty_and_is_replaced(tmp_path):
    path = tmp_path / "follow_quality_rejects.json"
    path.write_text('{"half')
    assert not fp._quality_reject_recent("SmallAccount")
    fp._record_quality_reject("SmallAccount")
    assert fp._quality_reject_recent("smallaccount")
    assert list(json.loads(path.read_text())) == ["smallaccount"]


SMALL = {"followers": "12", "bio": "dogs", "name": "x"}


def test_a_profile_rejected_by_the_gate_is_refused_before_the_next_visit(follow_env, monkeypatch,
                                                                        tmp_path):
    """The gate's reject is a quality refusal on the profile, then a
    quality refusal before the profile opens, for 30 days."""
    _counts(monkeypatch, tmp_path, 100, 10)
    monkeypatch.setattr(config, "FOLLOW_WHITELIST_ONLY", False)
    assert fp.judge("smallaccount") == ADMITTED

    verdict = fp.judge_profile("SmallAccount", lambda: SMALL)

    assert verdict.refusal is Refusal.QUALITY_REJECTED and "too small" in verdict.reason
    assert fp.judge("SmallAccount") == Verdict(
        Refusal.QUALITY_REJECTED, "rejected by the quality gate within 30 days")


def test_the_gate_admits_a_seed_and_skips_size_for_an_engager(follow_env):
    assert fp.judge_profile("karpathy", lambda: SMALL) == ADMITTED
    assert fp.judge_profile("smallfan", lambda: {"followers": "12", "bio": "hi", "name": "Sam"},
                            engager=True) == ADMITTED
    assert not fp._quality_reject_recent("smallfan")


def test_the_gate_reads_no_profile_while_the_whitelist_is_unreadable(tmp_path):
    (tmp_path / "whitelist.json").write_text('{"tiers": {"tier1": ["karp')

    verdict = fp.judge_profile("someone", lambda: pytest.fail("profile read"))

    assert verdict.refusal is Refusal.POLICY and "whitelist unreadable" in verdict.reason
    assert not (tmp_path / "follow_quality_rejects.json").exists()


# --- the followed accounts ------------------------------------------------------


def test_the_followed_accounts_merge_every_record(tmp_path):
    (tmp_path / "followed_accounts.json").write_text(json.dumps(["Earlier"]))
    fp.record_followed("fromengage")
    fp.record_followed("fromfollowback")
    fp.record_followed("fromengage")
    assert fp.followed() == {"Earlier", "fromengage", "fromfollowback"}


def test_an_unreadable_record_of_the_followed_accounts_is_never_overwritten(tmp_path):
    """record_followed runs after a follow shipped: it must not raise past
    it, and the guarded file waits for the Operator."""
    from src.core.state_errors import StateUnreadable
    path = tmp_path / "followed_accounts.json"
    path.write_text('["half')

    fp.record_followed("someone")

    assert path.read_text() == '["half'
    with pytest.raises(StateUnreadable):
        fp.followed()
