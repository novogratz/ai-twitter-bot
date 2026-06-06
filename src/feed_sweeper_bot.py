"""Feed sweeper — act on EVERY fresh on-niche post in the For You / Following feed.

Operator mandate 2026-06-05 ("it's simple"): scroll the main feed and engage
with every post you see —
  - GOOD post (viral / high-signal)  → QUOTE-retweet it with a clever take
  - meh / weak post                  → REPLY with a substantive comment

"Good" is decided deterministically by engagement velocity proxy (likes >=
FEED_SWEEP_QUOTE_MIN_LIKES): viral posts get amplified with our angle on top
(quote = we ride their reach), everything else gets a reply (reply = we farm
the conversation). The LLM still gets the final word — a quote/reply that
doesn't clear content_guard is skipped, and the action_guard chokepoints
(caps + jittered spacing) gate total volume.

Hard rules preserved:
  - ⛔ quotes obey the 48h REPOST_MAX_AGE_HOURS rule (via _too_old_to_quote)
  - replies obey DIRECT_REPLY_MAX_AGE_MINUTES (72h since 2026-06-05)
  - blocklist / respect-list / own-handle filtered
  - all writes go through the twitter_client chokepoints (dedup v2 included)
"""
import os
import random
import traceback

from .config import BLOCKLIST, BOT_HANDLE
from .logger import log

_OWN_HANDLE = BOT_HANDLE.lower()

# likes >= this → "good post" → quote; below → reply.
# 2026-06-05 PM: 300→200 + 3→4/cycle (operator: quote-RT extremely
# successful, "abuse a bit of it for the next few weeks").
FEED_SWEEP_QUOTE_MIN_LIKES = int(os.environ.get("FEED_SWEEP_QUOTE_MIN_LIKES", "200"))
FEED_SWEEP_SCAN_LIMIT = int(os.environ.get("FEED_SWEEP_SCAN_LIMIT", "50"))
FEED_SWEEP_MAX_QUOTES_PER_CYCLE = int(os.environ.get("FEED_SWEEP_MAX_QUOTES_PER_CYCLE", "4"))
FEED_SWEEP_MAX_REPLIES_PER_CYCLE = int(os.environ.get("FEED_SWEEP_MAX_REPLIES_PER_CYCLE", "8"))

# Both feeds are swept EVERY cycle (operator 2026-06-06: "go to FOR YOU
# page and FOLLOWING page... refresh the page, there is always content" —
# this is the bot's primary activity loop).
BANGER_LIKES = int(os.environ.get("FEED_SWEEP_BANGER_LIKES", "1000"))


def _handle_from_url(url: str) -> str:
    try:
        return (url or "").split("x.com/")[1].split("/")[0].lower()
    except (IndexError, AttributeError):
        return ""


def run_feed_sweep_cycle():
    """Sweep BOTH For You and Following every cycle — the primary loop."""
    from .twitter_client import scrape_home_feed, scrape_following_feed
    for source, scraper in (("FEED", scrape_home_feed), ("FOLLOWING", scrape_following_feed)):
        _sweep_one_feed(source, scraper)


def _sweep_one_feed(source, scraper):
    from .twitter_client import quote_tweet
    from .quote_tweet_bot import _load_quoted, _save_quoted, _generate_quote, _too_old_to_quote
    from .direct_reply import _reply_to_tweets, load_replied, _is_on_niche, _is_reply_like_tweet
    from . import content_guard, respect_list

    log.info(f"[SWEEP] Sweeping {source} (quote >= {FEED_SWEEP_QUOTE_MIN_LIKES} likes, reply below, BOTH >= {BANGER_LIKES})...")
    try:
        tweets = scraper(max_tweets=FEED_SWEEP_SCAN_LIMIT) or []
    except Exception:
        log.info(f"[SWEEP] {source} scrape failed:")
        traceback.print_exc()
        return
    if not tweets:
        log.info(f"[SWEEP] No tweets scraped from {source}.")
        return

    quoted = _load_quoted()
    replied = load_replied()

    quote_candidates = []
    reply_candidates = []
    for t in tweets:
        url = t.get("url") or ""
        text = (t.get("text") or "").strip()
        author = (t.get("author") or "").lower()
        if not url or not text:
            continue
        handle = _handle_from_url(url)
        if handle == _OWN_HANDLE or author == _OWN_HANDLE:
            continue
        if handle in BLOCKLIST or author in BLOCKLIST:
            continue
        if _is_reply_like_tweet(t):
            continue
        if not _is_on_niche(text):
            continue
        likes = int(t.get("likes") or 0)
        if likes >= FEED_SWEEP_QUOTE_MIN_LIKES and url not in quoted:
            # Respect-list authors are never quote-called-out; reply instead.
            if respect_list.is_protected(t.get("author", "")):
                if url not in replied:
                    reply_candidates.append(t)
            else:
                quote_candidates.append(t)
                # BANGER (operator: "reply or quote retweet OR BOTH"): on
                # very viral posts do both — the quote rides the reach, the
                # reply farms the thread.
                if likes >= BANGER_LIKES and url not in replied:
                    reply_candidates.append(t)
        elif url not in replied:
            reply_candidates.append(t)

    log.info(f"[SWEEP] {source}: {len(quote_candidates)} quote candidates, {len(reply_candidates)} reply candidates.")

    # --- QUOTE the good ones (most-liked first) ---------------------------
    quote_candidates.sort(key=lambda t: int(t.get("likes") or 0), reverse=True)
    quotes_done = 0
    for cand in quote_candidates:
        if quotes_done >= FEED_SWEEP_MAX_QUOTES_PER_CYCLE:
            break
        if _too_old_to_quote(cand):  # ⛔ hard 48h rule
            continue
        author = cand.get("author", "someone")
        quote = content_guard.generate_validated(
            lambda: _generate_quote(author, cand.get("text", "")),
            kind="quote", label="SWEEP-QUOTE")
        if not quote:
            continue
        try:
            posted = quote_tweet(cand["url"], quote)
        except Exception:
            traceback.print_exc()
            # Unknown state — mark consumed to be safe.
            quoted.add(cand["url"])
            _save_quoted(quoted)
            continue
        if not posted:
            # Spacing/cap at the chokepoint — keep the candidate for later.
            log.info("[SWEEP] Quote chokepoint skipped (spacing/cap) — stopping quote pass.")
            break
        quoted.add(cand["url"])
        _save_quoted(quoted)
        quotes_done += 1
        log.info(f"[SWEEP] Quoted @{author} ({cand.get('likes')} likes).")

    # --- REPLY to the meh ones --------------------------------------------
    random.shuffle(reply_candidates)
    replies_done = _reply_to_tweets(
        reply_candidates,
        replied,
        f"FEED-SWEEP-{source}",
        remaining=FEED_SWEEP_MAX_REPLIES_PER_CYCLE,
        en_counter=[0],
    )
    log.info(f"[SWEEP] {source} done: {quotes_done} quotes, {replies_done} replies.")


def safe_run_feed_sweep_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_feed_sweep_cycle()
        health.record_success("feed_sweep")
    except Exception:
        log.info("[SWEEP] Error during feed sweep cycle:")
        traceback.print_exc()
        health.record_failure("feed_sweep")
