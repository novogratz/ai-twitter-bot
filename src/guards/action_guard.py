"""Central write-action guard (2026-06-02 pivot).

Single chokepoint for rate-limits, daily caps, anti-churn and the follow
policy. Wired into the lowest-level write functions in twitter_client
(post_tweet / reply_to_tweet / follow_account) so every
caller — whichever of the ~30 bots — is governed by the same rules without
rewriting each bot. Likes and pins are recorded in the ledger, not
governed: no cap or spacing applies to them here.

This bot is Safari/AppleScript driven (no X API), so "respect API rate limits
/ back off on 429" maps to Safari write-pacing: per-action daily caps, a
minimum interval between same-type actions, and randomized jitter so writes
never burst. Same intent, different mechanism.

Every executed (or dry-run) write is recorded in the action ledger
(`src/guards/ledger.py`) as {action, target, ts}. The policy asks the ledger
for today's counts, the last write of an action and the last follow or
unfollow of a handle, and never knows where it stores them.
"""
import os
import random
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

from ..core import config
from ..core.logger import log
from ..core.state_errors import StateUnreadable
from ..core.state_store import DISPOSABLE, GUARDED, StateFile
from .active_hours import is_active, now_local, stop_requested, window_label
from .ledger import Ledger, file_ledger
# Action types, named by callers as action_guard.POST, action_guard.PIN...
from .ledger import DEBATE_TURN, FOLLOW, LIKE, PIN, POST, QUOTE, REPLY, RETWEET, UNFOLLOW

# The follow ceiling's inputs, declared here once; the jobs that write them
# import them from here.
# Guarded: engage_job follows every pool handle missing from it, and the
# ceiling counts it when following_count.json holds no count.
FOLLOWED = StateFile("followed_accounts.json", [], GUARDED)
# Guarded: the ceiling's count; the followed list under-counts the real
# following, so falling back to it would admit follows past the ceiling.
FOLLOWING_COUNT = StateFile("following_count.json", {}, GUARDED)
# Disposable: growth samples, where a fresh sample matters more than the
# series; without them the ceiling takes its lowest value and the ratio
# brake refuses, so losing them never admits a follow.
FOLLOWER_HISTORY = StateFile("follower_history.json", [], DISPOSABLE)
# Guarded: the Operator's follow whitelist, which account_curator extends.
# Read as empty, it would unprotect every seed from an unfollow.
WHITELIST = StateFile("whitelist.json", {}, GUARDED)


# --- ledger ----------------------------------------------------------------

# The ledger the policy asks. None stands for the file at
# config.ACTION_LEDGER_FILE, resolved at each call; tests set a MemoryLedger.
LEDGER: Optional[Ledger] = None


def _ledger() -> Ledger:
    return LEDGER if LEDGER is not None else file_ledger(config.ACTION_LEDGER_FILE)


def record(action: str, target: str = "", dry_run: bool = False) -> None:
    """Append an action to the ledger (thread-safe)."""
    _ledger().append(action, target, dry_run, now_local())


def _count_today(action: str) -> int:
    return _ledger().count(action, now_local().date())


def profile_count_today() -> int:
    return sum(_count_today(action) for action in (POST, QUOTE, RETWEET))


def debate_turn_authors() -> list:
    """Every author answered by a Debate turn in the ledger's 90 days,
    newest first: the Engagers the account conversed with."""
    return _ledger().targets(DEBATE_TURN)


def can_debate_turn(author: str) -> Tuple[bool, str]:
    """Per-author daily cap on Debate turns, shared by every answering bot."""
    if not (author or "").strip().lstrip("@"):
        return False, "debate turn without an author handle"
    cap = int(os.environ.get("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "4"))
    if _ledger().count(DEBATE_TURN, now_local().date(), author) >= cap:
        return False, f"debate turn cap reached for @{author} ({cap}/day)"
    return True, ""


def _seconds_since_last(action: str) -> float:
    last = _ledger().last_write(action)
    return now_local().timestamp() - last.timestamp() if last else float("inf")


def _within_churn_cooldown(target: str) -> bool:
    last = _ledger().last_touch(target)
    if last is None:
        return False
    return (now_local() - last) < timedelta(days=config.CHURN_COOLDOWN_DAYS)


# --- pacing -----------------------------------------------------------------

def jitter_sleep(max_seconds: int) -> None:
    """Sleep a random 0..max_seconds so writes never burst. No-op in dry-run."""
    if config.dry_run() or max_seconds <= 0:
        return
    time.sleep(random.uniform(0, max_seconds))


# action -> (minimum gap, jitter) as config attribute names, read at call time.
_SPACING = {
    REPLY: ("MIN_SECONDS_BETWEEN_REPLIES", "REPLY_JITTER_SECONDS"),
    POST: ("MIN_SECONDS_BETWEEN_POSTS", "POST_JITTER_SECONDS"),
    FOLLOW: ("MIN_SECONDS_BETWEEN_FOLLOWS", "FOLLOW_SPACING_JITTER_SECONDS"),
}


def _spacing_gap(action: str) -> float:
    """The gap the next write of `action` needs after the previous one.

    The jitter is drawn once per previous write of that action, seeded on its
    ledger timestamp: every caller sees the same gap, so a job waiting it out
    is admitted when the wait ends, and retrying cannot fish for a small draw.
    """
    if action not in _SPACING:
        raise ValueError(f"no write spacing for {action!r}")
    base, jitter = (getattr(config, name) for name in _SPACING[action])
    last = _ledger().last_write(action)
    seed = f"{action}:{last.isoformat() if last else ''}"
    return base + random.Random(seed).uniform(0, jitter)


def seconds_until_allowed(action: str) -> float:
    """Seconds before `can_post(action)` stops refusing on spacing; 0 when
    the spacing is clear or nothing was written yet. Never more than one
    gap: a ledger row stamped in the future (clock set back, copied ledger)
    must not park a waiting job for hours; can_post still refuses it."""
    gap = _spacing_gap(action)
    return min(gap, max(0.0, gap - _seconds_since_last(action)))


# --- whitelist --------------------------------------------------------------

def load_whitelist() -> dict:
    """Return {"tier1": set, ..., "tier4": set, "all": set} of lowercased
    handles. tier4 (2026-06-07 spec: crypto/markets crossover seeds) is
    optional in the file. Raises StateUnreadable while whitelist.json
    cannot be read."""
    raw = WHITELIST.read()

    def _norm(seq):
        return {str(h).lower().lstrip("@") for h in (seq or [])}

    tiers = raw.get("tiers", raw)  # tolerate flat or nested shape
    t1 = _norm(tiers.get("tier1") or tiers.get("tier1_sources_targets"))
    t2 = _norm(tiers.get("tier2") or tiers.get("tier2_peers"))
    t3 = _norm(tiers.get("tier3") or tiers.get("tier3_watch"))
    t4 = _norm(tiers.get("tier4"))
    # "discovered" tier: curator-promoted handles (2026-06-07 operator grant
    # — the bot develops its own follow list). Same follow rights as seeds;
    # additions capped + logged in account_curator.
    t5 = _norm(tiers.get("discovered"))
    return {"tier1": t1, "tier2": t2, "tier3": t3, "tier4": t4,
            "discovered": t5, "all": t1 | t2 | t3 | t4 | t5}


def is_whitelisted(handle: str,
                   tiers=("tier1", "tier2", "tier3", "tier4", "discovered")) -> bool:
    """Raises StateUnreadable while whitelist.json cannot be read."""
    h = (handle or "").lower().lstrip("@")
    wl = load_whitelist()
    return any(h in wl[t] for t in tiers)


# --- follower / following counts (best-effort, conservative) ---------------

def _current_counts() -> Tuple[Optional[int], int]:
    """(followers, following). Followers from follower_history.json (latest),
    None when unknown. Following: the env override, else following_count.json,
    else the tracked followed set (which under-counts true following).
    Raises StateUnreadable when following_count.json or the followed set
    cannot be read.
    """
    followers = None
    hist = FOLLOWER_HISTORY.read()
    try:
        if hist:
            followers = int(hist[-1].get("count"))
    except (AttributeError, ValueError, TypeError):
        pass

    override = os.environ.get("FOLLOWING_COUNT_OVERRIDE")
    if override and override.isdigit():
        return followers, int(override)
    try:
        return followers, int(FOLLOWING_COUNT.read().get("count"))
    except (ValueError, TypeError):
        return followers, len(FOLLOWED.read())


def adjust_following(delta: int) -> None:
    """Keep the live following counter in sync after a real follow/unfollow.

    The ratio invariant needs the TRUE following count, which followed_accounts
    .json under-reports. We track it from a manually-seeded baseline and apply
    +1 per follow / -1 per unfollow so the gate reflects reality as the prune
    runs. A periodic profile scrape can overwrite count for an exact resync.
    """
    if config.dry_run():
        return

    def adjust(doc):
        cur = doc.get("count")
        if not isinstance(cur, int):
            return None  # no baseline set — don't fabricate one
        return {**doc, "count": max(0, cur + delta), "updated": datetime.now().isoformat()}
    # Runs after a shipped write: raising would hide it from the caller. The
    # file stays as it is, and can_follow refuses while it is unreadable.
    try:
        FOLLOWING_COUNT.update(adjust)
    except StateUnreadable as exc:
        log.error(f"[FOLLOW] following count not adjusted by {delta:+d}: {exc}")


# --- policy decisions -------------------------------------------------------

def _following_ceiling(followers: Optional[int]) -> int:
    """Max total following allowed right now (2026-06-07 spec, Part 1),
    given the latest follower count, None when unknown.

    Hard constraints, never violated: total following cap 300; while
    followers are low (< FOLLOW_LOW_PHASE_FOLLOWERS) stay under the credible
    ~150; once followers exceed that, keep following <= followers (still
    capped at 300).
    """
    # Growth mode (operator 2026-06-11: follows + followback back ON):
    # the ceiling is FOLLOW_TOTAL_CAP alone — the followers-tied bound
    # below would block every follow while the manual purge is mid-flight
    # (following > followers). Daily cap + spacing + anti-churn still apply.
    if config.FOLLOW_GROWTH_MODE:
        return config.FOLLOW_TOTAL_CAP
    if followers is None or followers < config.FOLLOW_LOW_PHASE_FOLLOWERS:
        return min(config.FOLLOW_TOTAL_CAP, config.FOLLOW_LOW_PHASE_CEILING)
    return min(config.FOLLOW_TOTAL_CAP, followers)


def can_follow(handle: str, reciprocal: bool = False) -> Tuple[bool, str]:
    """2026-06-07 spec follow policy — whitelist-only seed/discovery list,
    hard total-following ceiling (300 cap / ~150 while followers are low),
    20/day pacing with >=10-min randomized gaps, 30-day anti-churn.

    `reciprocal=True` (a follow-back of someone who already engages with us)
    bypasses ONLY the whitelist-only gate when FOLLOWBACK_BYPASS_WHITELIST is
    set — every other gate (churn, daily cap, spacing, ceiling) still applies.
    """
    h = (handle or "").lower().lstrip("@")
    if not h:
        return (False, "empty handle")
    # follow_account's quality gate reads the whitelist too: an unreadable
    # one admits no follow, whitelist-only mode or not.
    try:
        whitelisted = is_whitelisted(h)
    except StateUnreadable as exc:
        return (False, f"whitelist unreadable ({exc})")
    _wl_exempt = reciprocal and config.FOLLOWBACK_BYPASS_WHITELIST
    if config.FOLLOW_WHITELIST_ONLY and not whitelisted and not _wl_exempt:
        return (False, "not on whitelist (whitelist-only mode; no strangers, no reciprocity)")
    if _within_churn_cooldown(h):
        return (False, f"anti-churn: touched within {config.CHURN_COOLDOWN_DAYS}d")
    follows_today = _count_today(FOLLOW)
    if follows_today >= config.MAX_FOLLOWS_PER_DAY:
        return (False, f"daily follow cap reached ({config.MAX_FOLLOWS_PER_DAY})")
    # Never burst-follow: >=10-min jittered gap between follows (spec Part 1).
    gap = _spacing_gap(FOLLOW)
    if _seconds_since_last(FOLLOW) < gap:
        return (False, f"too soon since last follow (need ~{int(gap)}s gap)")
    # Hard total-following ceiling — never exceed 300; ~150 while followers
    # are low; following <= followers once followers pass the low phase.
    # A ceiling that cannot be read admits no follow.
    try:
        followers, following = _current_counts()
    except StateUnreadable as exc:
        return (False, f"following ceiling unreadable ({exc})")
    ceiling = _following_ceiling(followers)
    if following + 1 > ceiling:
        return (False, f"total following ceiling reached ({following} >= {ceiling})")
    # Legacy net-negative ratio brake (kept behind FOLLOW_ENFORCE_RATIO).
    if config.FOLLOW_ENFORCE_RATIO:
        if followers is None:
            return (False, "follower count unknown: ratio brake cannot be checked")
        over_ceiling = (following + 1) > config.FOLLOW_RATIO_CEILING * followers
        if over_ceiling and follows_today >= _count_today(UNFOLLOW):
            return (False, f"over ratio ceiling (following {following} vs "
                           f"{config.FOLLOW_RATIO_CEILING}*{followers}); day not net-negative "
                           f"(follows {follows_today} >= unfollows {_count_today(UNFOLLOW)})")
    return (True, "")


def can_post(action: str, high_value: bool = False, urgent: bool = False) -> Tuple[bool, str]:
    """Hard day budget and bedtime; legacy urgency flags grant no bypass."""
    if stop_requested():
        return False, "stop requested"
    if not is_active():
        return False, f"asleep (active {window_label()})"
    if action in (QUOTE, RETWEET):
        return False, "automatic quote/repost cap is 0 (editorial originals only)"
    if action == POST:
        if profile_count_today() >= config.MAX_PROFILE_POSTS_PER_DAY:
            return False, f"daily profile publication cap reached ({config.MAX_PROFILE_POSTS_PER_DAY})"
        if _count_today(POST) >= config.MAX_ORIGINALS_PER_DAY:
            return False, f"daily post cap reached ({config.MAX_ORIGINALS_PER_DAY})"
    elif action != REPLY:
        return True, ""
    # No daily reply limit; replies retain spacing and per-tweet dedup.
    gap = _spacing_gap(action)
    if _seconds_since_last(action) < gap:
        return False, f"too soon since last {action} (need ~{int(gap)}s gap)"
    return True, ""
