"""Reply bot: finds AI tweets and posts troll replies."""
import os
import traceback
from datetime import timedelta
from ..x import x_urls
from ..core.config import MAX_REPLIES_PER_CYCLE
from ..core.logger import log
from . import reply_pipeline
from .reply_agent import generate_replies
from ..x.scraper import refresh_feed
from ..core.history import get_recent_tweets
from ..guards.replied_store import load_replied

# The model call that finds the posts also writes their replies: the
# candidates carry their text, and no voice is needed.
JOB = reply_pipeline.Job("reply_search", "REPLY", voice=None, pause=(15, 15))


def _reply_search_enabled() -> bool:
    """Read at call time (side-effect-env rule) so a live .env edit takes
    effect without code changes at the next cycle.

    Default OFF (2026-07-19): the LLM-web-search discovery path cannot find
    fresh tweets — web search doesn't index ≤24h x.com content — so the model
    either hallucinated URLs (PR #59) or, with the stale FR-era persona prompt,
    answered conversationally ("tu veux que je fasse quoi?"). Measured over
    35h of logs: 388 failed Claude CLI calls, 1 reply shipped, vs ~880 replies
    from the Safari-scrape direct_reply pipeline in the same window. Each
    cycle also burned a refresh_feed() Safari touch every ~3 min.
    """
    return os.environ.get("ENABLE_REPLY_SEARCH", "0") == "1"


def run_reply_cycle():
    """Search for popular AI tweets and reply with a sharp one-liner."""
    if not _reply_search_enabled():
        log.info("[REPLY] LLM-search reply surface disabled (ENABLE_REPLY_SEARCH=0) — direct_reply carries reply volume.")
        return
    if MAX_REPLIES_PER_CYCLE <= 0:
        log.info("[REPLY] Reply cap is 0. No search/model call this cycle.")
        return

    refresh_feed()
    log.info("[REPLY] Scanning for tweets to reply to...")

    # One model call both finds the targets and drafts the replies, so Reply
    # admission can only judge a target once it is known. Passing the Replied
    # store steers the search away from answered posts; an unreadable store
    # raises here, before the model is paid.
    replied = load_replied()

    # Cross-dedup: pass recent post topics so replies don't overlap
    recent_posts = get_recent_tweets(hours=6)
    replies = generate_replies(
        recent_topics=recent_posts if recent_posts else None,
        already_replied=replied,
    )

    if replies is None:
        log.info("[REPLY] No good tweets found - skipping this cycle.")
        return

    # Growth push: the model already ranked the batch; ship more good targets
    # per scan while MAX_REPLIES_PER_CYCLE still controls the hard ceiling.
    limit = min(20, MAX_REPLIES_PER_CYCLE)
    candidates = []
    for data in replies:
        url = data.get("tweet_url", "")
        if not url or not data.get("reply"):
            continue
        if data.get("type", "reply") == "quote":
            log.info(f"[REPLY] Quote action disabled - skipping {url}")
            continue
        if x_urls.is_reply_like_tweet({"url": url, "text": data.get("tweet_text") or data.get("text") or ""}):
            log.info(f"[REPLY] Looks like a thread reply - skipping {url}")
            continue

        # HARD RECENCY CHECK: the status ID carries the post time; no ID, or
        # older than 48h, is skipped.
        age = x_urls.age(url)
        if age is None or age > timedelta(hours=48):
            log.info(f"[REPLY] No status ID or older than 48h - skipping: {url}")
            continue
        candidates.append(reply_pipeline.Candidate(
            url, data.get("tweet_text") or data.get("text") or "", "", reply=data["reply"],
            pattern=data.get("pattern", ""), provider=data.get("provider", ""),
            model=data.get("model", "")))

    # The limit counts the targets Reply admission lets through.
    posted_count = reply_pipeline.run(JOB, candidates, reply_pipeline.Cycle(), max_generations=limit)
    log.info(f"[REPLY] Posted {posted_count} replies this cycle.")


def safe_run_reply_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from ..core import health
    try:
        run_reply_cycle()
        health.record_success("reply")
    except Exception:
        log.info("[REPLY] Error during reply cycle:")
        traceback.print_exc()
        health.record_failure("reply")
