"""Self-RT recycler (operator mandate 2026-06-07 PM-3).

"When posts like this work — thousands of views and likes — abuse the
retweet of your own posts: first self-RT after 1h, then keep going:
unretweet, re-retweet, like the pin rotation."

Mechanics: a self-RT pushes the post back to the top of followers' feeds.
Undo+redo (twitter_client.reboost_tweet — one Safari session, toggle 't'
twice) makes it appear fresh AGAIN without ever leaving a gap. Done on a
WINNER every few hours, the post gets 3-5 feed appearances instead of one.

Discipline (so it reads as conviction, not spam):
  - Only WINNERS: own posts with >= BOOST_RECYCLE_MIN_LIKES likes.
  - First boost at age >= 1h (the organic algo push owns the first hour).
  - Re-cycles every >= BOOST_RECYCLE_GAP_HOURS, max BOOST_RECYCLE_MAX_CYCLES
    per post, nothing older than 48h (stale resurfacing looks desperate).
  - ONE action per cycle — calm cadence, jittered by the scheduler.

State invariant shared with notify_bot's boost engine: a URL present in
boost_history.json is CURRENTLY retweeted (the boost engine never un-RTs,
and reboost_tweet ends in the retweeted state). That tells us which
primitive to use: not-yet-RT'd winners get retweet_post(), already-RT'd
winners get reboost_tweet().
"""
import json
import os
import traceback
from datetime import datetime, timedelta

from .config import _PROJECT_ROOT, BOT_HANDLE
from .logger import log
from .twitter_client import is_own_post as _is_own_post

STATE_FILE = os.path.join(_PROJECT_ROOT, "boost_recycler_state.json")

# Operator 2026-06-07: "boost winners when you get at least 1 like from
# someone else within an hour." The bot self-likes every own post at publish
# time, so scraped likes >= 2 means >= 1 like from a real person.
BOOST_RECYCLE_MIN_LIKES = int(os.environ.get("BOOST_RECYCLE_MIN_LIKES", "2"))
BOOST_RECYCLE_GAP_HOURS = float(os.environ.get("BOOST_RECYCLE_GAP_HOURS", "4"))
BOOST_RECYCLE_MAX_CYCLES = int(os.environ.get("BOOST_RECYCLE_MAX_CYCLES", "4"))
BOOST_RECYCLE_MIN_AGE_MINUTES = int(os.environ.get("BOOST_RECYCLE_MIN_AGE_MINUTES", "60"))
BOOST_RECYCLE_MAX_AGE_HOURS = 48  # stale resurfacing reads desperate — hard


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    # Prune entries past the recycle window so the file stays small.
    cutoff = (datetime.now() - timedelta(hours=BOOST_RECYCLE_MAX_AGE_HOURS + 24)).isoformat()
    state = {u: v for u, v in state.items() if v.get("last", "") >= cutoff}
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass


def _age_minutes(url: str) -> int:
    from .reply_bot import _tweet_age_minutes
    return _tweet_age_minutes(url)


def pick_action(winners: list, state: dict, currently_retweeted: set, now=None):
    """Pure decision: (action, url) or (None, None).

    winners: [{url, likes}] own posts already filtered to >= likes floor.
    action: "boost" (first self-RT) or "recycle" (un-RT + re-RT).
    Preference: first-boost a new winner before re-cycling an old one —
    fresh winners are in their algo window; recycling is the long tail.
    """
    now = now or datetime.now()
    best_recycle = None
    for w in sorted(winners, key=lambda x: int(x.get("likes") or 0), reverse=True):
        url = w["url"]
        age_min = _age_minutes(url)
        if age_min < BOOST_RECYCLE_MIN_AGE_MINUTES:
            continue  # organic push owns the first hour
        if age_min > BOOST_RECYCLE_MAX_AGE_HOURS * 60:
            continue
        row = state.get(url)
        if url not in currently_retweeted and not row:
            return ("boost", url)  # first self-RT of a fresh winner
        boosts = int((row or {}).get("boosts", 0))
        if boosts >= BOOST_RECYCLE_MAX_CYCLES:
            continue
        last = (row or {}).get("last", "")
        try:
            last_dt = datetime.fromisoformat(last)
        except (ValueError, TypeError):
            last_dt = None
        if last_dt and (now - last_dt) < timedelta(hours=BOOST_RECYCLE_GAP_HOURS):
            continue
        if url in currently_retweeted and best_recycle is None:
            best_recycle = url
    if best_recycle:
        return ("recycle", best_recycle)
    return (None, None)


def run_boost_recycler_cycle() -> None:
    from .twitter_client import scrape_profile_tweets, retweet_post, reboost_tweet
    from .notify_bot import _load_boost_history, _save_boost_history

    try:
        tweets = scrape_profile_tweets(BOT_HANDLE, max_tweets=15) or []
    except Exception:
        log.info("[RECYCLER] Profile scrape failed:")
        traceback.print_exc()
        return

    bot_lc = BOT_HANDLE.lower()
    winners = []
    for t in tweets:
        # Ownership by URL — the scraper's `author` is the DISPLAY NAME,
        # not the handle; comparing it to BOT_HANDLE silently dropped every
        # own post (2026-06-07 banger bug). is_own_post is ground truth.
        if not _is_own_post(t):
            continue
        url = t.get("url") or ""
        likes = int(t.get("likes") or 0)
        if url and likes >= BOOST_RECYCLE_MIN_LIKES:
            winners.append({"url": url, "likes": likes})
    if not winners:
        log.info(f"[RECYCLER] No winners (>= {BOOST_RECYCLE_MIN_LIKES} likes) "
                 f"in the window — nothing to recycle.")
        return

    state = _load_state()
    boost_history = _load_boost_history()
    action, url = pick_action(winners, state, boost_history)
    if not action:
        log.info(f"[RECYCLER] {len(winners)} winner(s) but none actionable "
                 f"(gaps/caps) — holding.")
        return

    try:
        if action == "boost":
            log.info(f"[RECYCLER] First self-RT of winner: {url}")
            retweet_post(url)
            boost_history.add(url)
            _save_boost_history(boost_history)
        else:
            log.info(f"[RECYCLER] Recycling winner (un-RT → re-RT): {url}")
            reboost_tweet(url)
    except Exception:
        log.info(f"[RECYCLER] {action} failed:")
        traceback.print_exc()
        return
    row = state.setdefault(url, {"boosts": 0})
    row["boosts"] = int(row.get("boosts", 0)) + 1
    row["last"] = datetime.now().isoformat()
    _save_state(state)
    log.info(f"[RECYCLER] Done ({action}, cycle {row['boosts']}/"
             f"{BOOST_RECYCLE_MAX_CYCLES}).")


def safe_run_boost_recycler_cycle() -> None:
    from . import health
    try:
        run_boost_recycler_cycle()
        health.record_success("boost_recycler")
    except Exception:
        log.info("[RECYCLER] outer error:")
        traceback.print_exc()
        health.record_failure("boost_recycler")
