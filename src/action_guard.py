"""Central write-action guard (2026-06-02 pivot).

Single chokepoint for rate-limits, daily caps, anti-churn and the follow
policy. Wired into the lowest-level write functions in twitter_client
(post_tweet / quote_tweet / reply_* / follow_account / unfollow_account /
like / retweet) so every caller — whichever of the ~30 bots — is governed by
the same rules without rewriting each bot.

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

from . import config
from .logger import log

_LOCK = threading.Lock()

# Action types
POST = "post"
QUOTE = "quote"
REPLY = "reply"
FOLLOW = "follow"
UNFOLLOW = "unfollow"
LIKE = "like"
RETWEET = "retweet"


# --- ledger ----------------------------------------------------------------

def _load_ledger() -> list:
    try:
        with open(config.ACTION_LEDGER_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_ledger(rows: list) -> None:
    # Keep the file bounded — 90 days is plenty for a 30-day cooldown + audit.
    cutoff = (datetime.now() - timedelta(days=90)).isoformat()
    rows = [r for r in rows if r.get("ts", "") >= cutoff]
    tmp = config.ACTION_LEDGER_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(rows, f)
        os.replace(tmp, config.ACTION_LEDGER_FILE)
    except OSError:
        pass


def record(action: str, target: str = "", dry_run: bool = False) -> None:
    """Append an action to the ledger (thread-safe)."""
    with _LOCK:
        rows = _load_ledger()
        rows.append({
            "action": action,
            "target": (target or "").lower().lstrip("@"),
            "ts": datetime.now().isoformat(),
            "dry_run": bool(dry_run),
        })
        _save_ledger(rows)


def _rows_for_action_today(action: str) -> list:
    today = datetime.now().date().isoformat()
    return [r for r in _load_ledger()
            if r.get("action") == action and r.get("ts", "")[:10] == today]


def count_today(action: str) -> int:
    return len(_rows_for_action_today(action))


def seconds_since_last(action: str) -> float:
    rows = [r for r in _load_ledger() if r.get("action") == action]
    if not rows:
        return float("inf")
    last = max(r.get("ts", "") for r in rows)
    try:
        return (datetime.now() - datetime.fromisoformat(last)).total_seconds()
    except ValueError:
        return float("inf")


def last_touch(target: str) -> Optional[datetime]:
    """Most recent follow OR unfollow timestamp for an account (anti-churn)."""
    t = (target or "").lower().lstrip("@")
    stamps = [r.get("ts", "") for r in _load_ledger()
              if r.get("target") == t and r.get("action") in (FOLLOW, UNFOLLOW)]
    if not stamps:
        return None
    try:
        return datetime.fromisoformat(max(stamps))
    except ValueError:
        return None


def within_churn_cooldown(target: str) -> bool:
    last = last_touch(target)
    if last is None:
        return False
    return (datetime.now() - last) < timedelta(days=config.CHURN_COOLDOWN_DAYS)


# --- pacing -----------------------------------------------------------------

def jitter_sleep(max_seconds: int) -> None:
    """Sleep a random 0..max_seconds so writes never burst. No-op in dry-run."""
    if config.DRY_RUN or max_seconds <= 0:
        return
    time.sleep(random.uniform(0, max_seconds))


def spacing_ok(action: str, min_seconds: int) -> bool:
    return seconds_since_last(action) >= min_seconds


# --- whitelist --------------------------------------------------------------

_WL_CACHE: dict = {}
_WL_MTIME: float = 0.0


def load_whitelist() -> dict:
    """Return {"tier1": set, "tier2": set, "tier3": set, "all": set} of
    lowercased handles. Cached, reloads when the file changes."""
    global _WL_CACHE, _WL_MTIME
    try:
        mtime = os.path.getmtime(config.WHITELIST_FILE)
    except OSError:
        return {"tier1": set(), "tier2": set(), "tier3": set(), "all": set()}
    if _WL_CACHE and mtime == _WL_MTIME:
        return _WL_CACHE
    try:
        with open(config.WHITELIST_FILE) as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"tier1": set(), "tier2": set(), "tier3": set(), "all": set()}

    def _norm(seq):
        return {str(h).lower().lstrip("@") for h in (seq or [])}

    tiers = raw.get("tiers", raw)  # tolerate flat or nested shape
    t1 = _norm(tiers.get("tier1") or tiers.get("tier1_sources_targets"))
    t2 = _norm(tiers.get("tier2") or tiers.get("tier2_peers"))
    t3 = _norm(tiers.get("tier3") or tiers.get("tier3_watch"))
    _WL_CACHE = {"tier1": t1, "tier2": t2, "tier3": t3, "all": t1 | t2 | t3}
    _WL_MTIME = mtime
    return _WL_CACHE


def is_whitelisted(handle: str, tiers=("tier1", "tier2", "tier3")) -> bool:
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
    if config.DRY_RUN:
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

def can_follow(handle: str) -> Tuple[bool, str]:
    """Daily cap + anti-churn + (optional) whitelist + net-negative ratio rule.

    Hybrid policy (2026-06-02): we follow new accounts for growth, but while
    following is OVER the ceiling we only allow a follow when the day is still
    net-negative (today's follows < today's unfollows) — so the ratio heals
    every day even as we keep discovering people. Under the ceiling, follows
    are free up to the daily cap.
    """
    h = (handle or "").lower().lstrip("@")
    if not h:
        return (False, "empty handle")
    if config.FOLLOW_WHITELIST_ONLY and not is_whitelisted(h):
        return (False, "not on whitelist (whitelist-only mode; no strangers, no reciprocity)")
    if within_churn_cooldown(h):
        return (False, f"anti-churn: touched within {config.CHURN_COOLDOWN_DAYS}d")
    follows_today = count_today(FOLLOW)
    if follows_today >= config.MAX_FOLLOWS_PER_DAY:
        return (False, f"daily follow cap reached ({config.MAX_FOLLOWS_PER_DAY})")
    # Ratio brake is OFF by default in growth mode (it was blocking 100% of
    # follows at 4200 following). Only enforce when FOLLOW_ENFORCE_RATIO=1.
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
    """Daily cap, anti-churn cooldown; never unfollow a tier1/tier2 account."""
    h = (handle or "").lower().lstrip("@")
    if not h:
        return (False, "empty handle")
    if is_whitelisted(h, tiers=("tier1", "tier2")):
        return (False, "protected: tier1/tier2 whitelist account")
    if within_churn_cooldown(h):
        return (False, f"anti-churn: touched within {config.CHURN_COOLDOWN_DAYS}d")
    if count_today(UNFOLLOW) >= config.MAX_UNFOLLOWS_PER_DAY:
        return (False, f"daily unfollow cap reached ({config.MAX_UNFOLLOWS_PER_DAY})")
    return (True, "")


def can_post(action: str) -> Tuple[bool, str]:
    """Daily cap + jittered min-spacing for originals / quotes / replies.

    Jitter is folded into the required gap (NOT a blocking sleep) so we never
    stall a scheduler thread for the 45-min post spacing: each call requires
    base_gap + random(0, jitter) seconds since the last same-type action, so
    spacing is randomized and writes never line up into a burst.
    """
    if action == POST:
        cap = config.MAX_ORIGINALS_PER_DAY
        gap = config.MIN_SECONDS_BETWEEN_POSTS + random.uniform(0, config.POST_JITTER_SECONDS)
    elif action == QUOTE:
        cap = config.MAX_QUOTE_REPOSTS_PER_DAY
        gap = config.MIN_SECONDS_BETWEEN_QUOTES + random.uniform(0, config.QUOTE_JITTER_SECONDS)
    elif action == REPLY:
        cap = config.MAX_REPLIES_PER_DAY
        gap = config.MIN_SECONDS_BETWEEN_REPLIES + random.uniform(0, config.REPLY_JITTER_SECONDS)
    else:
        return (True, "")
    if count_today(action) >= cap:
        return (False, f"daily {action} cap reached ({cap})")
    if not spacing_ok(action, gap):
        return (False, f"too soon since last {action} (need ~{int(gap)}s gap)")
    return (True, "")
