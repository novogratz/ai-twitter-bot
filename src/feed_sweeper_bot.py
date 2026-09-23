"""Feed sweeper — useful replies to fresh AI posts in the For You / Following feed.

Scroll For You and Following and reply to every on-niche post. The quote
lane that once amplified viral posts is gone (2026-09-20 policy: quotes are
zero). Authors of high-engagement feed posts are added to
dynamic_accounts.json so the engage_bot visits them.

Hard rules preserved:
  - replies obey DIRECT_REPLY_MAX_AGE_MINUTES (72h since 2026-06-05)
  - Reply admission (Blocked account, own post, already Replied) judges
    each post before generation, through direct_reply's pipeline
  - all writes go through the twitter_client chokepoints
"""
import os
import traceback

from .x import x_urls
from .core.config import BLOCKLIST, BOT_HANDLE
from .core.logger import log

_OWN_HANDLE = BOT_HANDLE.lower()

FEED_SWEEP_SCAN_LIMIT = int(os.environ.get("FEED_SWEEP_SCAN_LIMIT", "80"))
FEED_SWEEP_MAX_REPLIES_PER_CYCLE = int(os.environ.get("FEED_SWEEP_MAX_REPLIES_PER_CYCLE", "8"))

# Authors with at least this many likes on a post get added to dynamic_accounts.
HARVEST_MIN_LIKES = int(os.environ.get("FEED_SWEEP_HARVEST_MIN_LIKES", "100"))

# Posts this job is done with until restart: definitive Reply admission
# refusals, posts the model declined, posts answered.
_skipped: set = set()


def _harvest_active_authors(tweets: list) -> None:
    """Add authors of high-engagement feed posts to dynamic_accounts.json.

    This is the main way the engage_bot discovers NEW profiles to visit — it
    no longer relies on the old hardcoded list. Only handles with a valid X
    format (1-15 alphanumeric/_) are stored.
    """
    if not tweets:
        return
    try:
        from .core.dynamic_strategy import add_dynamic_accounts, get_dynamic_accounts
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
    from .x.twitter_client import scrape_home_feed, scrape_following_feed
    for source, scraper in (("FEED", scrape_home_feed), ("FOLLOWING", scrape_following_feed)):
        _sweep_one_feed(source, scraper)


def _sweep_one_feed(source, scraper):
    from .direct_reply import _reply_to_tweets, _is_on_niche

    log.info(f"[SWEEP] Sweeping {source} (reply to every on-niche post)...")
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

    reply_candidates = []
    for t in tweets:
        url = t.get("url") or ""
        text = (t.get("text") or "").strip()
        if not url or not text:
            continue
        if x_urls.is_reply_like_tweet(t):
            continue
        if not _is_on_niche(text):
            continue
        reply_candidates.append(t)

    # No shuffle: _reply_to_tweets orders fresh-and-rising first
    # (2026-06-07 spec — front-load <60-min climbers).
    replies_done = _reply_to_tweets(
        reply_candidates,
        set(),
        f"FEED-SWEEP-{source}",
        remaining=FEED_SWEEP_MAX_REPLIES_PER_CYCLE,
        en_counter=[0],
        skipped=_skipped,
    )
    log.info(f"[SWEEP] {source} done: {replies_done} replies.")


def safe_run_feed_sweep_cycle():
    from .core import health
    try:
        run_feed_sweep_cycle()
        health.record_success("feed_sweep")
    except Exception:
        log.info("[SWEEP] Error during feed sweep cycle:")
        traceback.print_exc()
        health.record_failure("feed_sweep")
