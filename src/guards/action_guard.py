"""Central write-action guard (2026-06-02 pivot).

Single chokepoint for rate-limits, daily caps, anti-churn and the follow
policy. Wired into the lowest-level write functions in twitter_client
(post_tweet / reply_* / follow_account / unfollow_account / like) so every
caller — whichever of the ~30 bots — is governed by the same rules without
rewriting each bot.

This bot is Safari/AppleScript driven (no X API), so "respect API rate limits
/ back off on 429" maps to Safari write-pacing: per-action daily caps, a
minimum interval between same-type actions, and randomized jitter so writes
never burst. Same intent, different mechanism.

Persistent ledger (ACTION_LEDGER_FILE): every executed (or dry-run) write is
recorded as {action, target, ts}. Used for the 30-day follow/unfollow
anti-churn check and for auditing.
"""
import json
import os
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

from ..core import config
from ..core.logger import log
from .active_hours import is_active, now_local, stop_requested
from ..core.state_errors import StateUnreadable
from zoneinfo import ZoneInfo

_LOCK = threading.Lock()

# Action types
POST = "post"
QUOTE = "quote"
REPLY = "reply"
FOLLOW = "follow"
UNFOLLOW = "unfollow"
LIKE = "like"
RETWEET = "retweet"
# Bookkeeping row beside REPLY: the answered author, for the per-author cap.
DEBATE_TURN = "debate_turn"


# --- ledger ----------------------------------------------------------------

def _load_ledger() -> list:
    try:
        with open(config.ACTION_LEDGER_FILE) as f:
            data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("Action ledger must be a list")
            return data
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        raise StateUnreadable("Action ledger unreadable; refusing unaudited writes") from exc


def _save_ledger(rows: list) -> None:
    # Keep the file bounded — 90 days is plenty for a 30-day cooldown + audit.
    cutoff = (datetime.now() - timedelta(days=90)).isoformat()
    rows = [r for r in rows if r.get("ts", "") >= cutoff]
    tmp = config.ACTION_LEDGER_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(rows, f)
        os.replace(tmp, config.ACTION_LEDGER_FILE)
    except OSError as exc:
        raise StateUnreadable("Action ledger could not be saved") from exc


def record(action: str, target: str = "", dry_run: bool = False) -> None:
    """Append an action to the ledger (thread-safe)."""
    with _LOCK:
        rows = _load_ledger()
        rows.append({
            "action": action,
            "target": (target or "").lower().lstrip("@"),
            "ts": now_local().isoformat(),
            "dry_run": bool(dry_run),
        })
        _save_ledger(rows)


def _ledger_time(stamp: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(stamp)
        # Historical entries were recorded using the Toronto host's naive clock.
        return dt.replace(tzinfo=ZoneInfo(config.BOT_TIMEZONE)) if dt.tzinfo is None else dt
    except (ValueError, TypeError):
        return None


def _rows_for_action_today(action: str) -> list:
    today = now_local().date()
    return [r for r in _load_ledger()
            if r.get("action") == action and not r.get("dry_run")
            and (stamp := _ledger_time(r.get("ts", ""))) is not None
            and stamp.astimezone(ZoneInfo(config.BOT_TIMEZONE)).date() == today]


def count_today(action: str) -> int:
    return len(_rows_for_action_today(action))


def profile_count_today() -> int:
    return sum(count_today(action) for action in (POST, QUOTE, RETWEET))


def debate_turns_today(author: str) -> int:
    author = (author or "").lower().lstrip("@")
    return sum(1 for r in _rows_for_action_today(DEBATE_TURN) if r.get("target") == author)


def debate_turn_authors() -> list:
    """Every author answered by a Debate turn in the ledger's 90 days,
    newest first: the Engagers the account conversed with."""
    rows = [r for r in _load_ledger() if r.get("action") == DEBATE_TURN and not r.get("dry_run")]
    return list(dict.fromkeys(r["target"] for r in reversed(rows) if r.get("target")))


def can_debate_turn(author: str) -> Tuple[bool, str]:
    """Per-author daily cap on Debate turns, shared by every answering bot."""
    if not (author or "").strip().lstrip("@"):
        return False, "debate turn without an author handle"
    cap = int(os.environ.get("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY", "4"))
    if debate_turns_today(author) >= cap:
        return False, f"debate turn cap reached for @{author} ({cap}/day)"
    return True, ""


def seconds_since_last(action: str) -> float:
    stamps = [_ledger_time(r.get("ts", "")) for r in _load_ledger()
              if r.get("action") == action and not r.get("dry_run")]
    stamps = [stamp for stamp in stamps if stamp is not None]
    return now_local().timestamp() - max(s.timestamp() for s in stamps) if stamps else float("inf")


def last_touch(target: str) -> Optional[datetime]:
    """Most recent follow OR unfollow timestamp for an account (anti-churn)."""
    t = (target or "").lower().lstrip("@")
    stamps = [r.get("ts", "") for r in _load_ledger()
              if r.get("target") == t and r.get("action") in (FOLLOW, UNFOLLOW)]
    if not stamps:
        return None
    try:
        return _ledger_time(max(stamps))
    except ValueError:
        return None


def within_churn_cooldown(target: str) -> bool:
    last = last_touch(target)
    if last is None:
        return False
    return (now_local() - last) < timedelta(days=config.CHURN_COOLDOWN_DAYS)


# --- pacing -----------------------------------------------------------------

def jitter_sleep(max_seconds: int) -> None:
    """Sleep a random 0..max_seconds so writes never burst. No-op in dry-run."""
    if config.dry_run() or max_seconds <= 0:
        return
    time.sleep(random.uniform(0, max_seconds))


def spacing_ok(action: str, min_seconds: int) -> bool:
    return seconds_since_last(action) >= min_seconds


# --- whitelist --------------------------------------------------------------

_WL_CACHE: dict = {}
_WL_MTIME: float = 0.0


_WL_EMPTY = {"tier1": set(), "tier2": set(), "tier3": set(), "tier4": set(),
             "discovered": set(), "all": set()}


def load_whitelist() -> dict:
    """Return {"tier1": set, ..., "tier4": set, "all": set} of lowercased
    handles. Cached, reloads when the file changes. tier4 (2026-06-07 spec:
    crypto/markets crossover seeds) is optional in the file."""
    global _WL_CACHE, _WL_MTIME
    try:
        mtime = os.path.getmtime(config.WHITELIST_FILE)
    except OSError:
        return dict(_WL_EMPTY)
    if _WL_CACHE and mtime == _WL_MTIME:
        return _WL_CACHE
    try:
        with open(config.WHITELIST_FILE) as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(_WL_EMPTY)

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
    _WL_CACHE = {"tier1": t1, "tier2": t2, "tier3": t3, "tier4": t4,
                 "discovered": t5, "all": t1 | t2 | t3 | t4 | t5}
    _WL_MTIME = mtime
    return _WL_CACHE


def is_whitelisted(handle: str,
                   tiers=("tier1", "tier2", "tier3", "tier4", "discovered")) -> bool:
    h = (handle or "").lower().lstrip("@")
    wl = load_whitelist()
    return any(h in wl[t] for t in tiers)


# --- follower / following counts (best-effort, conservative) ---------------

def current_counts() -> Tuple[Optional[int], Optional[int]]:
    """(followers, following). Followers from follower_history.json (latest).
    Following: optional override file / env, else the tracked followed set
    (which under-counts true following, so the ratio gate stays conservative).
    """
    followers = None
    try:
        with open(os.path.join(config._PROJECT_ROOT, "follower_history.json")) as f:
            hist = json.load(f)
        if isinstance(hist, list) and hist:
            followers = int(hist[-1].get("count"))
    except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError):
        pass

    following = None
    override = os.environ.get("FOLLOWING_COUNT_OVERRIDE")
    if override and override.isdigit():
        following = int(override)
    else:
        try:
            with open(os.path.join(config._PROJECT_ROOT, "following_count.json")) as f:
                following = int(json.load(f).get("count"))
        except (OSError, json.JSONDecodeError, ValueError, TypeError, KeyError):
            try:
                with open(os.path.join(config._PROJECT_ROOT, "followed_accounts.json")) as f:
                    fa = json.load(f)
                following = len(fa) if isinstance(fa, (list, dict)) else None
            except (OSError, json.JSONDecodeError):
                following = None
    return followers, following


_FOLLOWING_COUNT_FILE = os.path.join(config._PROJECT_ROOT, "following_count.json")


def adjust_following(delta: int) -> None:
    """Keep the live following counter in sync after a real follow/unfollow.

    The ratio invariant needs the TRUE following count, which followed_accounts
    .json under-reports. We track it from a manually-seeded baseline and apply
    +1 per follow / -1 per unfollow so the gate reflects reality as the prune
    runs. A periodic profile scrape can overwrite count for an exact resync.
    """
    if config.dry_run():
        return
    with _LOCK:
        try:
            with open(_FOLLOWING_COUNT_FILE) as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            doc = {}
        cur = doc.get("count")
        if not isinstance(cur, int):
            return  # no baseline set — don't fabricate one
        doc["count"] = max(0, cur + delta)
        doc["updated"] = datetime.now().isoformat()
        try:
            with open(_FOLLOWING_COUNT_FILE, "w") as f:
                json.dump(doc, f)
        except OSError:
            pass


# --- policy decisions -------------------------------------------------------

def following_ceiling() -> int:
    """Max total following allowed right now (2026-06-07 spec, Part 1).

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
    followers, _ = current_counts()
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
    _wl_exempt = reciprocal and config.FOLLOWBACK_BYPASS_WHITELIST
    if config.FOLLOW_WHITELIST_ONLY and not is_whitelisted(h) and not _wl_exempt:
        return (False, "not on whitelist (whitelist-only mode; no strangers, no reciprocity)")
    if within_churn_cooldown(h):
        return (False, f"anti-churn: touched within {config.CHURN_COOLDOWN_DAYS}d")
    follows_today = count_today(FOLLOW)
    if follows_today >= config.MAX_FOLLOWS_PER_DAY:
        return (False, f"daily follow cap reached ({config.MAX_FOLLOWS_PER_DAY})")
    # Never burst-follow: >=10-min jittered gap between follows (spec Part 1).
    gap = config.MIN_SECONDS_BETWEEN_FOLLOWS + random.uniform(
        0, config.FOLLOW_SPACING_JITTER_SECONDS)
    if not spacing_ok(FOLLOW, gap):
        return (False, f"too soon since last follow (need ~{int(gap)}s gap)")
    # Hard total-following ceiling — never exceed 300; ~150 while followers
    # are low; following <= followers once followers pass the low phase.
    _, following = current_counts()
    if following is not None:
        ceiling = following_ceiling()
        if following + 1 > ceiling:
            return (False, f"total following ceiling reached ({following} >= {ceiling})")
    # Legacy net-negative ratio brake (kept behind FOLLOW_ENFORCE_RATIO).
    if config.FOLLOW_ENFORCE_RATIO:
        followers, following = current_counts()
        if followers is not None and following is not None:
            over_ceiling = (following + 1) > config.FOLLOW_RATIO_CEILING * followers
            if over_ceiling and follows_today >= count_today(UNFOLLOW):
                return (False, f"over ratio ceiling (following {following} vs "
                               f"{config.FOLLOW_RATIO_CEILING}*{followers}); day not net-negative "
                               f"(follows {follows_today} >= unfollows {count_today(UNFOLLOW)})")
    return (True, "")


def can_unfollow(handle: str) -> Tuple[bool, str]:
    """Daily cap, anti-churn cooldown; never unfollow ANY whitelisted seed
    (all tiers — the 2026-06-07 spec bans follow/unfollow churn on the
    curated list)."""
    h = (handle or "").lower().lstrip("@")
    if not h:
        return (False, "empty handle")
    if is_whitelisted(h):
        return (False, "protected: whitelisted seed account (all tiers)")
    if within_churn_cooldown(h):
        return (False, f"anti-churn: touched within {config.CHURN_COOLDOWN_DAYS}d")
    if count_today(UNFOLLOW) >= config.MAX_UNFOLLOWS_PER_DAY:
        return (False, f"daily unfollow cap reached ({config.MAX_UNFOLLOWS_PER_DAY})")
    return (True, "")


def can_post(action: str, high_value: bool = False, urgent: bool = False) -> Tuple[bool, str]:
    """Hard day budget and bedtime; legacy urgency flags grant no bypass."""
    if stop_requested():
        return False, "stop requested"
    if not is_active():
        return False, "asleep (active 04:30–22:00 America/Toronto)"
    if action in (QUOTE, RETWEET):
        return False, "automatic quote/repost cap is 0 (editorial originals only)"
    if action == POST:
        if profile_count_today() >= config.MAX_PROFILE_POSTS_PER_DAY:
            return False, "daily profile publication cap reached (7)"
        if count_today(POST) >= config.MAX_ORIGINALS_PER_DAY:
            return False, f"daily post cap reached ({config.MAX_ORIGINALS_PER_DAY})"
        gap = config.MIN_SECONDS_BETWEEN_POSTS + random.uniform(0, config.POST_JITTER_SECONDS)
    elif action == REPLY:
        # No daily reply limit; retain spacing and per-tweet dedup.
        gap = config.MIN_SECONDS_BETWEEN_REPLIES + random.uniform(0, config.REPLY_JITTER_SECONDS)
    else:
        return True, ""
    if not spacing_ok(action, gap):
        return False, f"too soon since last {action} (need ~{int(gap)}s gap)"
    return True, ""
