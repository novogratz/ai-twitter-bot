"""Collect For You, Following Recent/Popular and rotating Latest topic searches.

Every discovery is archived before filtering; only on-topic standalone posts
enter comparison. Saved authors still need current topic evidence for engagement.
"""
import traceback
from datetime import timedelta

from ..x import x_urls
from ..core import account, config, settings
from ..core.logger import log
from ..guards.reply_admission import is_blocked_account
from . import reply_pipeline, reply_source
from .direct_reply import reply_call

_FEED_OFFSET = 0
_SEARCH_OFFSET = 0


def _harvest_active_authors(tweets: list) -> None:
    """Add authors of high-engagement feed posts to dynamic_accounts.json.

    This record alone never authorizes engagement: current topic evidence is
    required by the discovery policy. The handle comes from the
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
            if not handle or handle in known or config.is_own_handle(handle) or is_blocked_account(handle):
                continue
            if not reply_source.is_on_niche(t.get("text") or ""):
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
    """One rotating feed view plus one Latest search, yielding between pages."""
    global _FEED_OFFSET, _SEARCH_OFFSET
    from functools import partial
    from ..x.scraper import scrape_x_search, scrape_home_feed, scrape_following_feed
    views = [("FOR-YOU", scrape_home_feed),
             ("FOLLOWING-RECENT", partial(scrape_following_feed, sort="recent")),
             ("FOLLOWING-POPULAR", partial(scrape_following_feed, sort="popular"))]
    source, read = views[_FEED_OFFSET % len(views)]
    _FEED_OFFSET += 1
    cycle = reply_pipeline.Cycle()
    _sweep_one_feed(source, read, cycle)
    if cycle.rate_limited:
        return
    queries = list(account.current().searches.replies)
    if queries:
        query = queries[_SEARCH_OFFSET % len(queries)]
        _SEARCH_OFFSET += 1
        _sweep_one_feed("TOPIC/" + query[:60],
                        partial(scrape_x_search, query, tab="live", text_limit=2000), cycle)


def _sweep_one_feed(source, scraper, cycle):
    log.info(f"[SWEEP] Sweeping {source} (save posts for selective replies)...")
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
    log.info(f"[SWEEP] {source} done: {len(reply_candidates)} candidates saved for selection.")
