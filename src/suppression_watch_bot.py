"""Suppression watchdog — detect when X is throttling our reach.

Why: at high volume, X can shadowban accounts that look spammy.
Symptoms: posts that used to land 10+ likes suddenly land 0-1. If
we don't detect this, we keep posting volume → make the suppression
worse → death spiral.

Strategy:
  - Every hour, scrape last 20 own posts.
  - Compute avg likes for posts older than 90 min (fresh ones haven't
    had time to land yet) and posted in the last 12h.
  - If avg < SUPPRESSION_THRESHOLD likes → flag suppression.
  - On flag: write suppression_state.json with `paused_until` =
    now + 4h. The aggressive bots (spicy, breakout, follow_blast,
    spike) check this file and skip if paused. Replies + likes
    + follow-back stay active (relationship-driven, not flagged
    as spam by the algo).
  - When pause expires, resume normally. If suppression persists
    after the 4h cooldown, log + extend.

Recovery: best-effort — there's no public X API to confirm the ban,
so we use the engagement signal as a proxy.
"""
import json
import os
import time
import traceback
from datetime import datetime, timedelta

from .config import _PROJECT_ROOT, BOT_HANDLE
from .logger import log
from .twitter_client import scrape_profile_tweets

SUPPRESSION_STATE_FILE = os.path.join(_PROJECT_ROOT, "suppression_state.json")
SUPPRESSION_THRESHOLD = float(os.environ.get("SUPPRESSION_AVG_LIKES_FLOOR", "1.0"))
COOLDOWN_HOURS = int(os.environ.get("SUPPRESSION_COOLDOWN_H", "4"))


def _load_state() -> dict:
    if os.path.exists(SUPPRESSION_STATE_FILE):
        try:
            with open(SUPPRESSION_STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"paused_until": None, "last_avg": None, "last_check": None, "last_n": 0}


def _save_state(s: dict):
    with open(SUPPRESSION_STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


def is_paused() -> bool:
    """Public API: aggressive bots call this to check if they should skip."""
    s = _load_state()
    pu = s.get("paused_until")
    if not pu:
        return False
    try:
        until = datetime.fromisoformat(pu)
    except ValueError:
        return False
    return datetime.now() < until


def run_suppression_watch_cycle():
    """Scrape recent own posts, compute avg likes, flag/release suppression."""
    log.info(f"[SUPPRESSION] Scraping @{BOT_HANDLE} for engagement health check...")
    try:
        tweets = scrape_profile_tweets(BOT_HANDLE, max_tweets=20)
    except Exception:
        log.info("[SUPPRESSION] Scrape failed:")
        traceback.print_exc()
        return

    if not tweets:
        log.info("[SUPPRESSION] No tweets scraped; skipping check.")
        return

    # Filter: only OUR posts that have had >= 90 min to land likes.
    bot_lc = BOT_HANDLE.lower()
    seasoned = []
    for t in tweets:
        author = (t.get("author") or "").lower().lstrip("@")
        if author and author != bot_lc:
            continue
        # The scraper doesn't expose a precise timestamp — rely on order
        # (newest first) and skip top 3-4 to avoid penalizing fresh posts.
        seasoned.append(int(t.get("likes") or 0))

    if len(seasoned) <= 4:
        log.info("[SUPPRESSION] Not enough seasoned posts for a meaningful avg.")
        return

    seasoned = seasoned[3:]  # drop the freshest 3
    avg = sum(seasoned) / len(seasoned)
    state = _load_state()
    state["last_avg"] = round(avg, 2)
    state["last_check"] = datetime.now().isoformat()
    state["last_n"] = len(seasoned)

    if avg < SUPPRESSION_THRESHOLD:
        until = datetime.now() + timedelta(hours=COOLDOWN_HOURS)
        state["paused_until"] = until.isoformat()
        log.info(
            f"[SUPPRESSION] FLAGGED — avg likes {avg:.2f} on last "
            f"{len(seasoned)} seasoned posts < threshold "
            f"{SUPPRESSION_THRESHOLD}. Pausing aggressive bots until "
            f"{until.strftime('%H:%M %d-%m')}."
        )
    else:
        # Healthy — clear any prior pause.
        if state.get("paused_until"):
            log.info(
                f"[SUPPRESSION] Recovered — avg likes {avg:.2f} >= "
                f"{SUPPRESSION_THRESHOLD}. Resuming aggressive bots."
            )
        state["paused_until"] = None
        log.info(
            f"[SUPPRESSION] Healthy — avg likes {avg:.2f} on "
            f"{len(seasoned)} seasoned posts."
        )

    _save_state(state)


def safe_run_suppression_watch_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_suppression_watch_cycle()
        health.record_success("suppression_watch")
    except Exception:
        log.info("[SUPPRESSION] Error during suppression watch cycle:")
        traceback.print_exc()
        health.record_failure("suppression_watch")
