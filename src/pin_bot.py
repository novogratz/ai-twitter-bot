"""Pin-best-tweet bot — auto-pin our highest-engagement own POST.

Why this matters: a strong pinned tweet is the #1 leverage point on
follow-conversion. Every visitor sees it first; if it's a banger, they
follow. If it's stale, they bounce. We post a lot — the pinned slot
should rotate to whatever is currently working.

Strategy:
  - Once per day, scrape /kzer_ai (main feed, posts only — NOT
    /with_replies which mixes replies in).
  - Pick the post with the highest like count from the last ~30 tweets
    (the visible profile window).
  - Skip if already pinned (track via pin_history.json).
  - Pin via twitter_client.pin_own_tweet (best-effort JS menu click).
"""
import json
import os
import time
import traceback
from datetime import date

from .config import _PROJECT_ROOT, BOT_HANDLE
from .logger import log
from .twitter_client import scrape_profile_tweets, pin_own_tweet

PIN_HISTORY_FILE = os.path.join(_PROJECT_ROOT, "pin_history.json")
PIN_STATE_FILE = os.path.join(_PROJECT_ROOT, "pin_daily_state.json")

# Minimum likes to bother pinning. If the best post of the week didn't
# clear this floor, the pinned slot is more honest staying empty.
MIN_LIKES_TO_PIN = int(os.environ.get("PIN_MIN_LIKES", "5"))


def _load_history() -> dict:
    if os.path.exists(PIN_HISTORY_FILE):
        try:
            with open(PIN_HISTORY_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"pinned": []}


def _save_history(h: dict):
    with open(PIN_HISTORY_FILE, "w") as f:
        # Cap history to last 30 pin URLs so the file doesn't grow unbounded.
        h["pinned"] = h.get("pinned", [])[-30:]
        json.dump(h, f, indent=2)


def _already_ran_today() -> bool:
    if not os.path.exists(PIN_STATE_FILE):
        return False
    try:
        with open(PIN_STATE_FILE, "r") as f:
            state = json.load(f)
    except (json.JSONDecodeError, IOError):
        return False
    return state.get("date") == date.today().isoformat()


def _mark_ran_today():
    with open(PIN_STATE_FILE, "w") as f:
        json.dump({"date": date.today().isoformat()}, f)


def run_pin_cycle():
    """Pick the top own post of the recent window and pin it."""
    if _already_ran_today():
        log.info("[PIN] Already attempted today. Skipping.")
        return

    history = _load_history()
    pinned_urls = set(history.get("pinned", []))

    log.info(f"[PIN] Scraping @{BOT_HANDLE} main feed for top own post...")
    try:
        tweets = scrape_profile_tweets(BOT_HANDLE, max_tweets=20)
    except Exception:
        log.info("[PIN] Scrape failed:")
        traceback.print_exc()
        return

    if not tweets:
        log.info("[PIN] No tweets scraped.")
        return

    # Filter: must be authored by us, not already-pinned, has minimum likes.
    own = []
    for t in tweets:
        author = (t.get("author") or "").lower().lstrip("@")
        if author and author != BOT_HANDLE.lower():
            continue
        url = t.get("url") or ""
        if not url or url in pinned_urls:
            continue
        likes = int(t.get("likes") or 0)
        if likes < MIN_LIKES_TO_PIN:
            continue
        own.append({
            "url": url,
            "likes": likes,
            "replies": int(t.get("replies") or 0),
            "text": (t.get("text") or "").strip(),
        })

    if not own:
        log.info(
            f"[PIN] No fresh own post clears MIN_LIKES_TO_PIN={MIN_LIKES_TO_PIN}. "
            "Skipping (better empty than stale)."
        )
        _mark_ran_today()
        return

    best = max(own, key=lambda c: (c["likes"], c["replies"]))
    log.info(
        f"[PIN] Best post: {best['likes']} likes / {best['replies']} replies — "
        f"{best['text'][:120]!r}"
    )

    # Best-effort pin. The JS menu-click is fragile; if it fails we log and move on.
    try:
        ok = pin_own_tweet(best["url"])
    except Exception:
        log.info("[PIN] pin_own_tweet raised:")
        traceback.print_exc()
        ok = False

    _mark_ran_today()

    if ok:
        history.setdefault("pinned", []).append(best["url"])
        _save_history(history)
        log.info(f"[PIN] Pinned: {best['url']}")
        time.sleep(2)
    else:
        log.info(
            "[PIN] Pin attempt did not confirm. (X menu DOM may have shifted; "
            "manual pin still works.)"
        )


def safe_run_pin_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_pin_cycle()
        health.record_success("pin")
    except Exception:
        log.info("[PIN] Error during pin cycle:")
        traceback.print_exc()
        health.record_failure("pin")
