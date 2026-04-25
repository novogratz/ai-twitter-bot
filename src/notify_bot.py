"""Notify bot: likes replies on own tweets and replies back to build loyalty."""
import json
import os
import traceback
from .config import _PROJECT_ROOT, BLOCKLIST, BOT_HANDLE
from .logger import log
from .twitter_client import (
    like_own_tweet_replies,
    retweet_own_latest,
    scrape_own_tweet_and_replies,
    reply_to_tweet_in_thread,
    post_tweet,
    visit_profile_and_like,
)
from .replyback_agent import generate_replyback
from .humanizer import humanize
import random

REPLIED_BACK_FILE = os.path.join(_PROJECT_ROOT, "replied_back.json")
_OWN_HANDLE = BOT_HANDLE.lower()


def _influencer_handles() -> set:
    """Merge engage + reply-target lists into a single lowercase set."""
    from .engage_bot import TARGET_ACCOUNTS as ENGAGE_TARGETS
    from .reply_agent import TARGET_ACCOUNTS as REPLY_TARGETS
    return {h.lower() for h in list(ENGAGE_TARGETS) + list(REPLY_TARGETS)}


def _extract_handle(user_string: str) -> str:
    """Extract @handle (lowercase, no @) from a User-Name text blob."""
    if not user_string:
        return ""
    parts = user_string.split("@")
    if len(parts) >= 2:
        # take the last @-prefixed token, strip whitespace
        return parts[-1].split()[0].strip().lower()
    return user_string.strip().lower()


def _load_replied_back() -> set:
    if os.path.exists(REPLIED_BACK_FILE):
        try:
            with open(REPLIED_BACK_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def _save_replied_back(replied: set):
    with open(REPLIED_BACK_FILE, "w") as f:
        json.dump(list(replied)[-500:], f, indent=2)


def run_notify_cycle():
    """Visit own latest tweet, like replies, and build loyalty."""
    log.info("[NOTIFY] Checking replies on latest tweet...")
    like_own_tweet_replies()
    log.info("[NOTIFY] Done.")


def run_replyback_cycle():
    """Scrape replies on own tweets and reply back to create conversation threads.
    Threads boost both tweets in the algorithm. Influencer replies get nested
    in-thread responses (lands UNDER their reply); others get a standalone @mention.
    """
    log.info("[REPLYBACK] Scanning for replies to engage with...")

    data = scrape_own_tweet_and_replies()
    if not data or not data.get("replies"):
        log.info("[REPLYBACK] No replies found.")
        return

    own_tweet = data["own_tweet"]
    replies = data["replies"]
    replied_back = _load_replied_back()
    influencers = _influencer_handles()
    count = 0

    for reply_info in replies[:5]:  # Max 5 reply-backs per cycle
        user = reply_info.get("user", "")
        text = reply_info.get("text", "")
        reply_url = reply_info.get("url", "")
        handle = _extract_handle(user)

        # Skip blocklisted handles (e.g., @pgm_pm)
        if handle and handle in BLOCKLIST:
            log.info(f"[REPLYBACK] Blocklisted @{handle} - skipping.")
            continue

        # Skip our own replies (never reply to ourselves)
        if handle == _OWN_HANDLE or _OWN_HANDLE in user.lower():
            log.info(f"[REPLYBACK] Own reply — skipping.")
            continue

        # Skip very short or empty replies
        if len(text) < 5:
            continue

        # Dedup key: prefer reply URL (stable, unique); fall back to text snippet
        dedup_key = reply_url or f"text:{text[:50]}"
        if dedup_key in replied_back:
            continue

        is_influencer = handle in influencers
        log.info(
            f"[REPLYBACK] {'[INFLUENCER] ' if is_influencer else ''}"
            f"Replying to @{handle}: {text[:60]}..."
        )
        reply = generate_replyback(own_tweet, text)
        if not reply:
            continue

        reply = humanize(reply)
        log.info(f"[REPLYBACK] Reply ({len(reply)} chars): {reply}")

        try:
            if is_influencer and reply_url:
                # Nested in-thread reply — lands directly under their reply
                reply_to_tweet_in_thread(reply_url, reply)
            else:
                # Standalone @mention tweet (existing fallback)
                full_reply = f"@{handle} {reply}" if handle else reply
                post_tweet(full_reply)
            replied_back.add(dedup_key)
            count += 1
        except Exception:
            log.info(f"[REPLYBACK] Failed to reply back:")
            traceback.print_exc()

    _save_replied_back(replied_back)
    log.info(f"[REPLYBACK] Replied back to {count} people.")

    # Reciprocity loop: for non-influencer engagers, visit their profile and
    # like 1 of their tweets. Triggers a notification on their side, often
    # converts to follow-back. Cap small (max 2/cycle) to avoid spam patterns.
    _reciprocate_engagers(replies, influencers)


def _reciprocate_engagers(replies: list, influencers: set, max_visits: int = 2):
    """Visit a few engagers' profiles and like a tweet (reciprocity loop).

    Skip influencers (they don't need our reciprocity, and visiting them
    doesn't move our follower count). Skip blocklist + self. 50% probability
    per eligible engager so the pattern doesn't look mechanical.
    """
    visited = 0
    seen_handles = set()
    candidates = list(replies)
    random.shuffle(candidates)  # don't always hit the same top-of-list person

    for r in candidates:
        if visited >= max_visits:
            break
        handle = _extract_handle(r.get("user", ""))
        if not handle or handle in seen_handles:
            continue
        seen_handles.add(handle)
        if handle in BLOCKLIST or handle == _OWN_HANDLE:
            continue
        if handle in influencers:
            continue  # influencers already notice us via the in-thread reply
        if random.random() > 0.5:
            continue  # randomize so the pattern isn't mechanical

        log.info(f"[RECIPROCATE] Visiting @{handle} to like a tweet back...")
        try:
            visit_profile_and_like(handle, like_count=1)
            visited += 1
        except Exception:
            log.info(f"[RECIPROCATE] Failed to reciprocate @{handle}:")
            traceback.print_exc()

    if visited:
        log.info(f"[RECIPROCATE] Liked back {visited} engager(s).")


def run_boost_cycle():
    """Retweet own latest tweet for extra exposure in followers' feeds."""
    log.info("[BOOST] Boosting latest tweet...")
    retweet_own_latest()
    log.info("[BOOST] Done.")


def safe_run_notify_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_notify_cycle()
    except Exception:
        log.info("[NOTIFY] Error during notify cycle:")
        traceback.print_exc()


def safe_run_replyback_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_replyback_cycle()
    except Exception:
        log.info("[REPLYBACK] Error during replyback cycle:")
        traceback.print_exc()


def safe_run_boost_cycle():
    """Wrapper that catches errors so the scheduler keeps running."""
    try:
        run_boost_cycle()
    except Exception:
        log.info("[BOOST] Error during boost cycle:")
        traceback.print_exc()
