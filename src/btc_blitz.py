"""BTC Therapist bestie blitz (operator mandate 2026-06-07 PM).

"Be the best friend, the big sister of Bitcoin Therapist."

@TheBTCTherapist is the persona's foil AND its closest peer — the running
bit is the INVERSION: he treats Bitcoin trauma and suffers with his bags;
we treat AI-era portfolios and life is suspiciously great. His "working
the weekend because I bought Bitcoin instead of AI" → our "the AI side is
at the afterparty, private jet GIF". Always with love: big-brother
teasing he can quote back, never a dunk.

What the blitz does (startup + every 6h, fully idempotent):
  1. Scrape his profile, keep posts ≤48h old (the hard repost-age rule).
  2. REPLY to EVERY fresh post not yet replied to. One reply per tweet,
     EVER — the on-disk replied set + the chokepoint dedup make re-runs
     free, so "comment every single post of the past 48h" converges over
     cycles without ever double-commenting.
"""
import os
import traceback

from .config import REPLY_MODEL
from .direct_reply import (BESTIE_HANDLE, BESTIE_REPLY_PROMPT, BUDDY_REPLY_PROMPT,
                           generate_vip_reply)
from .logger import log
from .humanizer import humanize, smart_trim

BLITZ_MAX_AGE_MINUTES = 48 * 60  # ⛔ hard 48h rule — do not raise
BLITZ_SCRAPE_DEPTH = int(os.environ.get("BLITZ_SCRAPE_DEPTH", "30"))

# Operator mandate 2026-06-07 PM: "reply to everything graphseo and
# thebtctherapist post". Buddy handles get the reply-EVERY-post treatment
# (no QRT bit — that inversion is BTCTherapist-specific). Their profiles
# must be in twitter_client's PROFILE_VISIT_ALLOWLIST.
def _buddy_handles() -> list:
    raw = os.environ.get("BLITZ_BUDDY_HANDLES", "Graphseo")
    return [h.strip().lstrip("@") for h in raw.split(",") if h.strip()]


def _fresh_posts(handle: str):
    """A handle's posts ≤48h, own-authored, sorted most-liked first."""
    from .twitter_client import scrape_profile_tweets
    from .reply_bot import _tweet_age_minutes, _handle_from_url
    try:
        tweets = scrape_profile_tweets(handle, max_tweets=BLITZ_SCRAPE_DEPTH) or []
    except Exception:
        log.info(f"[BTC-BLITZ] profile scrape failed for @{handle}:")
        traceback.print_exc()
        return []
    fresh = []
    for t in tweets:
        url = t.get("url") or ""
        if not url:
            continue
        if _handle_from_url(url) != handle.lower():
            continue  # a repost of someone else on their profile
        if _tweet_age_minutes(url) > BLITZ_MAX_AGE_MINUTES:
            continue
        fresh.append(t)
    fresh.sort(key=lambda t: int(t.get("likes") or 0), reverse=True)
    return fresh


def _fresh_bestie_posts():
    return _fresh_posts(BESTIE_HANDLE)


def run_btc_blitz_cycle() -> None:
    fresh = _fresh_bestie_posts()
    if not fresh:
        # No early return — the buddy pass below must still run.
        log.info(f"[BTC-BLITZ] No fresh (≤48h) posts from @{BESTIE_HANDLE}.")
    else:
        log.info(f"[BTC-BLITZ] {len(fresh)} fresh posts from @{BESTIE_HANDLE} "
                 f"(top: {fresh[0].get('likes')} likes).")

    # --- 1. Reply to EVERY fresh post not yet replied -----------------------
    from .replied_store import load_replied
    from .twitter_client import reply_to_tweet
    from .engagement_log import log_reply
    replies_done = 0
    for t in fresh:
        url = t["url"]
        # Fresh disk read per candidate — re-runs and concurrent bots make
        # this set move; the chokepoint stays the final guard.
        if url in load_replied():
            continue
        reply = generate_vip_reply(BESTIE_REPLY_PROMPT, t.get("text", ""), REPLY_MODEL, "BTC_BLITZ_REPLY")
        if not reply:
            continue
        reply = smart_trim(humanize(reply), 278)
        try:
            if reply_to_tweet(url, reply):
                log_reply(url, reply, action_type="reply", source="BTC-BLITZ")
                replies_done += 1
        except Exception:
            traceback.print_exc()

    # --- 2. Buddy handles: reply to EVERY fresh post (no QRT bit) ----------
    # Operator 2026-06-07: "reply to everything graphseo and thebtctherapist
    # post". Same idempotency: replied set + chokepoint dedup make re-runs
    # free; Graphseo's one-typo rule is enforced at the reply chokepoint.
    for buddy in _buddy_handles():
        if buddy.lower() == BESTIE_HANDLE.lower():
            continue  # already covered by the bestie pass above
        for t in _fresh_posts(buddy):
            url = t["url"]
            if url in load_replied():
                continue
            if buddy.lower() == "graphseo":
                # His dedicated FR generator — the buddy prompt's
                # match-the-language rule shipped an English reply to a
                # short FR post (operator 2026-06-07).
                from .direct_reply import _generate_graphseo_reply
                reply = _generate_graphseo_reply(t.get("text", ""))
            else:
                reply = generate_vip_reply(BUDDY_REPLY_PROMPT, t.get("text", ""), REPLY_MODEL,
                             "BUDDY_BLITZ_REPLY", author=buddy)
            if not reply:
                continue
            reply = smart_trim(humanize(reply), 278)
            try:
                if reply_to_tweet(url, reply):
                    log_reply(url, reply, action_type="reply", source="BUDDY-BLITZ")
                    replies_done += 1
            except Exception:
                traceback.print_exc()
    log.info(f"[BTC-BLITZ] Done: {replies_done} replies "
             f"(bestie + buddies: {', '.join(_buddy_handles())}).")


def safe_run_btc_blitz_cycle() -> None:
    from . import health
    try:
        run_btc_blitz_cycle()
        health.record_success("btc_blitz")
    except Exception:
        log.info("[BTC-BLITZ] outer error:")
        traceback.print_exc()
        health.record_failure("btc_blitz")
