"""Promote-best-reply bot — repost our highest-engagement reply.

Replies are the bot's working surface (consistent likes + comments). But
they live INSIDE someone else's thread — invisible to followers scrolling
their timeline. Solution: once a reply hits a meaningful like count,
plain-repost it so it gets another feed pass. Same content, different
distribution surface.

Strategy:
  - Once every ~3h. Visit /CryptoAIDecode/with_replies, scrape recent replies +
    their like counts.
  - Filter: must be authored by @CryptoAIDecode, must have ≥ MIN_LIKES.
  - Skip if already promoted (persistent dedup in promoted_replies.json).
  - Plain-repost the top candidate.
  - Cap 3/day so we don't feel mechanical.

Different from quote_tweet_bot (which reposts external tweets):
this reposts OUR OWN replies that already proved they land.
"""
import json
import os
import random
import time
import traceback
from datetime import date, datetime

from .config import _PROJECT_ROOT, BOT_HANDLE, BLOCKLIST
from .logger import log
from .twitter_client import scrape_profile_tweets, retweet_post
from .engagement_log import log_reply

PROMOTED_FILE = os.path.join(_PROJECT_ROOT, "promoted_replies.json")
PROMOTE_STATE_FILE = os.path.join(_PROJECT_ROOT, "promote_daily_state.json")

MAX_PROMOTES_PER_DAY = int(os.environ.get("MAX_PROMOTES_PER_DAY", "3"))
MIN_LIKES = int(os.environ.get("PROMOTE_MIN_LIKES", "5"))

_OWN_HANDLE = BOT_HANDLE.lower()

# Kept only for older state/log context. Promote now uses plain reposts.
META_COMMENTS = [
    "Pour ceux qui scrollent trop vite.",
    "Repost pour ceux du fond.",
    "Je le redis parce que personne n'a réagi assez fort.",
    "Pour la postérité.",
    "Au cas où vous l'auriez raté.",
    "Mention spéciale.",
    "On a beaucoup ri ce matin.",
    "Le dimanche c'est rediffusion.",
    "Petit rappel.",
    "Toujours d'actualité.",
]


def _load_promoted() -> set:
    if os.path.exists(PROMOTED_FILE):
        try:
            with open(PROMOTED_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def _save_promoted(s: set):
    with open(PROMOTED_FILE, "w") as f:
        json.dump(list(s)[-500:], f)


def _today_count() -> int:
    if not os.path.exists(PROMOTE_STATE_FILE):
        return 0
    try:
        with open(PROMOTE_STATE_FILE, "r") as f:
            state = json.load(f)
    except (json.JSONDecodeError, IOError):
        return 0
    if state.get("date") != date.today().isoformat():
        return 0
    return int(state.get("count", 0))


def _increment_count():
    today = date.today().isoformat()
    state = {"date": today, "count": 0}
    if os.path.exists(PROMOTE_STATE_FILE):
        try:
            with open(PROMOTE_STATE_FILE, "r") as f:
                prev = json.load(f)
            if prev.get("date") == today:
                state = prev
        except (json.JSONDecodeError, IOError):
            pass
    state["count"] = int(state.get("count", 0)) + 1
    with open(PROMOTE_STATE_FILE, "w") as f:
        json.dump(state, f)


def run_promote_cycle():
    """Find our top recent reply and plain-repost it."""
    if _today_count() >= MAX_PROMOTES_PER_DAY:
        log.info(f"[PROMOTE] Daily cap reached ({MAX_PROMOTES_PER_DAY}). Skipping.")
        return

    promoted = _load_promoted()

    # /with_replies shows our recent replies as standalone tweets with metrics.
    # Hack: scrape_profile_tweets concatenates "https://x.com/" + arg, so we
    # can pass "CryptoAIDecode/with_replies" to land on the right page.
    log.info(f"[PROMOTE] Scraping @{BOT_HANDLE}/with_replies for top recent replies...")
    try:
        tweets = scrape_profile_tweets(f"{BOT_HANDLE}/with_replies", max_tweets=20)
    except Exception:
        log.info("[PROMOTE] Scrape failed:")
        traceback.print_exc()
        return

    if not tweets:
        log.info("[PROMOTE] No tweets scraped from /with_replies.")
        return

    # Keep only replies authored by us, with enough likes, and not already promoted.
    candidates = []
    for t in tweets:
        author = (t.get("author") or "").lower().lstrip("@")
        if author != _OWN_HANDLE:
            continue
        url = t.get("url") or ""
        if not url or url in promoted:
            continue
        likes = int(t.get("likes") or 0)
        text = (t.get("text") or "").strip()
        if likes < MIN_LIKES:
            continue
        if not text:
            continue
        # Skip our own news/hot takes — they already live on the profile.
        # Heuristic: replies on /with_replies start at the top of the page,
        # but our own news posts also show there. Skip if text contains a
        # URL that's clearly an article (https://...).
        if "http" in text.lower() and len(text) > 200:
            continue
        candidates.append({
            "url": url,
            "text": text,
            "likes": likes,
            "replies": int(t.get("replies") or 0),
        })

    if not candidates:
        log.info(f"[PROMOTE] No candidates pass MIN_LIKES={MIN_LIKES} + dedup.")
        return

    # Pick the highest-engagement candidate.
    best = max(candidates, key=lambda c: (c["likes"], c["replies"]))
    log.info(
        f"[PROMOTE] Best reply: {best['likes']} likes / {best['replies']} replies — "
        f"{best['text'][:120]!r}"
    )

    # Lock URL in BEFORE posting so a crash can't double-promote.
    promoted.add(best["url"])
    _save_promoted(promoted)

    try:
        retweet_post(best["url"])
        _increment_count()
        try:
            log_reply(
                best["url"],
                f"[PROMOTE_RT] {best['text'][:150]}",
                action_type="retweet",
                source=f"PROMOTE/{BOT_HANDLE}",
            )
        except Exception:
            pass
        time.sleep(random.randint(5, 10))
        log.info(f"[PROMOTE] DONE. Today's count: {_today_count()}/{MAX_PROMOTES_PER_DAY}")
    except Exception:
        log.info("[PROMOTE] Posting failed:")
        traceback.print_exc()


def safe_run_promote_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_promote_cycle()
        health.record_success("promote")
    except Exception:
        log.info("[PROMOTE] Error during promote cycle:")
        traceback.print_exc()
        health.record_failure("promote")
