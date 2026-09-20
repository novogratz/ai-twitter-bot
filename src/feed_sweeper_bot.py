"""Feed sweeper — useful replies to fresh AI posts in the For You / Following feed.

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

2026-06-06 additions:
  - GIF quotes: _generate_quote already asks the LLM for a [GIF: ...] tag;
    we now extract it and call quote_tweet_with_gif() so GIFs actually post.
  - Active author harvesting: authors of high-engagement feed posts are added
    to dynamic_accounts.json so the engage_bot visits them instead of the old
    static list.

Hard rules preserved:
  - ⛔ quotes obey the 48h REPOST_MAX_AGE_HOURS rule (via _too_old_to_quote)
  - replies obey DIRECT_REPLY_MAX_AGE_MINUTES (72h since 2026-06-05)
  - blocklist / respect-list / own-handle filtered
  - all writes go through the twitter_client chokepoints (dedup v2 included)
"""
import os
import traceback

from .config import BLOCKLIST, BOT_HANDLE
from .logger import log

_OWN_HANDLE = BOT_HANDLE.lower()

FEED_SWEEP_QUOTE_MIN_LIKES = int(os.environ.get("FEED_SWEEP_QUOTE_MIN_LIKES", "50"))
FEED_SWEEP_SCAN_LIMIT = int(os.environ.get("FEED_SWEEP_SCAN_LIMIT", "80"))
FEED_SWEEP_MAX_QUOTES_PER_CYCLE = int(os.environ.get("FEED_SWEEP_MAX_QUOTES_PER_CYCLE", "4"))
FEED_SWEEP_MAX_REPLIES_PER_CYCLE = int(os.environ.get("FEED_SWEEP_MAX_REPLIES_PER_CYCLE", "8"))
BANGER_LIKES = int(os.environ.get("FEED_SWEEP_BANGER_LIKES", "1000"))

# Authors with at least this many likes on a post get added to dynamic_accounts.
HARVEST_MIN_LIKES = int(os.environ.get("FEED_SWEEP_HARVEST_MIN_LIKES", "100"))


def _handle_from_url(url: str) -> str:
    try:
        return (url or "").split("x.com/")[1].split("/")[0].lower()
    except (IndexError, AttributeError):
        return ""


def _harvest_active_authors(tweets: list) -> None:
    """Add authors of high-engagement feed posts to dynamic_accounts.json.

    This is the main way the engage_bot discovers NEW profiles to visit — it
    no longer relies on the old hardcoded list. Only handles with a valid X
    format (1-15 alphanumeric/_) are stored.
    """
    if not tweets:
        return
    try:
        from .dynamic_strategy import add_dynamic_accounts, get_dynamic_accounts
        existing = get_dynamic_accounts()
        known = set(h.lower() for bucket in ("en", "fr") for h in existing.get(bucket, []))
        known.update(BLOCKLIST)
        known.add(_OWN_HANDLE)

        new_handles = []
        for t in tweets:
            likes = int(t.get("likes") or 0)
            if likes < HARVEST_MIN_LIKES:
                continue
            author = (t.get("author") or "").lstrip("@").strip()
            if not author or author.lower() in known:
                continue
            # Only keep valid X handles (1-15 chars, alphanumeric/_).
            if len(author) > 15 or not all(c.isascii() and (c.isalnum() or c == "_") for c in author):
                continue
            new_handles.append(author)
            known.add(author.lower())

        if new_handles:
            added = add_dynamic_accounts(en=new_handles)
            if added:
                log.info(f"[SWEEP] Harvested {added} new active author(s) into dynamic_accounts.")
    except Exception:
        log.info("[SWEEP] Author harvest failed (non-fatal):")
        traceback.print_exc()


def run_feed_sweep_cycle():
    """Sweep BOTH For You and Following every cycle — the primary loop."""
    from .twitter_client import scrape_home_feed, scrape_following_feed
    for source, scraper in (("FEED", scrape_home_feed), ("FOLLOWING", scrape_following_feed)):
        _sweep_one_feed(source, scraper)


def _sweep_one_feed(source, scraper):
    from .twitter_client import quote_tweet, quote_tweet_with_gif
    from .humanizer import extract_gif_query
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

    # Harvest active authors from this feed pass before filtering.
    _harvest_active_authors(tweets)

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
        # Every eligible item can receive a useful reply, including popular
        # ones formerly diverted to the quote lane.
        if url not in replied:
            reply_candidates.append(t)

    quotes_done = 0

    # --- REPLY to the meh ones --------------------------------------------
    # No shuffle: _reply_to_tweets orders fresh-and-rising first
    # (2026-06-07 spec — front-load <60-min climbers).
    replies_done = _reply_to_tweets(
        reply_candidates,
        replied,
        f"FEED-SWEEP-{source}",
        remaining=FEED_SWEEP_MAX_REPLIES_PER_CYCLE,
        en_counter=[0],
    )
    log.info(f"[SWEEP] {source} done: {quotes_done} quotes, {replies_done} replies.")


def safe_run_feed_sweep_cycle():
    from . import health
    try:
        run_feed_sweep_cycle()
        health.record_success("feed_sweep")
    except Exception:
        log.info("[SWEEP] Error during feed sweep cycle:")
        traceback.print_exc()
        health.record_failure("feed_sweep")
