"""Pin-best-tweet bot — auto-pin our highest-engagement own POST.

Why this matters: a strong pinned tweet is the #1 leverage point on
follow-conversion. Every visitor sees it first; if it's a banger, they
follow. If it's stale, they bounce. We post a lot — the pinned slot
should rotate to whatever is currently working.

Strategy:
  - Once per day, scrape /TheAIShrink (main feed, posts only — NOT
    /with_replies which mixes replies in).
  - Pick the post with the highest like count from the last ~30 tweets
    (the visible profile window).
  - Skip if already pinned (track via pin_history.json).
  - Pin via twitter_client.pin_own_tweet (best-effort JS menu click), which
    writes the ledger row. A dry run marks its own day and does not spend
    the live attempt.
"""
import os
import time
import traceback
from datetime import date

from ..core import config
from ..core.config import BOT_HANDLE
from ..core.logger import log
from ..core.state_store import GUARDED, StateFile
from ..guards import active_hours
from ..x.scraper import scrape_profile_tweets, is_own_post
from ..x import twitter_client
from ..x.confirmed_write import WriteOutcome

# Guarded: they alone hold one attempt per day and the posts already pinned.
PIN_HISTORY = StateFile("pin_history.json", {"pinned": []}, GUARDED)
PIN_STATE = StateFile("pin_daily_state.json", {}, GUARDED)

# Minimum likes to bother pinning. If the best post of the week didn't
# clear this floor, the pinned slot is more honest staying empty.
# 2 (was 5, 2026-07-19): we self-like at publish, so 2 = 1 external like.
# A floor of 5 froze the slot for weeks at this account size.
MIN_LIKES_TO_PIN = int(os.environ.get("PIN_MIN_LIKES", "2"))


def _load_history() -> dict:
    return PIN_HISTORY.read()


def _save_history(h: dict):
    # Cap history to last 30 pin URLs so the file doesn't grow unbounded.
    h["pinned"] = h.get("pinned", [])[-30:]
    PIN_HISTORY.write(h)


def _load_state() -> dict:
    return PIN_STATE.read()


def _day_key() -> str:
    # A dry run keeps its own day: it never spends the live attempt, and it
    # does not scrape the profile again every hour either.
    return "dry_run_date" if config.dry_run() else "date"


def _already_ran_today() -> bool:
    today = active_hours.now_local().date().isoformat()
    ran = _load_state().get(_day_key()) or ""
    if ran > today:
        # Stamped today by the Mac's clock, ahead of Toronto's: restamp it,
        # or tomorrow would read it as already spent.
        _mark_ran_today()
    return ran >= today


def _mark_ran_today():
    state = _load_state()
    state[_day_key()] = active_hours.now_local().date().isoformat()
    PIN_STATE.write(state)


def run_pin_cycle():
    """Pick the top own post of the recent window and pin it."""
    if _already_ran_today():
        log.info(f"[PIN] Already attempted today{' (dry run)' if config.dry_run() else ''}. Skipping.")
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
    # 2026-07-19 (4th hit of the display-name-vs-handle family): the scraper's
    # `author` is the DISPLAY NAME ("The AI Therapist"), never the @handle, so
    # comparing it to BOT_HANDLE filtered EVERY candidate — the pin could
    # never rotate. URL is ground truth: is_own_post().
    own = []
    for t in tweets:
        url = t.get("url") or ""
        if not url or not is_own_post(t):
            continue
        if url in pinned_urls:
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

    # 2026-06-06 operator policy: the pin changes AT MOST once per 24h
    # (the daily state above guarantees that), must be an IMPACTFUL/VIRAL
    # post, and we ALWAYS keep a pin — never downgrade. A candidate only
    # replaces the current pin when it meaningfully beats the engagement
    # the current pin had when it was pinned (1.3x), or there is no
    # recorded pin yet. (Décode-series preference removed with the brand.)
    best = max(own, key=lambda c: (c["likes"], c["replies"]))
    last = history.get("last_pin", {})
    last_likes = int(last.get("likes") or 0)
    # Staleness override (2026-07-19): a pin older than PIN_MAX_AGE_DAYS no
    # longer defends its slot with the 1.3x beat rule — a fresh good post
    # converts profile visits better than a stale banger.
    max_age_days = int(os.environ.get("PIN_MAX_AGE_DAYS", "7"))
    pinned_at = last.get("pinned_at") or ""
    pin_is_stale = True
    if pinned_at:
        try:
            pin_is_stale = (active_hours.now_local().date() - date.fromisoformat(pinned_at[:10])).days >= max_age_days
        except ValueError:
            pin_is_stale = True
    if last_likes and not pin_is_stale and             best["likes"] < max(MIN_LIKES_TO_PIN, int(last_likes * 1.3)):
        log.info(
            f"[PIN] Best candidate ({best['likes']} likes) doesn't beat the "
            f"current pin ({last_likes} likes x1.3) — keeping the existing pin."
        )
        _mark_ran_today()
        return
    log.info(
        f"[PIN] Best post: {best['likes']} likes / {best['replies']} replies — "
        f"{best['text'][:120]!r}"
    )

    # Best-effort pin. The JS menu-click is fragile; if it fails we log and move on.
    try:
        ok = twitter_client.pin_own_tweet(best["url"])
    except Exception:
        log.info("[PIN] pin_own_tweet raised:")
        traceback.print_exc()
        ok = False

    _mark_ran_today()
    if ok is WriteOutcome.DRY_RUN:
        log.info("[PIN][DRY_RUN] Dry-run pin recorded; the live attempt is not spent.")
        return

    if ok:
        history.setdefault("pinned", []).append(best["url"])
        history["last_pin"] = {"url": best["url"], "likes": best["likes"],
                               "pinned_at": active_hours.now_local().date().isoformat()}
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
    from ..core import health
    try:
        run_pin_cycle()
        health.record_success("pin")
    except Exception:
        log.info("[PIN] Error during pin cycle:")
        traceback.print_exc()
        health.record_failure("pin")
