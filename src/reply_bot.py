"""Reply bot: finds AI tweets and posts troll replies."""
import json
import os
import re
import time
import traceback
from datetime import datetime, timezone
from .config import MAX_REPLIES_PER_CYCLE, REPLIED_FILE, BLOCKLIST, BOT_HANDLE
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
from .twitter_client import reply_to_tweet, retweet_post, refresh_feed
from .history import get_recent_tweets
from .engagement_log import log_reply
from .humanizer import humanize


_REPLIED_CAP = 50000


def _canonical_tweet_id(url: str) -> str:
    """Extract the status ID from a tweet URL.

    Status IDs are globally unique on X, but the SAME tweet can surface
    under multiple author URLs because feed-scraping sometimes mis-attributes
    the author handle (e.g. when a tweet shows in a profile via quote / RT
    context). Dedup keyed on the raw URL string would let the same tweet
    get replied to multiple times under different scraped prefixes.

    Bug 2026-05-17: status 2056061134629933072 got 3 replies same day under
    @elonmusk, @ABaradez, @LeJournalDuCoin URLs — all same actual tweet.
    """
    if not url:
        return ""
    m = re.search(r"/status/(\d+)", url)
    if m:
        return m.group(1)
    return url.strip().lower()


class _CanonReplied(set):
    """Set wrapper that canonicalizes URLs to status IDs on add/contains.
    Lets existing call sites use `url in replied` / `replied.add(url)`
    unchanged while the underlying storage is keyed on status ID."""

    def __contains__(self, item) -> bool:
        return super().__contains__(_canonical_tweet_id(item))

    def add(self, item) -> None:
        super().add(_canonical_tweet_id(item))

    def update(self, items) -> None:
        for x in items:
            self.add(x)


def load_replied() -> set:
    """Return a canonicalizing set so `url in replied` dedupes on status ID."""
    raw: list[str] = []
    if os.path.exists(REPLIED_FILE):
        try:
            with open(REPLIED_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                raw = [str(u) for u in data if u]
            elif isinstance(data, dict):
                raw = [str(u) for u in (data.get("urls") or []) if u]
        except (json.JSONDecodeError, OSError):
            raw = []
    s = _CanonReplied()
    for item in raw:
        s.add(item)
    return s


def save_replied(urls: set):
    """Save replied URLs preserving insertion order.

    Bug 2026-05-16: previous impl was `list(urls)[-2000:]` which slices a
    Python SET. Sets are unordered → each save randomly dropped ~half of
    the URLs. URLs fell out of the cache, then another bot rediscovered
    the same tweet days later and replied again. Engagement_log shows 414
    duplicate-reply URLs from this bug.

    Fix: re-read the on-disk ordered list, append any URLs the in-memory
    set has but the file doesn't, cap at 50k from the TAIL (newest), and
    write back as a list. Also re-reading at save time handles parallel
    APScheduler cycles cleanly (last writer merges with whatever landed
    in between).
    """
    existing_list: list[str] = []
    if os.path.exists(REPLIED_FILE):
        try:
            with open(REPLIED_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                existing_list = [u for u in data if isinstance(u, str)]
            elif isinstance(data, dict):
                existing_list = [u for u in (data.get("urls") or []) if isinstance(u, str)]
        except (json.JSONDecodeError, OSError):
            existing_list = []
    existing_set = set(existing_list)
    for u in urls:
        if isinstance(u, str) and u not in existing_set:
            existing_list.append(u)
            existing_set.add(u)
    if len(existing_list) > _REPLIED_CAP:
        existing_list = existing_list[-_REPLIED_CAP:]
    with open(REPLIED_FILE, "w") as f:
        json.dump(existing_list, f, indent=2)


def run_reply_cycle():
    """Search for popular AI tweets and reply with a sharp one-liner."""
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

    # Growth push: the model already ranked the batch; ship more good targets
    # per scan while MAX_REPLIES_PER_CYCLE still controls the hard ceiling.
    replies = filtered[:min(8, MAX_REPLIES_PER_CYCLE)]

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
                log.info("[REPLY] Quote action disabled; plain-reposting instead.")
                retweet_post(url)
                action_type = "retweet"
            else:
                reply_to_tweet(url, reply_text)
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
    log.info(f"[REPLY] Posted {posted_count} replies/quotes this cycle.")


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
