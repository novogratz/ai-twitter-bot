"""Feed discovery and Replies, with an optional For You first strategy.

For You first mode drafts after its short scan and only visits Following
occasionally, after the primary turn. Ordinary sources stay within an hour.
Legacy mode retains the combined two-feed scan before drafting.

Hard rules preserved:
  - replies obey DIRECT_REPLY_MAX_AGE_MINUTES
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
from . import reply_pipeline, reply_source, candidate_buffer
from .direct_reply import reply_call

_for_you_cycles = 0  # Disposable discovery cadence, never a publication claim.


def _for_you_first():
    return settings.get("REPLY_BROAD_DISCOVERY") and settings.get("REPLY_FOR_YOU_FIRST")


def _fresh_candidate_ready(tweets):
    """End the skim once a recent, relevant parent merits its exact-source read."""
    from ..guards import reply_admission, reply_selection
    declaration = reply_source.Declaration(
        max_age=timedelta(minutes=min(30, settings.get("DIRECT_REPLY_MAX_AGE_MINUTES"))),
        root_only=True, niche=True, order=reply_source.Order.FRESH_AND_RISING)
    minimum = reply_selection.minimum_likes()
    for candidate in reply_source.select(tweets, declaration, "FEED-SWEEP-FEED"):
        if (type(candidate.likes) is int and candidate.likes >= max(5, minimum)
                and not reply_selection.source_refusal(candidate.url, candidate.text)
                and reply_admission.judge_parent(candidate.url)):
            return True
    return False


def _scan_feed(source):
    from ..x.scraper import scrape_home_feed, scrape_following_feed
    read = scrape_home_feed if source == "FEED" else scrape_following_feed
    log.info("[SWEEP] Scanning %s before drafting...", "FOR YOU" if source == "FEED" else source)
    options = {"stop_when": _fresh_candidate_ready} if source == "FEED" and _for_you_first() else {}
    tweets = reply_pipeline.scrape("SWEEP", source, read,
                                  max_tweets=settings.get("FEED_SWEEP_SCAN_LIMIT"), text_limit=1200, **options)
    log.info("[SWEEP] %s scan complete: %s posts.", source, len(tweets))
    return tweets


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
            if not reply_source.is_on_niche(t.get("text") or ""):
                continue
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
    """Draft from For You immediately when primary; secondary reads come later."""
    global _for_you_cycles
    run_feed_discovery_cycle()
    cycle = run_feed_reply_cycle()
    if _for_you_first():
        _for_you_cycles += 1
        if not cycle.rate_limited and _for_you_cycles % settings.get("FEED_FOLLOWING_EVERY_CYCLES") == 0:
            _buffer_one_feed("FOLLOWING", _scan_feed("FOLLOWING"))
            _sweep_one_feed("FOLLOWING", cycle)


def run_feed_discovery_cycle():
    """Refresh the primary feed, or both feeds in the legacy strategy."""
    feeds = []
    for source in (("FEED",) if _for_you_first() else ("FEED", "FOLLOWING")):
        feeds.append((source, _scan_feed(source)))
    # Retain both discoveries even if drafting the first feed hits a quota.
    for source, tweets in feeds:
        _buffer_one_feed(source, tweets)


def run_feed_reply_cycle():
    cycle = reply_pipeline.Cycle()
    for source in (("FEED",) if _for_you_first() else ("FEED", "FOLLOWING")):
        _sweep_one_feed(source, cycle)
        if cycle.rate_limited:
            break
    return cycle


def _buffer_one_feed(source, tweets):
    if not tweets:
        log.info(f"[SWEEP] No tweets scraped from {source}.")
        return

    label = f"FEED-SWEEP-{source}"
    # No shuffle: fresh-and-rising first (2026-06-07 spec — front-load
    # <60-min climbers).
    max_minutes = settings.get("DIRECT_REPLY_MAX_AGE_MINUTES")
    if _for_you_first():
        max_minutes = min(max_minutes, 60)
    declaration = reply_source.Declaration(
        max_age=timedelta(minutes=max_minutes),
        root_only=True, niche=True, order=reply_source.Order.FRESH_AND_RISING)
    reply_candidates = reply_source.select(tweets, declaration, label)

    eligible = {candidate.url for candidate in reply_candidates}
    _harvest_active_authors([tweet for tweet in tweets if tweet.get("url") in eligible]
                            if _for_you_first() else tweets)

    candidate_buffer.FEEDS[source].offer(reply_candidates, max_age=declaration.max_age)


def _sweep_one_feed(source, cycle):
    # The legacy lookahead prepares the next source in Safari before sending
    # the ready draft. Primary-feed Replies should not wait for another source.
    job = reply_pipeline.Job("feed_sweep", f"FEED-SWEEP-{source}", reply_call=reply_call,
                             pipelined=not _for_you_first())
    replies_done = candidate_buffer.FEEDS[source].run(
        job, cycle, max_generations=settings.reply_budget("FEED_SWEEP_MAX_REPLIES_PER_CYCLE"),
        **({"max_shipped": 1} if _for_you_first() else {}))
    log.info(f"[SWEEP] {source} done: {replies_done} replies.")
