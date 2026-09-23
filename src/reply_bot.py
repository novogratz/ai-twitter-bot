"""Reply bot: finds AI tweets and posts troll replies."""
import os
import re
import time
import traceback
from datetime import datetime, timezone
from .config import MAX_REPLIES_PER_CYCLE, BLOCKLIST, BOT_HANDLE
from .logger import log

_OWN_HANDLE = BOT_HANDLE.lower()


def _handle_from_url(tweet_url: str) -> str:
    """Extract @handle (lowercase, no @) from a tweet URL. Empty string if not found."""
    m = re.search(r"x\.com/([^/]+)/status/", tweet_url)
    return m.group(1).lower() if m else ""


def _is_reply_like_tweet(tweet: dict, expected_author: str = "") -> bool:
    """Return True for nested replies/thread comments we should not target."""
    text = (tweet.get("text") or "").lstrip()
    if text.startswith("@") or bool(tweet.get("is_reply")):
        return True
    expected = (expected_author or "").lower().lstrip("@")
    if expected:
        url_handle = _handle_from_url(tweet.get("url") or "")
        author = (tweet.get("author") or "").lower().lstrip("@")
        if url_handle and url_handle != expected:
            return True
        if author and author not in {"unknown", expected}:
            return True
    return False


# Twitter snowflake epoch (ms since 2010-11-04T01:42:54.657Z)
_TWITTER_EPOCH = 1288834974657


def _tweet_age_minutes(tweet_url: str) -> int:
    """Extract tweet age in minutes from the tweet ID (Twitter snowflake).
    Returns 9999 if we can't parse it."""
    match = re.search(r"/status/(\d+)", tweet_url)
    if not match:
        return 9999
    tweet_id = int(match.group(1))
    timestamp_ms = (tweet_id >> 22) + _TWITTER_EPOCH
    tweet_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    age = datetime.now(tz=timezone.utc) - tweet_time
    return int(age.total_seconds() / 60)
from .reply_agent import generate_replies
from .twitter_client import reply_to_tweet, refresh_feed
from .history import get_recent_tweets
from .engagement_log import log_reply
from .humanizer import humanize
from .replied_store import load_replied, save_replied


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

    # Load already-replied URLs so the agent avoids them
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

    # Pre-filter pass: drop blocklisted handles, already-replied URLs, thread
    # replies, and intra-batch dupes.
    # The in-loop check below is the final safety net.
    seen_in_batch = set()
    filtered = []
    for data in replies:
        url = data.get("tweet_url", "")
        if not url:
            continue
        if url in seen_in_batch:
            log.info(f"[REPLY] Duplicate URL in batch - dropping: {url}")
            continue
        if url in replied:
            log.info(f"[REPLY] Already replied (pre-filter) - dropping: {url}")
            continue
        if _is_reply_like_tweet({"url": url, "text": data.get("tweet_text") or data.get("text") or ""}):
            log.info(f"[REPLY] Looks like a thread reply - dropping: {url}")
            continue
        handle = _handle_from_url(url)
        if handle and handle in BLOCKLIST:
            log.info(f"[REPLY] Blocklisted handle @{handle} - dropping: {url}")
            continue
        if handle == _OWN_HANDLE:
            log.info(f"[REPLY] Own tweet @{handle} - dropping: {url}")
            continue
        seen_in_batch.add(url)
        filtered.append(data)

    # Growth push: the model already ranked the batch; ship more good targets
    # per scan while MAX_REPLIES_PER_CYCLE still controls the hard ceiling.
    replies = filtered[:min(20, MAX_REPLIES_PER_CYCLE)]

    if not replies:
        log.info("[REPLY] All replies filtered (dedup/blocklist) - skipping cycle.")
        save_replied(replied)
        return

    posted_count = 0

    for data in replies:
        url = data["tweet_url"]
        action_type = data.get("type", "reply")
        if action_type == "quote":
            log.info(f"[REPLY] Quote action disabled - skipping {url}")
            continue

        # Skip tweets we already replied to (final safety net)
        if url in replied:
            log.info(f"[REPLY] Already replied to {url} - skipping.")
            continue

        # Blocklist final safety net
        handle = _handle_from_url(url)
        if handle and handle in BLOCKLIST:
            log.info(f"[REPLY] Blocklisted @{handle} - skipping {url}")
            continue

        # Self-reply guard
        if handle == _OWN_HANDLE:
            log.info(f"[REPLY] Own tweet @{handle} - skipping {url}")
            continue

        if _is_reply_like_tweet({"url": url, "text": data.get("tweet_text") or data.get("text") or ""}):
            log.info(f"[REPLY] Looks like a thread reply - skipping {url}")
            continue

        # HARD RECENCY CHECK: reject tweets older than 48h (2880 min)
        age = _tweet_age_minutes(url)
        if age > 2880:
            log.info(f"[REPLY] Tweet is {age} min old (~{age // 60}h) - TOO OLD, skipping: {url}")
            continue

        reply_text = humanize(data["reply"])
        log.info(f"[REPLY] Target: {url}")
        log.info(f"[REPLY] {action_type.upper()} ({len(reply_text)} chars): {reply_text}")

        # ⛔ NO premark — the reply_to_tweet chokepoint marks the store
        # itself right before the Safari write (that IS the crash-safety);
        # a caller-side premark makes the chokepoint refuse its own reply
        # (100% silent self-skip, 2026-06-07 post-mortem).
        replied.add(url)  # in-memory only: no same-cycle retry

        try:
            if not reply_to_tweet(url, reply_text):
                continue  # chokepoint skip — nothing posted, no phantom log
            posted_count += 1
            log_reply(url, data["reply"], action_type, pattern_id=data.get("pattern", ""))
            # Wait between replies so browser can catch up
            if posted_count < len(replies):
                log.info("[REPLY] Waiting 15 seconds before next action...")
                time.sleep(15)
        except Exception:
            log.info(f"[REPLY] Failed to {action_type} {url}:")
            traceback.print_exc()

    save_replied(replied)
    log.info(f"[REPLY] Posted {posted_count} replies this cycle.")


def safe_run_reply_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    from . import health
    try:
        run_reply_cycle()
        health.record_success("reply")
    except Exception:
        log.info("[REPLY] Error during reply cycle:")
        traceback.print_exc()
        health.record_failure("reply")
