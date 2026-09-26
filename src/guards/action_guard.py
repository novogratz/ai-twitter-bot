"""Central write-action guard (2026-06-02 pivot).

Single chokepoint for rate-limits, daily caps and anti-churn. Wired into
the lowest-level write functions in twitter_client (post_tweet /
reply_to_tweet, and follow_account through `follow_policy`, which asks it
for today's follows, the follow spacing and the last touch of a handle) so
every caller — whichever of the ~30 bots — is governed by the same rules
without rewriting each bot. Likes and pins are recorded in the ledger, not
governed: no cap or spacing applies to them here.

This bot is Safari/AppleScript driven (no X API), so "respect API rate limits
/ back off on 429" maps to Safari write-pacing: per-action daily caps, a
minimum interval between same-type actions, and randomized jitter so writes
never burst. Same intent, different mechanism.

Every executed (or dry-run) write is recorded in the action ledger
(`src/guards/ledger.py`) as {action, target, ts}; an Original's target is
the Pending slot it was reserved under, if any, so `original_refusal`
counts it once. The policy asks the ledger for today's counts, the last
write of an action and the last follow or unfollow of a handle, and never
knows where it stores them.
"""
import os
import random
import time
from datetime import timedelta
from typing import Optional, Tuple

from ..core import config, settings
from .active_hours import is_active, now_local, stop_requested, window_label
from .ledger import Ledger, file_ledger
# Action types, named by callers as action_guard.POST, action_guard.PIN...
from .ledger import DEBATE_TURN, FOLLOW, LIKE, PIN, POST, QUOTE, REPLY, RETWEET, UNFOLLOW

# --- ledger ----------------------------------------------------------------

# The ledger the policy asks. None stands for the file at
# config.ACTION_LEDGER_FILE, resolved at each call; tests set a MemoryLedger.
LEDGER: Optional[Ledger] = None


def _ledger() -> Ledger:
    return LEDGER if LEDGER is not None else file_ledger(os.fspath(config.ACTION_LEDGER_FILE))


def record(action: str, target: str = "", dry_run: bool = False) -> None:
    """Append an action to the ledger (thread-safe)."""
    _ledger().append(action, target, dry_run, now_local())


def count_today(action: str) -> int:
    """Shipped writes of `action` on the Toronto day, dry runs excluded."""
    return _ledger().count(action, now_local().date())


def profile_count_today() -> int:
    return sum(count_today(action) for action in (POST, QUOTE, RETWEET))


def debate_turn_authors() -> list:
    """Every author answered by a Debate turn in the ledger's 90 days,
    newest first: the Engagers the account conversed with."""
    return _ledger().targets(DEBATE_TURN)


def can_debate_turn(author: str) -> Tuple[bool, str]:
    """Per-author daily cap on Debate turns, shared by every answering bot."""
    if not (author or "").strip().lstrip("@"):
        return False, "debate turn without an author handle"
    cap = settings.get("DEBATE_MAX_TURNS_PER_AUTHOR_PER_DAY")
    if _ledger().count(DEBATE_TURN, now_local().date(), author) >= cap:
        return False, f"debate turn cap reached for @{author} ({cap}/day)"
    return True, ""


def _seconds_since_last(action: str) -> float:
    last = _ledger().last_write(action)
    return now_local().timestamp() - last.timestamp() if last else float("inf")


def within_churn_cooldown(target: str) -> bool:
    """True when `target` was followed or unfollowed, dry runs included,
    within CHURN_COOLDOWN_DAYS."""
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


def too_soon(action: str) -> str:
    """Why the spacing refuses the next write of `action`, "" when clear."""
    gap = _spacing_gap(action)
    if _seconds_since_last(action) < gap:
        return f"too soon since last {action} (need ~{int(gap)}s gap)"
    return ""


# --- policy decisions -------------------------------------------------------

def original_refusal(journal, now, besides: Optional[str] = None) -> str:
    """Why the day's submissions forbid another Original at `now`, or "".

    `journal` is the Slot journal (`src/editorial/slot_journal.py`). An
    UNCONFIRMED submission writes no ledger row, so `can_post` never sees
    it; the journal does. One count: the ledger's profile publications,
    plus the journal's submissions of the day that no POST row names
    (pending ones, and Slots the Operator marked published after a check).
    A submission that shipped before a crash kept it from being confirmed
    has its row, so it counts once. The spacing runs from the latest
    pending or published submission. `besides`, the Pending slot of the
    submission being judged, counts for neither."""
    day = now.date()
    unnamed = [key for key in journal.submissions(day)
               if key != besides and not _ledger().count(POST, day, key)]
    used = profile_count_today() + len(unnamed)
    cap = config.posts_ceiling()
    if used >= cap:
        return f"daily ceiling reached with pending submissions ({used}/{cap})"
    last = journal.last_submission(besides)
    # The jitter's upper bound: every draw `_spacing_gap` can make is shorter.
    gap = config.MIN_SECONDS_BETWEEN_POSTS + config.POST_JITTER_SECONDS
    if last and (now - last).total_seconds() < gap:
        return f"too soon since the last submission (need ~{gap}s gap)"
    return ""


def can_post(action: str) -> Tuple[bool, str]:
    """Hard day budget and bedtime."""
    if stop_requested():
        return False, "stop requested"
    if not is_active():
        return False, f"asleep (active {window_label()})"
    if action in (QUOTE, RETWEET):
        return False, "automatic quote/repost cap is 0 (editorial originals only)"
    if action == POST:
        if profile_count_today() >= config.MAX_PROFILE_POSTS_PER_DAY:
            return False, f"daily profile publication cap reached ({config.MAX_PROFILE_POSTS_PER_DAY})"
        if count_today(POST) >= config.MAX_ORIGINALS_PER_DAY:
            return False, f"daily post cap reached ({config.MAX_ORIGINALS_PER_DAY})"
    elif action != REPLY:
        return True, ""
    # No daily reply limit; replies retain spacing and per-tweet dedup.
    why = too_soon(action)
    return (False, why) if why else (True, "")
