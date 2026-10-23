"""Feed sweeper — useful replies to fresh on-niche posts in the For You / Following feed.

Scroll For You and Following and reply to every on-niche post. The quote
lane that once amplified viral posts is gone (2026-09-20 policy: quotes are
zero). Authors of high-engagement feed posts are added to
dynamic_accounts.json so the engage_bot visits them.

Hard rules preserved:
  - replies obey DIRECT_REPLY_MAX_AGE_MINUTES (72h since 2026-06-05)
  - Reply admission (Blocked account, own post, already Replied) judges
    each post before generation, in the Reply pipeline
  - all writes go through the twitter_client chokepoints
"""
import traceback
from datetime import timedelta

from ..x import x_urls
from ..core import config, settings
from ..core.logger import log
from ..guards.reply_admission import is_blocked_account
from . import reply_pipeline, reply_source
from .direct_reply import reply_call


def _harvest_active_authors(tweets: list) -> None:
    """Add authors of high-engagement feed posts to dynamic_accounts.json.

    This is the main way the engage_bot discovers NEW profiles to visit — it
    no longer relies on the old hardcoded list. The handle comes from the
    status URL: the scraped `author` is a display name, and a one-word name
    ("Claude", "Tesla") once landed in the pool as another account's handle.
    """
    if not tweets:
        return
    try:
        from ..core.dynamic_strategy import add_dynamic_accounts, get_dynamic_accounts
        existing = get_dynamic_accounts()
        known = set(h.lower() for bucket in ("en", "fr") for h in existing.get(bucket, []))
        known.add(config.BOT_HANDLE.lower())

        min_likes = settings.get("FEED_SWEEP_HARVEST_MIN_LIKES")
        new_handles = []
        for t in tweets:
            likes = int(t.get("likes") or 0)
            if likes < min_likes:
                continue
            handle = x_urls.author(t.get("url") or "")
            if not handle or handle in known or is_blocked_account(handle):
                continue
            new_handles.append(handle)
            known.add(handle)

        if new_handles:
            added = add_dynamic_accounts(en=new_handles)
            if added:
                log.info(f"[SWEEP] Harvested {added} new active author(s) into dynamic_accounts.")
    except Exception:
        log.info("[SWEEP] Author harvest failed (non-fatal):")
        traceback.print_exc()


def run_feed_sweep_cycle():
    """Sweep BOTH For You and Following every cycle — the primary loop."""
    from ..x.scraper import scrape_home_feed, scrape_following_feed
    for source, scraper in (("FEED", scrape_home_feed), ("FOLLOWING", scrape_following_feed)):
        cycle = reply_pipeline.Cycle()
        _sweep_one_feed(source, scraper, cycle)
        if cycle.rate_limited:
            break


def _sweep_one_feed(source, scraper, cycle):
    log.info(f"[SWEEP] Sweeping {source} (reply to every on-niche post)...")
    tweets = reply_pipeline.scrape("SWEEP", source, scraper, max_tweets=settings.get("FEED_SWEEP_SCAN_LIMIT"))
    if not tweets:
        log.info(f"[SWEEP] No tweets scraped from {source}.")
        return

    # Harvest active authors from this feed pass before filtering.
    _harvest_active_authors(tweets)

    label = f"FEED-SWEEP-{source}"
    # No shuffle: fresh-and-rising first (2026-06-07 spec — front-load
    # <60-min climbers).
    declaration = reply_source.Declaration(
        max_age=timedelta(minutes=settings.get("DIRECT_REPLY_MAX_AGE_MINUTES")),
        root_only=True, niche=True, order=reply_source.Order.FRESH_AND_RISING)
    reply_candidates = reply_source.select(tweets, declaration, label)

    job = reply_pipeline.Job("feed_sweep", label, reply_call=reply_call, pipelined=True)
    replies_done = reply_pipeline.run(job, reply_candidates, cycle,
                                      max_generations=settings.get("FEED_SWEEP_MAX_REPLIES_PER_CYCLE"))
    log.info(f"[SWEEP] {source} done: {replies_done} replies.")
