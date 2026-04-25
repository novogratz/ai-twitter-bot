"""Reply bot: finds AI tweets and posts troll replies."""
import json
import os
import re
import time
import traceback
from datetime import datetime, timezone
from .config import REPLIED_FILE, BLOCKLIST, BOT_HANDLE
from .logger import log

_OWN_HANDLE = BOT_HANDLE.lower()


def _handle_from_url(tweet_url: str) -> str:
    """Extract @handle (lowercase, no @) from a tweet URL. Empty string if not found."""
    m = re.search(r"x\.com/([^/]+)/status/", tweet_url)
    return m.group(1).lower() if m else ""


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
from .twitter_client import reply_to_tweet, quote_tweet, refresh_feed
from .history import get_recent_tweets
from .engagement_log import log_reply
from .humanizer import humanize


def load_replied() -> set:
    """Load set of tweet URLs we already replied to."""
    if os.path.exists(REPLIED_FILE):
        with open(REPLIED_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_replied(urls: set):
    """Save the set of replied tweet URLs."""
    # Keep only the last 2000 - URLs are tiny, longer memory = stronger dedup
    url_list = list(urls)[-2000:]
    with open(REPLIED_FILE, "w") as f:
        json.dump(url_list, f, indent=2)


def run_reply_cycle():
    """Search for popular AI tweets and reply with a sharp one-liner."""
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

    # Pre-filter pass: drop blocklisted handles, already-replied URLs, and intra-batch dupes.
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
        handle = _handle_from_url(url)
        if handle and handle in BLOCKLIST:
            log.info(f"[REPLY] Blocklisted handle @{handle} - dropping: {url}")
            continue
        if handle == _OWN_HANDLE:
            log.info(f"[REPLY] Own tweet @{handle} - dropping: {url}")
            continue
        seen_in_batch.add(url)
        filtered.append(data)

    # Hard cap: 2 replies per cycle. Reply bot fires every ~30min so this caps
    # us at ~80 replies/day which is plausibly human. The agent sometimes
    # returns 4-5 candidates — we keep only the top 2 (preserves agent ordering,
    # which we've prompted to be impact-ranked).
    replies = filtered[:2]

    if not replies:
        log.info("[REPLY] All replies filtered (dedup/blocklist) - skipping cycle.")
        save_replied(replied)
        return

    posted_count = 0

    for data in replies:
        url = data["tweet_url"]
        action_type = data.get("type", "reply")

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

        # HARD RECENCY CHECK: reject tweets older than 7 days (10080 min)
        age = _tweet_age_minutes(url)
        if age > 10080:
            log.info(f"[REPLY] Tweet is {age} min old (~{age // 1440}d) - TOO OLD, skipping: {url}")
            continue

        reply_text = humanize(data["reply"])
        log.info(f"[REPLY] Target: {url}")
        log.info(f"[REPLY] {action_type.upper()} ({len(reply_text)} chars): {reply_text}")

        # Lock the URL in BEFORE posting. If the post call gets interrupted
        # (network blip, AppleScript hang, OS kill) after the tweet went
        # through, we still won't re-reply on the next cycle.
        replied.add(url)
        save_replied(replied)

        try:
            if action_type == "quote":
                quote_tweet(url, reply_text)
            else:
                reply_to_tweet(url, reply_text)
            posted_count += 1
            log_reply(url, data["reply"], action_type)
            # Wait between replies so browser can catch up
            if posted_count < len(replies):
                log.info("[REPLY] Waiting 15 seconds before next action...")
                time.sleep(15)
        except Exception:
            log.info(f"[REPLY] Failed to {action_type} {url}:")
            traceback.print_exc()

    save_replied(replied)
    log.info(f"[REPLY] Posted {posted_count} replies/quotes this cycle.")


def safe_run_reply_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_reply_cycle()
    except Exception:
        log.info("[REPLY] Error during reply cycle:")
        traceback.print_exc()
